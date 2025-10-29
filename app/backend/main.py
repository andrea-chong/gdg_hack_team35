# app/backend/main.py
import os
import base64
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Google Cloud clients
from google.cloud import texttospeech
from google.cloud import speech
from google.cloud import aiplatform

app = FastAPI(title="ING Voice API", version="1.0.0")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "*"  # keep demo simple; tighten later if you host a fixed origin
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Safety: never 404 on preflight; middleware will inject ACAO headers.
@app.options("/{rest_of_path:path}")
def cors_preflight(rest_of_path: str):
    return Response(status_code=204)

# ---------------- Models ----------------
class TTSIn(BaseModel):
    text: str
    lang: str  # "nl-BE" | "fr-BE" | "en-GB"

class TTSOut(BaseModel):
    audio: str  # base64 MP3

class STTIn(BaseModel):
    audio: str                 # base64-encoded audio
    lang: Optional[str] = None # default set below

class STTOut(BaseModel):
    text: str

class AssistIn(BaseModel):
    audio: str                 # base64 from MediaRecorder (webm/opus)
    lang: Optional[str] = "en-GB"
    context: Optional[str] = None

class AssistOut(BaseModel):
    text: str
    audio: str                 # base64 MP3

# ---------------- Health ----------------
@app.get("/healthz", tags=["Health"])
def healthz():
    return {
        "status": "ok",
        "project": os.getenv("GCP_PROJECT", ""),
        "location": os.getenv("VERTEX_LOCATION", ""),
    }

# ---------------- TTS ----------------
_VOICE_MAP = {
    "en-GB": ("en-GB", "en-GB-Neural2-C"),
    "nl-BE": ("nl-BE", "nl-BE-Standard-A"),
    "fr-BE": ("fr-BE", "fr-BE-Standard-A"),
}

def _tts_text_to_b64mp3(text: str, lang: str) -> str:
    language_code, voice_name = _VOICE_MAP.get(lang, ("en-GB", "en-GB-Neural2-C"))
    tts_client = texttospeech.TextToSpeechClient()
    resp = tts_client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
    )
    return base64.b64encode(resp.audio_content).decode("utf-8")

@app.post("/tts", response_model=TTSOut, tags=["Voice"])
def tts(body: TTSIn):
    if body.lang not in _VOICE_MAP:
        raise HTTPException(status_code=400, detail=f"Unsupported lang '{body.lang}'")
    return TTSOut(audio=_tts_text_to_b64mp3(body.text, body.lang))

# ---------------- STT ----------------
def _stt_bytes_to_text(audio_bytes: bytes, lang: str) -> str:
    """Robust STT: try WEBM_OPUS (browser), then auto, then MP3 44.1k."""
    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(content=audio_bytes)

    # 1) Browser MediaRecorder (webm/opus)
    try:
        cfg = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            language_code=lang,
            enable_automatic_punctuation=True,
            model="latest_short",
        )
        resp = client.recognize(config=cfg, audio=audio)
    except Exception:
        # 2) Auto-detect
        try:
            cfg = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,
                language_code=lang,
                enable_automatic_punctuation=True,
                model="latest_short",
            )
            resp = client.recognize(config=cfg, audio=audio)
        except Exception:
            # 3) MP3 fallback
            cfg = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.MP3,
                sample_rate_hertz=44100,
                language_code=lang,
                enable_automatic_punctuation=True,
                model="latest_short",
            )
            try:
                resp = client.recognize(config=cfg, audio=audio)
            except Exception:
                return ""

    return " ".join(
        r.alternatives[0].transcript for r in resp.results if r.alternatives
    ).strip()

@app.post("/stt", response_model=STTOut, tags=["Voice"])
def stt(body: STTIn):
    lang = body.lang or "en-GB"
    text = _stt_bytes_to_text(base64.b64decode(body.audio), lang)
    return STTOut(text=text)

# ---------------- ASSIST (STT -> reply -> TTS) ----------------
# --- Vertex AI Gemini integration + tiny RAG from local chunks ---

