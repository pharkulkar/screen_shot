"""Tests for script_guard: script detection, plausibility, retry-once-then-drop."""
import pytest

import script_guard as sg


# ── script_of ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("What is dependency injection?", sg.LATIN),
    ("यह फ़ंक्शन कैसे काम करता है", sg.DEVANAGARI),
    ("हा प्रश्न कसा सोडवायचा", sg.DEVANAGARI),          # Marathi
    ("এটা কিভাবে কাজ করে", sg.BENGALI),
    ("ਇਹ ਕਿਵੇਂ ਕੰਮ ਕਰਦਾ ਹੈ", sg.GURMUKHI),
    ("આ કેવી રીતે કામ કરે છે", sg.GUJARATI),
    ("இது எப்படி வேலை செய்கிறது", sg.TAMIL),
    ("ఇది ఎలా పనిచేస్తుంది", sg.TELUGU),
    ("ಇದು ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ", sg.KANNADA),
    ("ഇത് എങ്ങനെ പ്രവർത്തിക്കുന്നു", sg.MALAYALAM),
    ("یہ کیسے کام کرتا ہے", sg.ARABIC),                  # Urdu
    ("这个函数是怎么工作的", sg.HAN),
    ("これはどう動きますか", sg.KANA),
    ("이것은 어떻게 작동합니까", sg.HANGUL),
    ("Как это работает", sg.CYRILLIC),
])
def test_script_of_scripts(text, expected):
    assert sg.script_of(text) == expected


def test_script_of_mixed_hinglish_with_devanagari_words():
    # Mostly Latin with a couple of Devanagari words -> Latin dominates.
    assert sg.script_of("angular vs react me kya difference hai यह बताओ") == sg.LATIN
    # Mostly Devanagari with a few English tech words.
    assert sg.script_of("मुझे बताओ कि यह function कैसे काम करता है") == sg.DEVANAGARI


def test_script_of_empty_and_symbols():
    assert sg.script_of("") == sg.UNKNOWN
    assert sg.script_of(None) == sg.UNKNOWN
    assert sg.script_of("  123 ?!... ") == sg.UNKNOWN


def test_script_of_tie_is_deterministic():
    # 2 Latin vs 2 Devanagari letters: fixed order picks Latin every time.
    assert sg.script_of("ab कख") == sg.LATIN


def test_has_non_latin():
    assert not sg.has_non_latin("hello world 123")
    assert not sg.has_non_latin("café naïve")
    assert not sg.has_non_latin("")
    assert sg.has_non_latin("hello दुनिया")
    assert sg.has_non_latin("你好")


# ── allowed_scripts / is_plausible ─────────────────────────────────────────────
def test_allowed_scripts_basic():
    assert sg.allowed_scripts(["en"], True) == {sg.LATIN}
    assert sg.DEVANAGARI in sg.allowed_scripts(["hi"], False)
    assert sg.DEVANAGARI in sg.allowed_scripts(["mr"], True)
    assert sg.TAMIL in sg.allowed_scripts(["ta"], True)


def test_arabic_allowed_only_with_hindi_family_in_roman_mode():
    assert sg.ARABIC in sg.allowed_scripts(["en", "hi"], True)
    assert sg.ARABIC in sg.allowed_scripts(["en", "hing"], True)
    assert sg.ARABIC in sg.allowed_scripts(["en", "ur"], True)
    assert sg.ARABIC not in sg.allowed_scripts(["en", "hi"], False)
    assert sg.ARABIC not in sg.allowed_scripts(["en", "mr"], True)


def test_latin_always_allowed_in_roman_mode():
    for sel in (["hi"], ["ta"], ["zh"], ["ur"]):
        assert sg.LATIN in sg.allowed_scripts(sel, True)


def test_chinese_rejected_for_en_hi_mr_both_modes():
    for roman in (True, False):
        assert not sg.is_plausible("这个函数是怎么工作的", ["en", "hi", "mr"], roman)


def test_devanagari_accepted_for_hi_and_mr():
    assert sg.is_plausible("यह फ़ंक्शन कैसे काम करता है", ["hi"], True)
    assert sg.is_plausible("हा प्रश्न कसा सोडवायचा", ["en", "mr"], False)


def test_urdu_script_plausible_with_hindi_selected_in_roman_mode():
    assert sg.is_plausible("یہ کیسے کام کرتا ہے", ["en", "hi"], True)
    assert not sg.is_plausible("یہ کیسے کام کرتا ہے", ["en", "hi"], False)


