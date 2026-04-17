"""
Custom exception hierarchy for the Voice AI Smart Relay Controller.

Every exception carries an HTTP status code, a machine-readable error
code string, and a human-readable message so that the global exception
handler can build a uniform JSON error envelope.
"""
from __future__ import annotations


class RelayControllerError(Exception):
    """Base class for all application-level errors."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# ---------------------------------------------------------------------------
# 4xx — client errors
# ---------------------------------------------------------------------------


class RelayIndexError(RelayControllerError):
    """Raised when the requested relay index is outside 0-7."""

    status_code = 422
    error_code = "invalid_relay_index"

    def __init__(self, index: int) -> None:
        super().__init__(
            f"Relay index {index} is out of range. Valid indices are 0–7.",
        )
        self.index = index


class AudioTooLargeError(RelayControllerError):
    """Raised when an uploaded audio file exceeds the 10 MB limit."""

    status_code = 413
    error_code = "audio_too_large"

    def __init__(self, size_bytes: int, limit_bytes: int = 10 * 1024 * 1024) -> None:
        super().__init__(
            f"Audio file size ({size_bytes:,} bytes) exceeds the "
            f"{limit_bytes // (1024 * 1024)} MB limit."
        )
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


class InvalidAudioMimeError(RelayControllerError):
    """Raised when the uploaded file is not an audio/* MIME type."""

    status_code = 415
    error_code = "invalid_audio_mime"

    def __init__(self, content_type: str) -> None:
        super().__init__(
            f"Unsupported media type '{content_type}'. "
            "Only audio/* MIME types are accepted."
        )
        self.content_type = content_type


class InvalidCommandTypeError(RelayControllerError):
    """Raised when the command type is not one of voice/text/manual."""

    status_code = 422
    error_code = "invalid_command_type"

    def __init__(self, command_type: str) -> None:
        super().__init__(
            f"Unknown command type '{command_type}'. "
            "Accepted values: voice, text, manual."
        )


# ---------------------------------------------------------------------------
# 5xx — upstream / infrastructure errors
# ---------------------------------------------------------------------------


class WhisperAPIError(RelayControllerError):
    """Raised when the HuggingFace Whisper transcription fails."""

    status_code = 503
    error_code = "whisper_api_error"

    def __init__(self, message: str = "Whisper transcription service unavailable.") -> None:
        super().__init__(message)


class GeminiAPIError(RelayControllerError):
    """Raised when the Google Gemini intent classification fails."""

    status_code = 503
    error_code = "gemini_api_error"

    def __init__(self, message: str = "Gemini AI service unavailable.") -> None:
        super().__init__(message)


class GPIOError(RelayControllerError):
    """Raised for hardware GPIO faults (falls back to simulation mode)."""

    status_code = 500
    error_code = "gpio_error"

    def __init__(self, message: str = "GPIO hardware error.") -> None:
        super().__init__(message)


class LowConfidenceError(RelayControllerError):
    """Raised when Gemini returns confidence below the acceptable threshold."""

    status_code = 422
    error_code = "low_confidence"

    def __init__(self, confidence: float) -> None:
        super().__init__(
            f"Intent confidence {confidence:.2f} is below the minimum threshold of 0.6."
        )
        self.confidence = confidence
