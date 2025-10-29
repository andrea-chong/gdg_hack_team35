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
    allow_credentials=False,
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