import glob
import re
from collections import Counter

USE_VERTEX = os.getenv("ENABLE_VERTEX", "0") == "1"
CHUNKS_ROOT = os.getenv("CHUNKS_ROOT", "/app/data/chunks")

def _read_text_file(path: str, limit_chars: int = 2000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()[:limit_chars]
    except Exception:
        return ""

def _retrieve_context(query: str, max_docs: int = 5, max_chars: int = 6000) -> str:
    """Naive keyword scorer over *.txt in CHUNKS_ROOT."""
    if not query:
        query = ""
    q_tokens = [t for t in re.findall(r"\b\w+\b", query.lower()) if len(t) > 2]
    q_counts = Counter(q_tokens)
    scored = []
    for path in glob.glob(os.path.join(CHUNKS_ROOT, "**", "*.txt"), recursive=True):
        text = _read_text_file(path, limit_chars=2000)
        if not text:
            continue
        t_tokens = re.findall(r"\b\w+\b", text.lower())
        score = sum(q_counts[t] for t in t_tokens)
        if score == 0 and not q_tokens:
            score = 1  # allow some context when query empty
        scored.append((score, path, text))
    scored.sort(reverse=True, key=lambda x: x[0])
    buf, total = [], 0
    for _, path, text in scored[:max_docs]:
        if total >= max_chars:
            break
        block = f"\n\n[DOC: {os.path.basename(path)}]\n{text}"
        buf.append(block)
        total += len(block)
    return "".join(buf).strip()

def _assistant_reply(user_text: str, lang: str, context: Optional[str]) -> str:
    """
    Returns a short assistant reply.
    If ENABLE_VERTEX=0 (or vertexai missing), we return a safe fallback.
    """
    # Fallback path (keeps the demo alive if Vertex is off)
    if not USE_VERTEX:
        if not user_text:
            return "I didn’t catch that. Please try again."
        return f"You said: {user_text}. How can I help next?"

    # --- Vertex AI Gemini call ---
    try:
        # Lazy import so local dev without the lib still runs the server
        from vertexai import init as vertex_init
        from vertexai.generative_models import GenerativeModel

        project = os.getenv("GCP_PROJECT")
        location = os.getenv("VERTEX_LOCATION", "europe-west1")
        vertex_init(project=project, location=location)

        # Optional: compact domain context from local chunks (if you have rag.py/_retrieve_context)
        domain_context = None
        try:
            domain_context = _retrieve_context(user_text, max_docs=6, max_chars=6000)  # noqa: F821
        except Exception:
            pass

        system_instruction = (
            (context or "") + "\n\n" + (domain_context or "")
            if (context or domain_context)
            else "You are a concise banking voice assistant. Use the provided context when relevant."
        )

        model = GenerativeModel("gemini-1.5-flash")
        prompt = f"{system_instruction}\n\nUser ({lang}): {user_text}"

        resp = model.generate_content(
            prompt,
            generation_config={"temperature": 0.3, "max_output_tokens": 200},
        )
        text = (resp.text or "").strip()
        if not text:
            text = "I’m here."
        return text

    except ModuleNotFoundError:
        # vertexai not installed in the environment -> fallback
        if not user_text:
            return "I didn’t catch that. Please try again."
        return f"You said: {user_text}. How can I help next?"
    except Exception:
        # Any runtime/permission issue -> graceful fallback
        if not user_text:
            return "I didn’t catch that. Please try again."
        return f"(fallback) You said: {user_text}. How can I help next?"


@app.post("/assist", response_model=AssistOut, tags=["Assistant"])
def assist(body: AssistIn):
    lang = body.lang or "en-GB"
    # 1) STT
    try:
        user_text = _stt_bytes_to_text(base64.b64decode(body.audio), lang)
    except Exception:
        user_text = ""
    # 2) Reply
    reply_text = _assistant_reply(user_text, lang, body.context)
    # 3) TTS
    reply_audio_b64 = _tts_text_to_b64mp3(reply_text, lang)
    return AssistOut(text=reply_text, audio=reply_audio_b64)