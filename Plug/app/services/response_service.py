"""
Response message builder for the Voice AI Smart Relay Controller.

Generates localised confirmation / error messages in Arabic or English
based on the executed intent and its result, then assembles the full
:class:`CommandResponse` envelope.
"""
from __future__ import annotations

from app.models.schemas import CommandResponse, GeminiIntent, Intent, Language
from app.services.relay_service import RelayOperationResult
from app.utils.logger import get_logger, get_request_id

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

_MESSAGES: dict[Language, dict[str, str]] = {
    Language.AR: {
        # Single relay
        "turn_on_ok":      "تم تشغيل الخانة {n}",
        "turn_on_already": "الخانة {n} شغالة بالفعل",
        "turn_off_ok":     "تم إيقاف الخانة {n}",
        "turn_off_already":"الخانة {n} متوقفة بالفعل",
        "toggle_ok":       "تم تبديل حالة الخانة {n}",
        # Bulk
        "all_on_ok":       "تم تشغيل جميع الخانات",
        "all_on_already":  "جميع الخانات مشغولة بالفعل",
        "all_off_ok":      "تم إيقاف جميع الخانات",
        "all_off_already": "جميع الخانات متوقفة بالفعل",
        "toggle_all_ok":   "تم تبديل حالة جميع الخانات",
        # Status
        "status":          "النظام يعمل — {active} خانة مشغولة من أصل {total}",
        # Unknown / clarification
        "unknown":         "مش فاهم الأمر، ممكن تعيد؟",
        "low_confidence":  "مش فاهم الأمر بشكل واضح، ممكن تعيد؟",
        # Manual
        "manual_on_ok":    "تم تشغيل الخانة {n} يدوياً",
        "manual_on_already": "الخانة {n} شغالة بالفعل",
        "manual_off_ok":   "تم إيقاف الخانة {n} يدوياً",
        "manual_off_already": "الخانة {n} متوقفة بالفعل",
        "manual_toggle_ok":"تم تبديل حالة الخانة {n} يدوياً",
    },
    Language.EN: {
        # Single relay
        "turn_on_ok":      "Relay {n} turned ON",
        "turn_on_already": "Relay {n} is already ON",
        "turn_off_ok":     "Relay {n} turned OFF",
        "turn_off_already":"Relay {n} is already OFF",
        "toggle_ok":       "Relay {n} toggled",
        # Bulk
        "all_on_ok":       "All relays turned ON",
        "all_on_already":  "All relays are already ON",
        "all_off_ok":      "All relays turned OFF",
        "all_off_already": "All relays are already OFF",
        "toggle_all_ok":   "All relays toggled",
        # Status
        "status":          "System running — {active} of {total} relays active",
        # Unknown / clarification
        "unknown":         "Command not understood. Please try again.",
        "low_confidence":  "Command not understood clearly. Please try again.",
        # Manual
        "manual_on_ok":    "Relay {n} manually turned ON",
        "manual_on_already": "Relay {n} is already ON",
        "manual_off_ok":   "Relay {n} manually turned OFF",
        "manual_off_already": "Relay {n} is already OFF",
        "manual_toggle_ok":"Relay {n} manually toggled",
    },
}


def _t(key: str, lang: Language = Language.EN, **kwargs: object) -> str:
    """Return a localised template string with substitutions applied."""
    template = _MESSAGES.get(lang, _MESSAGES[Language.EN]).get(key, key)
    return template.format(**kwargs)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def build_command_response(
    *,
    intent: GeminiIntent,
    result: RelayOperationResult,
    relay_snapshot: list[bool],
    transcript: str | None = None,
) -> CommandResponse:
    """
    Build a :class:`CommandResponse` for a voice or text command.

    Args:
        intent:          The classified :class:`GeminiIntent`.
        result:          The outcome from the relay service.
        relay_snapshot:  Full relay state after execution.
        transcript:      Whisper transcript (or None for text commands).

    Returns:
        A populated :class:`CommandResponse`.
    """
    lang = intent.language
    indices = intent.indices or []
    if indices:
        n = " و ".join(str(i + 1) for i in indices) if lang == Language.AR else " and ".join(str(i + 1) for i in indices)
    else:
        n = "0"

    match intent.intent:
        case Intent.TURN_ON:
            key = "turn_on_already" if result.already_in_state else "turn_on_ok"
            message = _t(key, lang, n=n)
        case Intent.TURN_OFF:
            key = "turn_off_already" if result.already_in_state else "turn_off_ok"
            message = _t(key, lang, n=n)
        case Intent.TOGGLE:
            message = _t("toggle_ok", lang, n=n)
        case Intent.ALL_ON:
            key = "all_on_already" if result.already_in_state else "all_on_ok"
            message = _t(key, lang)
        case Intent.ALL_OFF:
            key = "all_off_already" if result.already_in_state else "all_off_ok"
            message = _t(key, lang)
        case Intent.TOGGLE_ALL:
            message = _t("toggle_all_ok", lang)
        case Intent.STATUS:
            active = sum(relay_snapshot)
            message = _t("status", lang, active=active, total=len(relay_snapshot))
        case _:
            message = _t("unknown", lang)

    return CommandResponse(
        success=True,
        message=message,
        intent=intent.intent,
        relay_indices=intent.indices,
        already_in_state=result.already_in_state,
        transcript=transcript,
        language=lang,
        request_id=get_request_id(),
        relays_snapshot=relay_snapshot,
    )


def build_manual_response(
    *,
    index: int,
    action: str,
    result: RelayOperationResult,
    relay_snapshot: list[bool],
    lang: Language = Language.EN,
) -> CommandResponse:
    """
    Build a :class:`CommandResponse` for a manual relay command.

    Args:
        index:          Zero-based relay index.
        action:         One of ``on`` / ``off`` / ``toggle``.
        result:         The outcome from the relay service.
        relay_snapshot: Full relay state after execution.
        lang:           Response language (defaults to English).

    Returns:
        A populated :class:`CommandResponse`.
    """
    n = index + 1  # 1-based display number

    match action.lower():
        case "on":
            key = "manual_on_already" if result.already_in_state else "manual_on_ok"
            resolved_intent = Intent.TURN_ON
        case "off":
            key = "manual_off_already" if result.already_in_state else "manual_off_ok"
            resolved_intent = Intent.TURN_OFF
        case "toggle":
            key = "manual_toggle_ok"
            resolved_intent = Intent.TOGGLE
        case _:
            key = "unknown"
            resolved_intent = Intent.UNKNOWN

    message = _t(key, lang, n=n)

    return CommandResponse(
        success=True,
        message=message,
        intent=resolved_intent,
        relay_indices=[index],
        already_in_state=result.already_in_state,
        transcript=None,
        language=lang,
        request_id=get_request_id(),
        relays_snapshot=relay_snapshot,
    )


def build_clarification_response(
    *,
    lang: Language = Language.EN,
    low_confidence: bool = False,
    relay_snapshot: list[bool],
) -> CommandResponse:
    """
    Build an "I didn't understand" clarification response.

    Args:
        lang:            Response language.
        low_confidence:  Use the low-confidence variant if True.
        relay_snapshot:  Full relay state (unchanged).

    Returns:
        A :class:`CommandResponse` with ``success=False``.
    """
    key = "low_confidence" if low_confidence else "unknown"
    message = _t(key, lang)

    return CommandResponse(
        success=False,
        message=message,
        intent=Intent.UNKNOWN,
        relay_indices=None,
        already_in_state=False,
        transcript=None,
        language=lang,
        request_id=get_request_id(),
        relays_snapshot=relay_snapshot,
    )
