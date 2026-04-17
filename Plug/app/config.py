"""
Application configuration via pydantic-settings.

All sensitive values (API keys, tokens) are loaded exclusively from
environment variables or an .env file — never hard-coded.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Voice AI Smart Relay Controller."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    environment: Literal["development", "production", "testing"] = Field(
        default="development",
        description="Runtime environment.",
    )

    # ------------------------------------------------------------------
    # API keys — REQUIRED in production
    # ------------------------------------------------------------------
    hf_token: str = Field(
        default="",
        description="HuggingFace API token for Whisper inference.",
    )

    # ------------------------------------------------------------------
    # Groq settings
    # ------------------------------------------------------------------
    groq_api_key: str = Field(
        default="",
        description="Groq API key for intent classification (free, fast).",
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model to use for intent classification.",
    )

    # ------------------------------------------------------------------
    # Whisper settings
    # ------------------------------------------------------------------
    whisper_model_url: str = Field(
        default=(
            "https://router.huggingface.co/hf-inference/models/"
            "openai/whisper-large-v3"
        ),
        description="Full URL of the HuggingFace Whisper inference endpoint.",
    )
    whisper_timeout_seconds: float = Field(
        default=30.0,
        description="HTTP timeout (seconds) for Whisper API calls.",
    )

    # ------------------------------------------------------------------
    # Audio validation
    # ------------------------------------------------------------------
    audio_max_size_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        description="Maximum accepted audio file size in bytes.",
    )

    # ------------------------------------------------------------------
    # Intent classifier settings
    # ------------------------------------------------------------------
    intent_confidence_threshold: float = Field(
        default=0.6,
        description="Minimum confidence score to act on an intent (local classifier).",
    )

    # ------------------------------------------------------------------
    # Relay / GPIO
    # ------------------------------------------------------------------
    relay_count: int = Field(default=8, description="Number of physical relays.")
    gpio_pins_bcm: list[int] = Field(
        default=[17, 18, 27, 22, 23, 24, 25, 4],
        description="BCM GPIO pin numbers mapped to relay indices 0-7.",
    )
    gpio_active_low: bool = Field(
        default=True,
        description="When True, a LOW signal activates the relay (active-low board).",
    )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    rate_limit_per_minute: int = Field(
        default=30,
        description="Maximum requests per IP per minute.",
    )

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    host: str = Field(default="0.0.0.0", description="Uvicorn bind host.")
    port: int = Field(default=8000, description="Uvicorn bind port.")
    log_level: str = Field(default="info", description="Uvicorn log level.")

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("gpio_pins_bcm")
    @classmethod
    def validate_pin_count(cls, pins: list[int]) -> list[int]:
        """Ensure exactly 8 GPIO pins are configured."""
        if len(pins) != 8:
            raise ValueError(
                f"gpio_pins_bcm must contain exactly 8 pin numbers; got {len(pins)}."
            )
        return pins

    @field_validator("intent_confidence_threshold")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("intent_confidence_threshold must be between 0 and 1.")
        return v

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        """True when running in the production environment."""
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached application settings singleton.

    Using ``lru_cache`` ensures the .env file is parsed only once,
    making the settings object safe to use as a FastAPI dependency.
    """
    return Settings()
