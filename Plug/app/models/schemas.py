"""
Pydantic v2 request/response schemas for the Voice AI Smart Relay Controller.

All public schemas are exported from this module so that routes and
services only need to import from ``app.models.schemas``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CommandType(str, Enum):
    """The three accepted input modes for POST /command."""

    VOICE = "voice"
    TEXT = "text"
    MANUAL = "manual"


class RelayAction(str, Enum):
    """Discrete actions applicable to a single relay."""

    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"


class Intent(str, Enum):
    """All intents that Gemini can classify."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"
    ALL_ON = "all_on"
    ALL_OFF = "all_off"
    TOGGLE_ALL = "toggle_all"
    STATUS = "status"
    UNKNOWN = "unknown"


class Language(str, Enum):
    """Response language returned by Gemini."""

    AR = "ar"
    EN = "en"


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class TextCommandRequest(BaseModel):
    """Body for a text-based command (type='text')."""

    command_type: CommandType = Field(
        default=CommandType.TEXT,
        alias="type",
        description="Must be 'text'.",
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural-language command string.",
    )

    model_config = {"populate_by_name": True}


class ManualCommandRequest(BaseModel):
    """Body for a manual relay command (type='manual')."""

    command_type: CommandType = Field(
        default=CommandType.MANUAL,
        alias="type",
        description="Must be 'manual'.",
    )
    index: int = Field(
        ...,
        ge=0,
        le=7,
        description="Zero-based relay index (0–7).",
    )
    action: RelayAction = Field(
        ...,
        description="The action to apply: on | off | toggle.",
    )

    model_config = {"populate_by_name": True}

    @field_validator("index")
    @classmethod
    def validate_relay_index(cls, v: int) -> int:
        if not (0 <= v <= 7):
            raise ValueError(f"Relay index must be 0–7, got {v}.")
        return v


# ---------------------------------------------------------------------------
# Gemini AI response schema
# ---------------------------------------------------------------------------


class GeminiIntent(BaseModel):
    """Parsed intent returned by the Gemini classification prompt."""

    intent: Intent
    indices: list[int] | None = Field(
        default=None,
        description="Target relay indices (0-7), or null for bulk/status intents.",
    )
    language: Language | None = Language.EN
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence in the classified intent.",
    )

    @model_validator(mode="after")
    def validate_indices_for_single_relay_intents(self) -> "GeminiIntent":
        """Ensure single-relay intents always carry indices. If missing, degrade to UNKNOWN."""
        
        # Safe fallback for language if Gemini explicitly returns explicit null
        if self.language is None:
            self.language = Language.EN
            
        single_relay_intents = {Intent.TURN_ON, Intent.TURN_OFF, Intent.TOGGLE}
        if self.intent in single_relay_intents and not self.indices:
            # Instead of crashing the API with a ValueError, gracefully degrade to UNKNOWN
            # so the route can ask the user for clarification.
            self.intent = Intent.UNKNOWN
            self.confidence = 0.0
        return self


# ---------------------------------------------------------------------------
# Command response
# ---------------------------------------------------------------------------


class CommandResponse(BaseModel):
    """Unified response envelope for POST /command."""

    success: bool = Field(description="Whether the command was executed.")
    message: str = Field(description="Human-readable result in detected language.")
    intent: Intent | None = Field(
        default=None,
        description="Detected intent (absent for manual commands).",
    )
    relay_indices: list[int] | None = Field(
        default=None,
        description="Affected relay indices, if applicable.",
    )
    already_in_state: bool = Field(
        default=False,
        description="True when the relay was already in the requested state.",
    )
    transcript: str | None = Field(
        default=None,
        description="Whisper transcript (voice commands only).",
    )
    language: Language = Field(
        default=Language.EN,
        description="Language of the response message.",
    )
    request_id: str = Field(description="Unique identifier for this request.")
    relays_snapshot: list[bool] = Field(
        description="Full relay state after command execution.",
    )


# ---------------------------------------------------------------------------
# Status response
# ---------------------------------------------------------------------------


class StatusResponse(BaseModel):
    """Response for GET /status."""

    relays: list[bool] = Field(
        description="Boolean state for each of the 8 relays.",
    )
    active_count: int = Field(
        description="Number of relays currently ON.",
    )
    timestamp: str = Field(
        description="ISO-8601 UTC timestamp of the status snapshot.",
    )

    @classmethod
    def from_relay_states(cls, states: list[bool]) -> "StatusResponse":
        """Build a StatusResponse from the current relay state list."""
        return cls(
            relays=states,
            active_count=sum(states),
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Error response (used by global exception handler)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error envelope returned on any exception."""

    error: str = Field(description="Machine-readable error code.")
    message: str = Field(description="Human-readable error description.")
    request_id: str = Field(description="Unique identifier for the failed request.")
    detail: Any = Field(
        default=None,
        description="Optional extra detail (omitted in production).",
    )
