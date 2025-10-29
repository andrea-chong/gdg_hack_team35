from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, base64

from google.cloud import texttospeech
from google.cloud import speech

# --- FastAPI app + CORS ---
app = FastAPI(title="ING Voice")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten if you later host a specific frontend
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---
class TTSIn(BaseModel):
    text: str
    lang: str  # "nl-BE" | "fr-BE" | "en-GB"

class TTSOut(BaseModel):
    audio: str  # base64 mp3

class STTIn(BaseModel):
    audio: str  # base64 (mp3 or wav OK)
    lang: Optional[str] = None  # default auto to en-GB if not provided

class STTOut(BaseModel):
    text: str

# --- Health ---
@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "project": os.getenv("GCP_PROJECT", ""),
        "location": os.getenv("VERTEX_LOCATION", ""),
    }

# --- TTS ---
@app.post("/tts", response_model=TTSOut)
def tts(body: TTSIn):
    # Map your 3 language codes to Google voices
    # (Choose neural voices available in europe-west1)
    voice_map = {
        "en-GB": ("en-GB", "en-GB-Neural2-C"),
        "nl-BE": ("nl-BE", "nl-BE-Standard-A"),  # BE choices are limited; Standard ok
        "fr-BE": ("fr-BE", "fr-BE-Standard-A"),
    }
    if body.lang not in voice_map:
        raise HTTPException(status_code=400, detail=f"Unsupported lang '{body.lang}'")

    language_code, voice_name = voice_map[body.lang]

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=body.text)

    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    resp = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    audio_b64 = base64.b64encode(resp.audio_content).decode("utf-8")
    return TTSOut(audio=audio_b64)

# --- STT ---
@app.post("/stt", response_model=STTOut)
def stt(body: STTIn):
    """
    Accepts base64 audio (mp3 or wav). If you know you're sending mp3 from browser,
    this config uses MP3 44.1kHz mono by default, but we'll try "auto" with v2-like hints.
    For robustness, we let the API do automatic decoding when encoding unspecified is allowed.
    """
    audio_bytes = base64.b64decode(body.audio)

    # Try to infer encoding by header; very light heuristic
    # MP3 often starts with 0xFF 0xFB or "ID3"
    encoding = speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED
    sample_rate_hz = 0  # let API detect when unspecified
    # (OPTIONAL) You can force MP3 if your client always sends MP3:
    # encoding = speech.RecognitionConfig.AudioEncoding.MP3
    # sample_rate_hz = 44100

    language_code = body.lang or "en-GB"

    client = speech.SpeechClient()

    config = speech.RecognitionConfig(
        encoding=encoding,
        sample_rate_hertz=sample_rate_hz if sample_rate_hz else None,
        language_code=language_code,
        enable_automatic_punctuation=True,
        model="latest_long",  # or "latest_short" for short queries
    )
    audio = speech.RecognitionAudio(content=audio_bytes)

    try:
        response = client.recognize(config=config, audio=audio)
    except Exception as e:
        # If unspecified encoding failed, retry forcing MP3 44.1k
        try:
            cfg_mp3 = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.MP3,
                sample_rate_hertz=44100,
                language_code=language_code,
                enable_automatic_punctuation=True,
                model="latest_short",
            )
            response = client.recognize(config=cfg_mp3, audio=audio)
        except Exception as e2:
            raise HTTPException(status_code=400, detail=f"STT error: {e2}")

    text = ""
    for result in response.results:
        if result.alternatives:
            text += (result.alternatives[0].transcript + " ")

    return STTOut(text=text.strip())
