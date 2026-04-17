"""
Intent classification service — Local-first, Groq fallback.

Strategy
--------
1.  Local keyword classifier (zero API calls, instant).
2.  If ambiguous → Groq Llama 3.3 70B (free, < 500ms).

Groq is OpenAI-API-compatible and dramatically faster than Gemini
with a generous free tier (14,400 req/day, 30 req/min).
"""
from __future__ import annotations

import json
import re

from groq import AsyncGroq

from app.config import Settings, get_settings
from app.models.schemas import GeminiIntent, Intent, Language
from app.services.local_classifier import local_classify
from app.utils.exceptions import GeminiAPIError, LowConfidenceError
from app.utils.logger import get_logger, get_request_id

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Groq system prompt (same logic as the old Gemini prompt)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an intent classifier for a smart relay controller.
The controller has 8 relays indexed 0 to 7.

Arabic ON  words : ولع، فتح، اشغل، تشغيل، وصّل، شغّل، نور، شغال، افتح، ايد، قيد
Arabic OFF words : طفي، قفل، وقف، اطفي، وقّف، افصل، اطفأ، اقفل، الغي
Arabic TOGGLE    : بدّل، بدل، عكس، قلب
Arabic ALL ON    : شغّل كل، ولّع كل، افتح كل
Arabic ALL OFF   : اطفي كل، وقّف كل، قفل كل
Arabic TOGGLE ALL: بدّل كل، عكس كل

Arabic/Egyptian numbers (relay index = number - 1):
- 1: واحد، الأول، الأولى، الاولاني، الاولانية → index 0
- 2: اتنين، اثنين، الثاني، التاني → index 1
- 3: تلاتة، ثلاثة، الثالث، التالت → index 2
- 4: اربعة، الرابع، الرابعة → index 3
- 5: خمسة، الخامس → index 4
- 6: ستة، السادس، الساتت، الساتة → index 5
- 7: سبعة، السابع → index 6
- 8: تمانية، ثمانية، الثامن، التامن → index 7

English: turn on/off, toggle, all on/off, relay 1-8, first/second...eighth

Return ONLY compact JSON, no markdown:
{"intent":"turn_on|turn_off|toggle|all_on|all_off|toggle_all|status|unknown","indices":[0-7] or [],"language":"ar|en","confidence":0.0-1.0}

RULES:
1. The user's command is transcribed from an Audio Speech Recognition (ASR) system. It WILL contain phonetic errors, dialect words, or completely misspelled words in both Arabic and English (e.g., hearing "ولا" instead of "ولع", "تلاجة" instead of "تلاتة", "tree" instead of "three", or "turn of" instead of "turn off"). Use your understanding of phonetic similarity to deduce the intended command.
2. NEVER return unknown if there is ANY clue about the intent based on the sound of the words.
3. confidence should be 1.0 almost always.
4. Single-relay intents (turn_on/off/toggle) MUST have at least one index in the indices array. If the user mentions multiple relays (e.g., "turn on 5 and 6"), extract all of them: {"indices": [4, 5]}.

EXAMPLES OF BAD AUDIO TRANSCRIPTIONS TO CORRECT JSON:
Input: "ولا التلاجة و الرابعه"
Output: {"intent":"turn_on","indices":[2, 3],"language":"ar","confidence":1.0}

Input: "شال الاولاني"
Output: {"intent":"turn_on","indices":[0],"language":"ar","confidence":1.0}

Input: "في التامنه" (sounds like طفي)
Output: {"intent":"turn_off","indices":[7],"language":"ar","confidence":0.9}

Input: "اضفي الساتت"
Output: {"intent":"turn_off","indices":[5],"language":"ar","confidence":1.0}

Input: "taco too and tree" (sounds like toggle two and three)
Output: {"intent":"toggle","indices":[1, 2],"language":"en","confidence":1.0}
"""


# ---------------------------------------------------------------------------
# Groq intent call
# ---------------------------------------------------------------------------

async def _classify_via_groq(
    command: str,
    settings: Settings,
) -> GeminiIntent:
    """Call Groq Llama to classify an ambiguous command."""
    rid = get_request_id()
    client = AsyncGroq(api_key=settings.groq_api_key)

    logger.info({
        "event": "groq_request",
        "request_id": rid,
        "command_preview": command[:100],
    })

    try:
        chat = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f'Command: "{command}"'},
            ],
            temperature=0.1,
            max_tokens=128,
        )
    except Exception as exc:  # noqa: BLE001
        raise GeminiAPIError(f"Groq API call failed: {exc}") from exc

    raw: str = chat.choices[0].message.content or ""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)

    try:
        data: dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiAPIError(f"Groq returned non-JSON: {raw[:200]}") from exc

    # Sanitise language — Groq sometimes returns unexpected codes (e.g. "he")
    raw_lang = str(data.get("language", "ar")).lower()
    data["language"] = "ar" if raw_lang not in ("ar", "en") else raw_lang

    try:
        intent_obj = GeminiIntent(**data)
    except Exception as exc:  # noqa: BLE001
        raise GeminiAPIError(f"Groq response schema error: {exc}") from exc

    logger.info({
        "event": "groq_classified",
        "request_id": rid,
        "intent": intent_obj.intent,
        "indices": intent_obj.indices,
        "confidence": intent_obj.confidence,
    })
    return intent_obj


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def classify_intent(
    command: str,
    settings: Settings | None = None,
) -> GeminiIntent:
    """
    Classify a relay command — local-first, Groq fallback.

    Args:
        command:  Input string (Whisper transcript or raw text).
        settings: Optional settings override.

    Returns:
        A validated :class:`GeminiIntent`.

    Raises:
        GeminiAPIError:     If Groq fails.
        LowConfidenceError: If confidence < threshold.
    """
    settings = settings or get_settings()
    rid = get_request_id()

    # ── Fast path: local keyword classifier ───────────────────────────
    # [DISABLED BY USER REQUEST - ALL COMMANDS GO TO GROQ]
    # result = local_classify(command)
    # if result is not None:
    #     logger.info({
    #         "event": "local_classify_hit",
    #         "request_id": rid,
    #         "intent": result.intent,
    #         "index": result.indices[0] if result.indices else None,
    #     })
    #     return result

    # ── Slow path: Groq (only for ambiguous commands) ─────────────────
    logger.info({"event": "groq_fallback", "request_id": rid, "command": command[:80]})
    intent_obj = await _classify_via_groq(command, settings)

    if intent_obj.confidence < settings.intent_confidence_threshold:
        raise LowConfidenceError(intent_obj.confidence)

    return intent_obj
