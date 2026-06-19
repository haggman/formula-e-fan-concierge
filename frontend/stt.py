"""Speech-to-text for pit-wall push-to-talk (chunk 11).

Cloud Speech V2 with the Chirp 2 model — deliberately the same model family
as the engineer's voice, so the demo loop is Chirp in, Gemini in the middle,
Chirp out. Chirp 2 is regional; we use the us-central1 endpoint to match
the project region. MediaRecorder's webm/opus decodes via auto-detection,
so the browser sends its native format untouched.
"""
from __future__ import annotations

import logging
import os

import google.auth
from google.api_core.client_options import ClientOptions
from google.cloud import speech_v2

logger = logging.getLogger("stt")

STT_REGION = os.environ.get("STT_REGION", "us-central1")
STT_MODEL = os.environ.get("STT_MODEL", "chirp_2")
STT_LANGUAGE = os.environ.get("STT_LANGUAGE", "en-US")

_client: speech_v2.SpeechAsyncClient | None = None
_recognizer: str | None = None


def _setup() -> tuple[speech_v2.SpeechAsyncClient, str]:
    global _client, _recognizer
    if _client is None:
        _, project = google.auth.default()
        _client = speech_v2.SpeechAsyncClient(
            client_options=ClientOptions(
                api_endpoint=f"{STT_REGION}-speech.googleapis.com",
            )
        )
        _recognizer = f"projects/{project}/locations/{STT_REGION}/recognizers/_"
    return _client, _recognizer


async def transcribe(audio_bytes: bytes) -> str:
    """Audio (any MediaRecorder container) -> transcript. Empty string if
    nothing was recognized; raises on API failure (caller reports it)."""
    if not audio_bytes:
        return ""
    client, recognizer = _setup()
    response = await client.recognize(
        recognizer=recognizer,
        config=speech_v2.RecognitionConfig(
            auto_decoding_config=speech_v2.AutoDetectDecodingConfig(),
            model=STT_MODEL,
            language_codes=[STT_LANGUAGE],
        ),
        content=audio_bytes,
    )
    parts = [
        result.alternatives[0].transcript
        for result in response.results
        if result.alternatives
    ]
    transcript = " ".join(p.strip() for p in parts).strip()
    logger.info("transcribed %d bytes -> %r", len(audio_bytes), transcript[:120])
    return transcript
