"""Text-to-speech for the race engineer's voice (chunk 10).

Server-side synthesis: one call per radio message regardless of connected
browsers, credentials never leave the service, and audio arrives atomically
with its text. Chirp 3 HD voice, en-GB male, 1.15x rate per the locked
decision — both overridable via env (TTS_VOICE, TTS_RATE) since swapping
voices is a one-string change.

Failure policy: a lost voice is not a lost call — synthesis errors log and
return None, and the radio message goes out text-only.
"""
from __future__ import annotations

import base64
import logging
import os

from google.cloud import texttospeech

logger = logging.getLogger("tts")

VOICE_NAME = os.environ.get("TTS_VOICE", "en-GB-Chirp3-HD-Charon")
SPEAKING_RATE = float(os.environ.get("TTS_RATE", "1.15"))
LANGUAGE_CODE = "-".join(VOICE_NAME.split("-")[:2])  # "en-GB" from the name

_client: texttospeech.TextToSpeechAsyncClient | None = None


def _get_client() -> texttospeech.TextToSpeechAsyncClient:
    global _client
    if _client is None:
        _client = texttospeech.TextToSpeechAsyncClient()
    return _client


async def synthesize(text: str) -> str | None:
    """Text -> base64 MP3, or None on any failure (call goes out text-only)."""
    if not text:
        return None
    try:
        response = await _get_client().synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(
                language_code=LANGUAGE_CODE, name=VOICE_NAME,
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=SPEAKING_RATE,
            ),
        )
        return base64.b64encode(response.audio_content).decode()
    except Exception as e:
        logger.warning("synthesis failed (text-only fallback): %s",
                       str(e).splitlines()[0][:160])
        return None
