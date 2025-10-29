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
def _assistant_reply(user_text: str, lang: str, context: Optional[str]) -> str:
    # Simple rule-based reply for demo; swap with Vertex later if wanted.
    if not user_text:
        return "I didn’t catch that. Please try again."
    if "time" in user_text.lower():
        return "I’m running in the cloud. Ask me to speak, transcribe, or explain something."
    return f"You said: {user_text}. How can I help next?"

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