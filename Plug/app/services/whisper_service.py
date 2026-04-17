"""
HuggingFace Whisper transcription service.

Sends raw audio bytes to the ``openai/whisper-large-v3`` inference
endpoint via the HuggingFace Router API and returns the transcribed text.

The returned transcript is normalised (diacritics stripped, Alef unified)
so the local classifier matches reliably regardless of accent/spelling.
"""
from __future__ import annotations

import asyncio
import re

from groq import AsyncGroq

from app.config import Settings, get_settings
from app.utils.exceptions import (
    AudioTooLargeError,
    InvalidAudioMimeError,
    WhisperAPIError,
)
from app.utils.logger import get_logger, get_request_id

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Arabic text normaliser
# ---------------------------------------------------------------------------

def _normalize_arabic(text: str) -> str:
    """
    Normalise an Arabic transcript so keyword matching is accent-agnostic.

    Steps
    -----
    1. Strip Arabic diacritics (tashkeel / harakat).
    2. Unify all Alef variants → bare Alef (ا).
    3. Normalise Taa Marbuta (ة) → Haa (ه) — common in dialects.
    4. Normalise Yaa variants (ى → ي).
    5. Collapse repeated spaces.
    """
    # Remove tashkeel (U+064B – U+065F) and tatweel (U+0640)
    text = re.sub(r"[\u064B-\u065F\u0640]", "", text)
    # Unify Alef forms: أ إ آ ٱ → ا
    text = re.sub(r"[أإآٱ]", "ا", text)
    # Taa marbuta → haa
    text = text.replace("ة", "ه")
    # Yaa variants → ي
    text = text.replace("ى", "ي")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def transcribe_audio(
    audio_bytes: bytes,
    content_type: str,
    settings: Settings | None = None,
) -> str:
    """
    Transcribe audio using HuggingFace Whisper large-v3.

    Args:
        audio_bytes:  Raw bytes of the uploaded audio file.
        content_type: MIME type reported by the HTTP client (e.g. ``audio/wav``).
        settings:     Optional settings override; defaults to ``get_settings()``.

    Returns:
        The stripped transcription string.

    Raises:
        AudioTooLargeError:    When ``len(audio_bytes)`` exceeds the limit.
        InvalidAudioMimeError: When ``content_type`` is not ``audio/*``.
        WhisperAPIError:       For any network, timeout, or API-level error.
    """
    settings = settings or get_settings()
    rid = get_request_id()

    # ------------------------------------------------------------------
    # Pre-flight validation
    # ------------------------------------------------------------------
    if len(audio_bytes) > settings.audio_max_size_bytes:
        raise AudioTooLargeError(len(audio_bytes), settings.audio_max_size_bytes)

    if not content_type.startswith("audio/"):
        raise InvalidAudioMimeError(content_type)

    logger.info(
        {
            "event": "whisper_request",
            "request_id": rid,
            "audio_size_bytes": len(audio_bytes),
            "content_type": content_type,
        }
    )

    # ------------------------------------------------------------------
    # Groq Whisper API Call
    # ------------------------------------------------------------------
    try:
        client = AsyncGroq(api_key=settings.groq_api_key)
        # Groq expects a tuple (filename, file_bytes) for the file parameter
        file_tuple = ("audio.wav", audio_bytes)
        
        response = await client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-large-v3",
        )
    except Exception as exc:
        logger.error(
            {"event": "groq_whisper_error", "request_id": rid, "error": str(exc)}
        )
        raise WhisperAPIError(
            f"Groq Whisper transcription failed: {exc}"
        ) from exc

    transcript: str = getattr(response, "text", "").strip()

    if not transcript:
        logger.warning(
            {"event": "whisper_empty_transcript", "request_id": rid}
        )
        raise WhisperAPIError(
            "Whisper returned an empty transcript. "
            "The audio may be silent or corrupted."
        )

    # Normalise Arabic text so the local classifier matches reliably
    normalised = _normalize_arabic(transcript)

    logger.info(
        {
            "event": "whisper_success",
            "request_id": rid,
            "transcript_raw": transcript[:80],
            "transcript_normalised": normalised[:80],
        }
    )
    return normalised
