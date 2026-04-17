"""
Local keyword-based intent classifier for Arabic and English relay commands.

Uses simple string contains checks instead of regex — more reliable
for Arabic text which has issues with regex word boundaries.

All Arabic text is normalised (diacritics removed, Alef unified, etc.)
before matching so dialect variations are handled transparently.
"""
from __future__ import annotations

import re

from app.models.schemas import GeminiIntent, Intent, Language
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Arabic normaliser (same logic as whisper_service)
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = re.sub(r"[\u064B-\u065F\u0640]", "", text)   # strip tashkeel
    text = re.sub(r"[أإآٱ]", "ا", text)              # unify alef
    text = text.replace("ة", "ه")                        # taa marbuta
    text = text.replace("ى", "ي")                        # yaa
    return text.strip()


def _n(words: list[str]) -> list[str]:
    """Return a normalized copy of a keyword list."""
    return [_normalize(w) for w in words]

# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

ON_WORDS_AR = _n([
    "ولع", "ولّع", "اشغل", "شغل", "شغّل", "تشغيل",
    "افتح", "فتح", "وصل", "وصّل", "نور", "شغال", "ايد", "قيد",
    # Whisper common mistakes:
    "ولا", "شال", "شعل", "يشتغل"
])
OFF_WORDS_AR = _n([
    "اطفي", "طفي", "اطفأ", "قفل", "اقفل",
    "وقف", "وقّف", "افصل", "الغي",
    # Whisper common mistakes:
    "طاف", "اضفي", "طفا"
])
TOGGLE_WORDS_AR = _n(["بدل", "بدّل", "عكس", "قلب"])

ON_WORDS_EN = ["turn on", "switch on", "enable", "activate", "power on", "start", "target on", "tan on", "terman"]
OFF_WORDS_EN = ["turn off", "turn of", "switch off", "disable", "deactivate", "power off", "stop", "target off", "tan off"]
TOGGLE_WORDS_EN = ["toggle", "flip", "reverse", "to go", "taco"]


ALL_TRIGGERS_AR = _n(["كل", "جميع", "الكل"])
ALL_TRIGGERS_EN = ["all", "everything", "every"]

# ---------------------------------------------------------------------------
# Number keyword → relay index (0-based)
# ---------------------------------------------------------------------------

NUMBER_WORDS: list[tuple[list[str], int]] = [
    # ── Arabic / Egyptian ────────────────────────────────────────────────
    (_n(["واحد", "الاول", "الأول", "الاولى", "الأولى", "الاولاني", "الاولانية", "وحد"]) + ["1", "١"], 0),
    (_n(["اتنين", "اثنين", "التاني", "الثاني", "التانية", "الثانية", "تنين"]) + ["2", "٢"], 1),
    (_n(["تلاتة", "ثلاثة", "التالت", "الثالث", "التالتة", "الثالثة", "تلاجة", "ثلاجة"]) + ["3", "٣"], 2),
    (_n(["اربعة", "أربعة", "اربعه", "الرابع", "الرابعة", "اربع"]) + ["4", "٤"], 3),
    (_n(["خمسة", "خمسه", "الخامس", "الخامسة", "خمس"]) + ["5", "٥"], 4),
    (_n(["ستة", "سته", "السادس", "السادسة", "الساتت", "الساتة", "ست"]) + ["6", "٦"], 5),
    (_n(["سبعة", "سبعه", "السابع", "السابعة", "سبع"]) + ["7", "٧"], 6),
    (_n(["تمانية", "ثمانية", "التامن", "الثامن", "التامنة", "الثامنة", "تمنية"]) + ["8", "٨"], 7),
    # ── English ordinals / cardinals ─────────────────────────────────────
    (["first", "one", "won"], 0),
    (["second", "two", "too"], 1),
    (["third", "three", "tree", "free"], 2),
    (["fourth", "four", "for "], 3),
    (["fifth", "five", "fife"], 4),
    (["sixth", "six", "sex"], 5),
    (["seventh", "seven", "steven"], 6),
    (["eighth", "eight", "ate"], 7),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contains_any(text: str, words: list[str]) -> bool:
    """Return True if any word from *words* appears in *text*."""
    return any(w in text for w in words)


def _find_relay_indices(text: str) -> list[int]:
    """Return a list of all zero-based relay indices found in *text*."""
    found_indices = []
    for keywords, idx in NUMBER_WORDS:
        if _contains_any(text, keywords):
            found_indices.append(idx)
    return found_indices


def _is_arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06FF" for c in text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def local_classify(command: str) -> GeminiIntent | None:
    """
    Classify *command* using keyword matching.

    Returns a :class:`GeminiIntent` with confidence 1.0 on a match,
    or ``None`` if the command is ambiguous.
    """
    # Normalise first so dialect variations don't matter
    text = _normalize(command.strip().lower())
    lang = Language.AR if _is_arabic(command) else Language.EN

    # ------------------------------------------------------------------
    # 1. Bulk intents — check for "all / كل" with an action word
    # ------------------------------------------------------------------
    has_all = _contains_any(text, ALL_TRIGGERS_AR) or _contains_any(text, ALL_TRIGGERS_EN)

    if has_all:
        is_on     = _contains_any(text, ON_WORDS_AR)  or _contains_any(text, ON_WORDS_EN)
        is_off    = _contains_any(text, OFF_WORDS_AR)  or _contains_any(text, OFF_WORDS_EN)
        is_toggle = _contains_any(text, TOGGLE_WORDS_AR) or _contains_any(text, TOGGLE_WORDS_EN)

        if is_on and not is_off:
            logger.debug({"event": "local_hit", "intent": "all_on"})
            return GeminiIntent(intent=Intent.ALL_ON, indices=[], language=lang, confidence=1.0)
        if is_off and not is_on:
            logger.debug({"event": "local_hit", "intent": "all_off"})
            return GeminiIntent(intent=Intent.ALL_OFF, indices=[], language=lang, confidence=1.0)
        if is_toggle:
            logger.debug({"event": "local_hit", "intent": "toggle_all"})
            return GeminiIntent(intent=Intent.TOGGLE_ALL, indices=[], language=lang, confidence=1.0)

    # ------------------------------------------------------------------
    # 2. Single-relay intents — need both action + number
    # ------------------------------------------------------------------
    is_on     = _contains_any(text, ON_WORDS_AR)     or _contains_any(text, ON_WORDS_EN)
    is_off    = _contains_any(text, OFF_WORDS_AR)    or _contains_any(text, OFF_WORDS_EN)
    is_toggle = _contains_any(text, TOGGLE_WORDS_AR) or _contains_any(text, TOGGLE_WORDS_EN)

    # Ambiguous — multiple actions
    if sum([is_on, is_off, is_toggle]) > 1:
        logger.debug({"event": "local_miss", "reason": "multiple_action_words"})
        return None

    if not (is_on or is_off or is_toggle):
        logger.debug({"event": "local_miss", "reason": "no_action_word", "text": text})
        return None

    relay_indices = _find_relay_indices(text)
    if not relay_indices:
        logger.debug({"event": "local_miss", "reason": "no_relay_number", "text": text})
        return None

    intent = (
        Intent.TURN_ON  if is_on  else
        Intent.TURN_OFF if is_off else
        Intent.TOGGLE
    )

    logger.debug({"event": "local_hit", "intent": intent, "indices": relay_indices})
    return GeminiIntent(intent=intent, indices=relay_indices, language=lang, confidence=1.0)
