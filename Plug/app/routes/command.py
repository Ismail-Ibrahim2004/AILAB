"""
POST /command — unified command endpoint.

Handles three mutually exclusive input modes:

  a) **voice**   — UploadFile audio → Whisper → Gemini → Execute
  b) **text**    — plain string     → Gemini → Execute
  c) **manual**  — index + action  → Execute directly (no AI)

The payload is a multipart/form-data body so that audio files can be
uploaded alongside the other fields in a single request.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional, Union

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.config import Settings, get_settings
from app.models.schemas import (
    CommandResponse,
    CommandType,
    Intent,
    Language,
    RelayAction,
)
from app.services import relay_service
from app.services.ai_service import classify_intent
from app.services.relay_service import (
    RelayOperationResult,
    get_relay_states,
    set_all_relays,
    set_relay,
    toggle_all_relays,
    toggle_relay,
)
from app.services.response_service import (
    build_clarification_response,
    build_command_response,
    build_manual_response,
)
from app.services.whisper_service import transcribe_audio
from app.utils.exceptions import (
    InvalidCommandTypeError,
    LowConfidenceError,
    RelayIndexError,
)
from app.utils.logger import get_logger, get_request_id, set_request_id

router = APIRouter(tags=["Command"])
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _execute_intent(
    intent_obj,
    settings: Settings,
) -> RelayOperationResult:
    """
    Dispatch a classified intent to the appropriate relay service call.

    Args:
        intent_obj: A validated :class:`GeminiIntent`.
        settings:   Application settings.

    Returns:
        :class:`RelayOperationResult` from the relay service.
    """
    indices = intent_obj.indices or []
    
    match intent_obj.intent:
        case Intent.TURN_ON:
            affected = []
            already = True
            for idx in indices:
                res = await set_relay(idx, True, settings)
                affected.extend(res.affected_indices)
                if not res.already_in_state: already = False
            return RelayOperationResult(
                index=indices[0] if indices else None,
                previous_state=None, new_state=True,
                already_in_state=already, affected_indices=list(set(affected))
            )
        case Intent.TURN_OFF:
            affected = []
            already = True
            for idx in indices:
                res = await set_relay(idx, False, settings)
                affected.extend(res.affected_indices)
                if not res.already_in_state: already = False
            return RelayOperationResult(
                index=indices[0] if indices else None,
                previous_state=None, new_state=False,
                already_in_state=already, affected_indices=list(set(affected))
            )
        case Intent.TOGGLE:
            affected = []
            for idx in indices:
                res = await toggle_relay(idx, settings)
                affected.extend(res.affected_indices)
            return RelayOperationResult(
                index=indices[0] if indices else None,
                previous_state=None, new_state=None,
                already_in_state=False, affected_indices=list(set(affected))
            )
        case Intent.ALL_ON:
            return await set_all_relays(True, settings)
        case Intent.ALL_OFF:
            return await set_all_relays(False, settings)
        case Intent.TOGGLE_ALL:
            return await toggle_all_relays(settings)
        case Intent.STATUS | Intent.UNKNOWN:
            # Read-only: return a no-op result
            return RelayOperationResult(
                index=None,
                previous_state=None,
                new_state=None,
                already_in_state=False,
                affected_indices=[],
            )
        case _:
            return RelayOperationResult(
                index=None,
                previous_state=None,
                new_state=None,
                already_in_state=False,
                affected_indices=[],
            )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/command",
    response_model=CommandResponse,
    summary="Send a relay command",
    description=(
        "Accepts voice audio (Whisper → Gemini), text (Gemini), "
        "or a direct manual relay action. All three modes use the same endpoint."
    ),
)
async def post_command(
    # ------------------------------------------------------------------
    # Form fields — all optional at declaration level; validated below
    # ------------------------------------------------------------------
    type: Annotated[str, Form(description="Command type: voice | text | manual")] = "text",
    text: Annotated[Optional[str], Form(description="Text command (type=text only)")] = None,
    index: Annotated[Optional[int], Form(description="Relay index 0-7 (type=manual only)")] = None,
    action: Annotated[Optional[str], Form(description="on | off | toggle (type=manual only)")] = None,
    audio: Annotated[Optional[Union[UploadFile, str]], File(description="Audio file (type=voice only)")] = None,
    language: Annotated[str, Form(description="Preferred response language: ar | en")] = "en",
    settings: Settings = Depends(get_settings),
) -> CommandResponse:
    """
    Unified command handler supporting voice, text, and manual modes.

    **voice**:  Upload an audio file. The server transcribes it with
                Whisper then classifies the intent with Gemini.

    **text**:   Send a natural-language string. Gemini classifies the
                intent directly.

    **manual**: Provide ``index`` (0-7) and ``action`` (on/off/toggle)
                to bypass AI and execute the relay change directly.
    """
    # ------------------------------------------------------------------
    # Attach a fresh request_id to this async call chain
    # ------------------------------------------------------------------
    set_request_id(str(uuid.uuid4()))
    rid = get_request_id()

    # Normalise preferred language
    preferred_lang = Language.AR if language.lower() == "ar" else Language.EN

    logger.info(
        {
            "event": "command_received",
            "request_id": rid,
            "type": type,
            "text_preview": (text or "")[:80] if type == "text" else None,
            "has_audio": audio is not None,
            "index": index,
            "action": action,
        }
    )

    # ------------------------------------------------------------------
    # Route by command type
    # ------------------------------------------------------------------

    # ── MANUAL ────────────────────────────────────────────────────────
    if type == CommandType.MANUAL:
        if index is None or action is None:
            raise RelayIndexError(-1)  # Will be caught by global handler

        if not (0 <= index <= 7):
            raise RelayIndexError(index)

        action_lower = action.lower()
        if action_lower not in {"on", "off", "toggle"}:
            raise InvalidCommandTypeError(f"manual action '{action}'")

        match action_lower:
            case "on":
                result = await set_relay(index, True, settings)
            case "off":
                result = await set_relay(index, False, settings)
            case "toggle":
                result = await toggle_relay(index, settings)
            case _:
                result = RelayOperationResult(
                    index=index, previous_state=None, new_state=None,
                    already_in_state=False, affected_indices=[],
                )

        snapshot = await get_relay_states()
        response = build_manual_response(
            index=index,
            action=action_lower,
            result=result,
            relay_snapshot=snapshot,
            lang=preferred_lang,
        )
        logger.info({"event": "command_executed", "request_id": rid, "type": "manual",
                     "response_message": response.message})
        return response

    # ── VOICE ─────────────────────────────────────────────────────────
    if type == CommandType.VOICE:
        if audio is None or isinstance(audio, str):
            raise InvalidCommandTypeError("voice command requires a valid audio file")

        audio_bytes = await audio.read()
        content_type = audio.content_type or "audio/wav"

        transcript = await transcribe_audio(
            audio_bytes=audio_bytes,
            content_type=content_type,
            settings=settings,
        )
        command_text = transcript

    # ── TEXT ──────────────────────────────────────────────────────────
    elif type == CommandType.TEXT:
        if not text:
            raise InvalidCommandTypeError("text command requires a non-empty 'text' field")
        transcript = None
        command_text = text

    else:
        raise InvalidCommandTypeError(type)

    # ------------------------------------------------------------------
    # Gemini intent classification (shared by voice + text paths)
    # ------------------------------------------------------------------
    try:
        intent_obj = await classify_intent(command_text, settings)
    except LowConfidenceError as exc:
        snapshot = await get_relay_states()
        response = build_clarification_response(
            lang=preferred_lang,
            low_confidence=True,
            relay_snapshot=snapshot,
        )
        logger.warning(
            {"event": "low_confidence", "request_id": rid,
             "confidence": exc.confidence, "command": command_text[:80]}
        )
        return response

    # ------------------------------------------------------------------
    # Handle unknown intent gracefully (not an error, just clarification)
    # ------------------------------------------------------------------
    if intent_obj.intent == Intent.UNKNOWN:
        snapshot = await get_relay_states()
        logger.warning(
            {"event": "intent_unknown", "request_id": rid,
             "command": command_text[:80], "confidence": intent_obj.confidence}
        )
        return build_clarification_response(
            lang=preferred_lang,
            low_confidence=False,
            relay_snapshot=snapshot,
        )

    # ------------------------------------------------------------------
    # Execute intent
    # ------------------------------------------------------------------
    result = await _execute_intent(intent_obj, settings)
    snapshot = await get_relay_states()

    response = build_command_response(
        intent=intent_obj,
        result=result,
        relay_snapshot=snapshot,
        transcript=transcript,
    )
    logger.info(
        {
            "event": "command_executed",
            "request_id": rid,
            "type": type,
            "intent": intent_obj.intent,
            "indices": intent_obj.indices,
            "already_in_state": result.already_in_state,
            "response_message": response.message,
        }
    )
    return response
