# app/backend/main.py
import os, base64
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# Google Cloud client libs
from google.cloud import texttospeech
from google.cloud import speech

app = FastAPI(title="ING Voice API", version="1.0.0")

# CORS so the demo page can call the API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten later if you host a specific frontend
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------
class TTSIn(BaseModel):
    text: str
    lang: str  # "nl-BE" | "fr-BE" | "en-GB"

class TTSOut(BaseModel):
    audio: str  # base64 mp3

class STTIn(BaseModel):
    audio: str            # base64 (mp3/wav)
    lang: Optional[str] = None  # default = "en-GB" if not provided

class STTOut(BaseModel):
    text: str

# ---------- Health ----------
@app.get("/healthz", tags=["Health"])
def healthz():
    return {
        "status": "ok",
        "project": os.getenv("GCP_PROJECT", ""),
        "location": os.getenv("VERTEX_LOCATION", ""),
    }

# ---------- TTS ----------
@app.post("/tts", response_model=TTSOut, tags=["Voice"])
def tts(body: TTSIn):
    # Map requested language → Google voice name
    voice_map = {
        "en-GB": ("en-GB", "en-GB-Neural2-C"),
        "nl-BE": ("nl-BE", "nl-BE-Standard-A"),   # BE neural availability varies; Standard is safe
        "fr-BE": ("fr-BE", "fr-BE-Standard-A"),
    }
    if body.lang not in voice_map:
        raise HTTPException(status_code=400, detail=f"Unsupported lang '{body.lang}'")

    language_code, voice_name = voice_map[body.lang]

    tts_client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=body.text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
    )
    audio_cfg = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    resp = tts_client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_cfg
    )
    audio_b64 = base64.b64encode(resp.audio_content).decode("utf-8")
    return TTSOut(audio=audio_b64)

# ---------- STT ----------
@app.post("/stt", response_model=STTOut, tags=["Voice"])
def stt(body: STTIn):
    audio_bytes = base64.b64decode(body.audio)
    language_code = body.lang or "en-GB"

    stt_client = speech.SpeechClient()

    # First try letting the API detect encoding
    cfg = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,
        language_code=language_code,
        enable_automatic_punctuation=True,
        model="latest_short",
    )
    audio = speech.RecognitionAudio(content=audio_bytes)

    try:
        resp = stt_client.recognize(config=cfg, audio=audio)
    except Exception:
        # Fallback: assume MP3 44.1k mono
        cfg2 = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MP3,
            sample_rate_hertz=44100,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="latest_short",
        )
        resp = stt_client.recognize(config=cfg2, audio=audio)

    text = " ".join(
        r.alternatives[0].transcript for r in resp.results if r.alternatives
    ).strip()
    return STTOut(text=text)

# --- One-shot ASSIST: audio -> STT -> LLM -> TTS ---
from pydantic import BaseModel
from typing import Optional
import base64, os

# Optional: Vertex AI (Gemini) reply
USE_VERTEX = os.getenv("ENABLE_VERTEX", "0") == "1"
if USE_VERTEX:
    from google.cloud import aiplatform

class AssistIn(BaseModel):
    audio: str              # base64 wav/mp3 from mic
    lang: Optional[str] = "en-GB"
    context: Optional[str] = None  # optional system prompt

class AssistOut(BaseModel):
    text: str               # assistant transcript
    audio: str              # base64 MP3 answer

def _stt_bytes_to_text(audio_bytes: bytes, lang: str) -> str:
    from google.cloud import speech
    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(content=audio_bytes)
    cfg = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,
        language_code=lang,
        enable_automatic_punctuation=True,
        model="latest_short",
    )
    try:
        resp = client.recognize(config=cfg, audio=audio)
    except Exception:
        # fallback: assume MP3 44.1k
        cfg2 = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MP3,
            sample_rate_hertz=44100,
            language_code=lang,
            enable_automatic_punctuation=True,
            model="latest_short",
        )
        resp = client.recognize(config=cfg2, audio=audio)
    text = " ".join([r.alternatives[0].transcript for r in resp.results if r.alternatives]).strip()
    return text

