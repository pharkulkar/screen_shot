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
    "en", "hi", "mr", "zh", "es", "fr", "de", "ja", "ko", "ar",
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
