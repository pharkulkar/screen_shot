#!/usr/bin/env python3
"""
script_guard.py — pure helpers for the "Roman output" (English letters) mode
============================================================================
Unicode-script detection, a plausibility guard for speech-to-text output, and
the retry-once-then-drop decision logic. Stdlib only (no openai / flask) so it
is cheap to import and fully unit-testable with no network.

Cost / latency note: the guard itself is free. The only extra OpenAI work it
can trigger is ONE additional transcription retry per utterance, and only when
the first transcript is in an implausible script (see `transcribe_with_guard`).
"""
from __future__ import annotations

# ── Script names ───────────────────────────────────────────────────────────────
LATIN = "latin"
DEVANAGARI = "devanagari"
BENGALI = "bengali"
GURMUKHI = "gurmukhi"
GUJARATI = "gujarati"
TAMIL = "tamil"
TELUGU = "telugu"
KANNADA = "kannada"
MALAYALAM = "malayalam"
ARABIC = "arabic"
HAN = "han"
KANA = "kana"
HANGUL = "hangul"
CYRILLIC = "cyrillic"
GREEK = "greek"
HEBREW = "hebrew"
THAI = "thai"
OTHER = "other"
UNKNOWN = "unknown"

# Fixed order used to break count ties deterministically.
_SCRIPT_ORDER = (LATIN, DEVANAGARI, BENGALI, GURMUKHI, GUJARATI, TAMIL, TELUGU,
                 KANNADA, MALAYALAM, ARABIC, HAN, KANA, HANGUL, CYRILLIC,
                 GREEK, HEBREW, THAI, OTHER)

# (lo, hi, script) inclusive ranges.
_RANGES = (
    (0x0041, 0x005A, LATIN), (0x0061, 0x007A, LATIN),
    (0x00C0, 0x00FF, LATIN),            # Latin-1 letters (x/÷ filtered by isalpha)
    (0x0100, 0x024F, LATIN),            # Latin Extended-A/B
    (0x1E00, 0x1EFF, LATIN),            # Latin Extended Additional
    (0x0900, 0x097F, DEVANAGARI),
    (0x0980, 0x09FF, BENGALI),
    (0x0A00, 0x0A7F, GURMUKHI),
    (0x0A80, 0x0AFF, GUJARATI),
    (0x0B80, 0x0BFF, TAMIL),
    (0x0C00, 0x0C7F, TELUGU),
    (0x0C80, 0x0CFF, KANNADA),
    (0x0D00, 0x0D7F, MALAYALAM),
    (0x0600, 0x06FF, ARABIC), (0x0750, 0x077F, ARABIC),
    (0xFB50, 0xFDFF, ARABIC), (0xFE70, 0xFEFF, ARABIC),
    (0x4E00, 0x9FFF, HAN), (0x3400, 0x4DBF, HAN),
    (0x3040, 0x30FF, KANA),
    (0xAC00, 0xD7AF, HANGUL), (0x1100, 0x11FF, HANGUL),
    (0x0400, 0x04FF, CYRILLIC),
    (0x0370, 0x03FF, GREEK),
    (0x0590, 0x05FF, HEBREW),
    (0x0E00, 0x0E7F, THAI),
)


def _script_for_char(ch: str) -> str | None:
    """Script of a single character, or None if it is not a letter."""
    if not ch.isalpha():
        return None
    cp = ord(ch)
    for lo, hi, name in _RANGES:
        if lo <= cp <= hi:
            return name
    return OTHER


def script_counts(text: str) -> dict:
    """Count letters per script (digits, punctuation, whitespace ignored)."""
    counts: dict = {}
    for ch in text or "":
        s = _script_for_char(ch)
        if s is not None:
            counts[s] = counts.get(s, 0) + 1
    return counts


def script_of(text: str) -> str:
    """Dominant script among the letters of `text`; UNKNOWN if there are none.
    Ties resolve by higher count, then the fixed `_SCRIPT_ORDER`."""
    counts = script_counts(text)
    if not counts:
        return UNKNOWN
    return min(counts, key=lambda s: (-counts[s], _SCRIPT_ORDER.index(s)))