def test_tamil_rejected_for_en_hi():
    assert not sg.is_plausible("இது எப்படி வேலை செய்கிறது", ["en", "hi"], True)


def test_mixed_hinglish_passes_and_empty_is_plausible():
    assert sg.is_plausible("mujhe batao यह kya hai", ["en", "hi"], True)
    assert sg.is_plausible("", ["en"], True)
    assert sg.is_plausible("123 ?!", ["en"], True)


def test_pure_latin_always_plausible():
    assert sg.is_plausible("What is a closure?", ["hi", "mr"], True)


# ── romanize_hint_language ─────────────────────────────────────────────────────
def test_hint_single_non_english():
    assert sg.romanize_hint_language(["en", "mr"]) == "mr"


def test_hint_first_when_multiple_non_english():
    assert sg.romanize_hint_language(["en", "hi", "mr"]) == "en"
    assert sg.romanize_hint_language(["hi", "mr"]) == "hi"


def test_hint_pseudo_code_gives_none():
    assert sg.romanize_hint_language(["en", "hing"]) is None
    assert sg.romanize_hint_language([]) is None


# ── transcribe_with_guard ──────────────────────────────────────────────────────
class Stub:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, hint, roman):
        self.calls.append((hint, roman))
        return self.results.pop(0)


def test_guard_plausible_first_is_one_call():
    t = Stub(("kya hai", "hi"))
    assert sg.transcribe_with_guard(t, ["en", "hi"], True, None) == ("kya hai", "hi")
    assert t.calls == [(None, True)]


def test_guard_implausible_then_plausible_two_calls_with_firm_hint():
    t = Stub(("这个函数", "zh"), ("yeh kya hai", "hi"))
    out = sg.transcribe_with_guard(t, ["en", "mr"], True, None)
    assert out == ("yeh kya hai", "hi")
    assert t.calls == [(None, True), ("mr", True)]


def test_guard_implausible_twice_drops_after_exactly_two_calls():
    t = Stub(("这个函数", "zh"), ("这个函数", "zh"))
    assert sg.transcribe_with_guard(t, ["en", "hi", "mr"], True, None) is None
    assert len(t.calls) == 2


def test_guard_retry_empty_text_drops():
    t = Stub(("这个函数", "zh"), ("", None))
    assert sg.transcribe_with_guard(t, ["en", "hi", "mr"], True, None) is None


def test_guard_roman_false_never_retries():
    t = Stub(("这个函数", "zh"))
    assert sg.transcribe_with_guard(t, ["en", "hi"], False, None) == ("这个函数", "zh")
    assert len(t.calls) == 1


def test_guard_empty_text_no_retry():
    t = Stub(("", None))
    assert sg.transcribe_with_guard(t, ["en", "hi"], True, None) == ("", None)
    assert len(t.calls) == 1


def test_guard_hing_retry_passes_no_hard_hint():
    t = Stub(("这个", "zh"), ("yeh kya hai", None))
    sg.transcribe_with_guard(t, ["en", "hing"], True, None)
    assert t.calls[1] == (None, True)


def test_guard_retry_exception_propagates():
    def boom(hint, roman):
        if hint is None:
            return ("这个函数", "zh")
        raise RuntimeError("stt down")
    with pytest.raises(RuntimeError):
        sg.transcribe_with_guard(boom, ["en", "mr"], True, None)


# ── derive_language_tag ────────────────────────────────────────────────────────
def test_tag_uses_detected_when_in_set():
    assert sg.derive_language_tag("x", "hi", ["en", "hi"], lambda t, s: "en") == "hi"


def test_tag_single_language_set():
    assert sg.derive_language_tag("x", None, ["mr"], lambda t, s: "en") == "mr"
    assert sg.derive_language_tag("x", "ur", ["mr"], lambda t, s: "en") == "ur"


def test_tag_falls_back_to_detect_fn_on_original_text():
    seen = []

    def detect(text, sel):
        seen.append((text, list(sel)))
        return "hi"
    original = "यह क्या है"
    assert sg.derive_language_tag(original, None, ["en", "hi"], detect) == "hi"
    assert seen == [(original, ["en", "hi"])]   # the pre-romanization text


def test_tag_out_of_set_detected_still_wins_over_detect_fn():
    assert sg.derive_language_tag("x", "ur", ["en", "hi"], lambda t, s: "en") == "ur"
