"""Tests for the expanded language registry + set-normalization helpers."""
import interview_config as ic


# ── normalize_language_set ─────────────────────────────────────────────────────

def test_set_dedupes_and_normalizes():
    assert ic.normalize_language_set(["en", "hi", "hi", "mr-IN"]) == ["en", "hi", "mr"]


def test_set_drops_unknowns():
    assert ic.normalize_language_set(["hi", "xx", "zz", "fr"]) == ["hi", "fr"]


def test_set_empty_or_all_unknown_falls_back():
    assert ic.normalize_language_set([]) == ["en"]
    assert ic.normalize_language_set(["xx", "zz"]) == ["en"]
    assert ic.normalize_language_set(None) == ["en"]


def test_set_custom_fallback():
    assert ic.normalize_language_set([], fallback="hi") == ["hi"]
    # An unknown fallback itself normalizes back to English.
    assert ic.normalize_language_set([], fallback="xx") == ["en"]


def test_set_preserves_order():
    assert ic.normalize_language_set(["zh", "en", "ja"]) == ["zh", "en", "ja"]


# ── normalize_language_in_set ──────────────────────────────────────────────────

def test_in_set_keeps_member():
    assert ic.normalize_language_in_set("hi", ["hi", "en"]) == "hi"


def test_in_set_coerces_outsider_to_fallback():
    assert ic.normalize_language_in_set("en", ["hi", "mr"], fallback="hi") == "hi"


def test_in_set_coerces_outsider_to_first_when_no_fallback():
    assert ic.normalize_language_in_set("en", ["mr", "hi"]) == "mr"


def test_in_set_normalizes_locale_form():
    assert ic.normalize_language_in_set("hi-IN", ["hi", "en"]) == "hi"


def test_in_set_empty_allowed_defaults_english():
    assert ic.normalize_language_in_set("hi", []) == "en"


# ── Registry completeness ──────────────────────────────────────────────────────

EXPECTED_CODES = {
    "en", "hi", "hing", "mr", "zh", "es", "fr", "de", "ja", "ko", "ar",
    "pt", "ru", "it", "nl", "tr", "ta", "te", "bn", "gu", "pa",
}


def test_registry_has_full_set():
    assert set(ic.SUPPORTED_LANGUAGES.keys()) == EXPECTED_CODES


def test_every_entry_has_name_native_locale():
    for code, meta in ic.SUPPORTED_LANGUAGES.items():
        assert meta.get("name"), code
        assert meta.get("native"), code
        assert meta.get("default_locale"), code
        # speech_locale_for resolves to that entry's locale.
        assert ic.speech_locale_for(code) == meta["default_locale"]


# ── Hinglish pseudo-code ───────────────────────────────────────────────────────

def test_hinglish_is_registered_and_normalizes():
    # Hinglish is a selectable pseudo-code (Hindi-English code-mix, Roman script).
    assert "hing" in ic.SUPPORTED_LANGUAGES
    assert ic.normalize_language("hing") == "hing"
    # It survives set normalization alongside real codes.
    assert ic.normalize_language_set(["hing", "en"]) == ["hing", "en"]
    # STT biasing uses the Hindi locale (the Hindi words are Hindi).
    assert ic.speech_locale_for("hing") == "hi-IN"


def test_hinglish_answer_directive_is_roman_codemix():
    import ai
    directive = ai.language_instruction("hing")
    low = directive.lower()
    assert "hinglish" in low
    assert "roman" in low            # must specify Roman/Latin script
    assert "devanagari" in low       # must say NOT Devanagari
    # And it does NOT collapse to the generic "respond in Hinglish" wording.
    assert "regardless of the input language" not in low


def test_hinglish_detect_language_allows_four_letter_code():
    # The set-constrained classifier must be able to return the 4-letter code.
    import ai
    # No OpenAI key in tests -> detect_language coerces to the set default,
    # which must preserve 'hing' when it is the first allowed code.
    assert ai.detect_language("yeh scalable hai kya", ["hing", "en"]) == "hing"