def has_non_latin(text: str) -> bool:
    """True if any letter in `text` is not Latin."""
    return any(s != LATIN for s in script_counts(text))


# ── Language -> scripts it may legitimately produce ────────────────────────────
_SCRIPTS_BY_LANG = {
    "en": {LATIN},
    "hi": {DEVANAGARI, LATIN}, "mr": {DEVANAGARI, LATIN},
    "hing": {LATIN},
    "ur": {ARABIC}, "ar": {ARABIC},
    "bn": {BENGALI}, "pa": {GURMUKHI}, "gu": {GUJARATI},
    "ta": {TAMIL}, "te": {TELUGU}, "kn": {KANNADA}, "ml": {MALAYALAM},
    "zh": {HAN}, "ja": {HAN, KANA}, "ko": {HANGUL}, "ru": {CYRILLIC},
    "es": {LATIN}, "fr": {LATIN}, "de": {LATIN}, "pt": {LATIN},
    "it": {LATIN}, "nl": {LATIN}, "tr": {LATIN},
}

# Hindi / Urdu / Hinglish are one spoken language family; STT confuses them.
HINDI_FAMILY = frozenset({"hi", "ur", "hing"})

# A script must hold at least this share of the letters to count as "present".
_PRESENT_RATIO = 0.10


def allowed_scripts(selected, roman: bool) -> set:
    """Union of scripts the selected languages may produce. Latin stays allowed
    (English / loanwords are normal in every transcript). In Roman mode Arabic
    is also allowed when a Hindi-family language is selected (it will be
    romanized rather than rejected)."""
    allowed: set = set()
    for code in selected or []:
        allowed |= _SCRIPTS_BY_LANG.get(code, {LATIN})
    allowed.add(LATIN)
    if roman and any(c in HINDI_FAMILY for c in (selected or [])):
        allowed.add(ARABIC)
    return allowed


def is_plausible(text: str, selected, roman: bool) -> bool:
    """True if every script holding >= ~10% of the letters is allowed for the
    selected languages. Empty / symbol-only text is trivially plausible."""
    counts = script_counts(text)
    total = sum(counts.values())
    if total == 0:
        return True
    allowed = allowed_scripts(selected, roman)
    for script, n in counts.items():
        if n / total >= _PRESENT_RATIO and script not in allowed:
            return False
    return True


def romanize_hint_language(selected) -> str | None:
    """Firm STT hint for the single retry: the one non-English language of the
    set if there is exactly one, else the first selected language. Pseudo-codes
    (e.g. 'hing') yield None — the Roman steering prompt does the work then."""
    codes = [c for c in (selected or []) if c]
    if not codes:
        return None
    non_en = [c for c in codes if c != "en"]
    pick = non_en[0] if len(non_en) == 1 else codes[0]
    if pick == "hing" or pick not in _SCRIPTS_BY_LANG:
        return None
    return pick


def transcribe_with_guard(transcribe, selected, roman: bool, hint):
    """
    Run `transcribe(language_hint, roman) -> (text, detected)` with the
    plausibility guard.

    - roman False: never guarded, single call, result returned unchanged.
    - Empty text: returned as-is, no retry.
    - Plausible text: returned.
    - Implausible: exactly ONE retry with `romanize_hint_language(selected)`
      (bounds cost to at most one extra STT call per utterance). Still
      implausible -> returns None (caller drops the utterance).
    Exceptions from the retry propagate; the caller handles them fail-soft.
    """
    text, detected = transcribe(hint, roman)
    if not roman or not (text or "").strip():
        return text, detected
    if is_plausible(text, selected, roman):
        return text, detected
    text2, detected2 = transcribe(romanize_hint_language(selected), roman)
    if (text2 or "").strip() and is_plausible(text2, selected, roman):
        return text2, detected2
    return None


def derive_language_tag(text, detected, selected, detect_fn) -> str:
    """Language tag for a transcript: STT-reported language if in the selected
    set; a single-language set decides itself; otherwise `detect_fn(text,
    selected)`. Pass the ORIGINAL (pre-romanization) text."""
    selected = list(selected or [])
    if detected and detected in selected:
        return detected
    if len(selected) == 1:
        return detected or selected[0]
    return detected or detect_fn(text, selected)