def _tts_text_to_b64mp3(text: str, lang: str) -> str:
    from google.cloud import texttospeech
    voice_map = {
        "en-GB": ("en-GB", "en-GB-Neural2-C"),
        "nl-BE": ("nl-BE", "nl-BE-Standard-A"),
        "fr-BE": ("fr-BE", "fr-BE-Standard-A"),
    }
    language_code, voice_name = voice_map.get(lang, ("en-GB","en-GB-Neural2-C"))
    tts_client = texttospeech.TextToSpeechClient()
    resp = tts_client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
    )
    return base64.b64encode(resp.audio_content).decode("utf-8")

def _reply_llm(user_text: str, lang: str, context: Optional[str]) -> str:
    # Safe default: rule-based fallback if Vertex not enabled
    if not USE_VERTEX:
        if not user_text:
            return "I didn’t catch that. Could you repeat?"
        # Tiny helper behavior so it feels alive:
        if "time" in user_text.lower():
            return "I’m running in the cloud. I can help with banking assistant flows, speech tests, or general questions."
        return f"You said: {user_text}. How can I help next?"
    # Gemini via Vertex AI (simple text model)
    aiplatform.init(project=os.getenv("GCP_PROJECT"), location=os.getenv("VERTEX_LOCATION", "europe-west1"))
    model = aiplatform.TextGenerationModel.from_pretrained("text-bison@002")
    sys_prompt = context or "You are a concise banking voice assistant. Answer briefly and helpfully."
    prompt = f"{sys_prompt}\n\nUser ({lang}): {user_text}"
    resp = model.predict(prompt, temperature=0.3, max_output_tokens=200)
    return (resp.text or "").strip() or "I’m here."

@app.post("/assist", response_model=AssistOut, tags=["Assistant"])
def assist(body: AssistIn):
    # 1) STT
    audio_bytes = base64.b64decode(body.audio)
    user_text = _stt_bytes_to_text(audio_bytes, body.lang or "en-GB")
    # 2) LLM reply
    answer = _reply_llm(user_text, body.lang or "en-GB", body.context)
    # 3) TTS back
    answer_b64 = _tts_text_to_b64mp3(answer, body.lang or "en-GB")
    return AssistOut(text=answer, audio=answer_b64)

# ---- ASSIST: audio(base64) -> STT -> reply -> TTS ----
from pydantic import BaseModel
from typing import Optional
import base64

class AssistIn(BaseModel):
    audio: str              # base64 from MediaRecorder (webm/opus)
    lang: Optional[str] = "en-GB"

class AssistOut(BaseModel):
    text: str               # assistant's text reply
    audio: str              # base64 MP3 of the reply

def _stt_bytes_to_text(audio_bytes: bytes, lang: str) -> str:
    from google.cloud import speech
    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(content=audio_bytes)
    cfg = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,
        language_code=lang,
        enable_automatic_punctuation=True,
        model="latest_short",
    )
    try:
        resp = client.recognize(config=cfg, audio=audio)
    except Exception:
        # fallback assume MP3 44.1k
        cfg2 = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MP3,
            sample_rate_hertz=44100,
            language_code=lang,
            enable_automatic_punctuation=True,
            model="latest_short",
        )
        resp = client.recognize(config=cfg2, audio=audio)
    return " ".join([r.alternatives[0].transcript for r in resp.results if r.alternatives]).strip()

def _tts_text_to_b64mp3(text: str, lang: str) -> str:
    from google.cloud import texttospeech
    voice_map = {
        "en-GB": ("en-GB", "en-GB-Neural2-C"),
        "nl-BE": ("nl-BE", "nl-BE-Standard-A"),
        "fr-BE": ("fr-BE", "fr-BE-Standard-A"),
    }
    language_code, voice_name = voice_map.get(lang, ("en-GB","en-GB-Neural2-C"))
    tts_client = texttospeech.TextToSpeechClient()
    resp = tts_client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
    )
    return base64.b64encode(resp.audio_content).decode("utf-8")

@app.post("/assist", response_model=AssistOut, tags=["Assistant"])
def assist(body: AssistIn):
    # 1) STT
    user_text = _stt_bytes_to_text(base64.b64decode(body.audio), body.lang or "en-GB")
    # 2) “Assistant” reply (simple, but works for demo)
    reply_text = f"You said: {user_text}. How can I help next?"
    if not user_text:
        reply_text = "I didn’t catch that. Please try again."
    # 3) TTS back
    reply_audio_b64 = _tts_text_to_b64mp3(reply_text, body.lang or "en-GB")
    return AssistOut(text=reply_text, audio=reply_audio_b64)
