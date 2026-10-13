"""Tests for the default-language behaviour (English, en-IN) across layers."""
import pytest

import interview_config as ic
import ai
import question_detector as qd
import interview_session as isess
from tests.test_interview_session import FakeAI, Collector, make_manager


# ── Config layer ───────────────────────────────────────────────────────────────

def test_config_defaults_to_english():
    cfg = ic.load_config()
    assert cfg.language == "en"
    assert cfg.defaultSpeechLocale == "en-IN"


@pytest.mark.parametrize("value,expected", [
    (None, "en"),
    ("", "en"),
    ("   ", "en"),
    ("en", "en"),
    ("en-IN", "en"),
    ("en_US", "en"),
    ("EN", "en"),
    ("fr", "en"),        # unsupported -> fall back to English
    ("zh-CN", "en"),     # unsupported -> fall back to English
])
def test_normalize_language(value, expected):
    assert ic.normalize_language(value) == expected


def test_speech_locale_default():
    assert ic.speech_locale_for(None) == "en-IN"
    assert ic.speech_locale_for("en") == "en-IN"
    assert ic.speech_locale_for("fr") == "en-IN"  # fallback language's locale


# ── ai.py prompt directive ───────────────────────────────────────────────────

def test_prompt_pins_english_by_default():
    sys_prompt = ai._build_interview_prompt("general", None)
    assert "respond in English" in sys_prompt


def test_prompt_unknown_language_falls_back_to_english():
    sys_prompt = ai._build_interview_prompt("general", "fr")
    assert "respond in English" in sys_prompt


# ── Session layer ──────────────────────────────────────────────────────────────

def test_session_defaults_to_english_when_unspecified():
    ai_fake = FakeAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai_fake)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="lang-default")
    assert s.language == "en"
    assert s.speech_locale == "en-IN"
    mgr.shutdown()


def test_session_explicit_language_normalized():
    ai_fake = FakeAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai_fake)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="lang-explicit", language="en-US")
    assert s.language == "en"  # normalized to base code
    mgr.shutdown()


def test_session_invalid_language_falls_back_to_english():
    ai_fake = FakeAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai_fake)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="lang-bad", language="xx")
    assert s.language == "en"
    mgr.shutdown()


def test_session_passes_language_to_answer_generation():
    ai_fake = FakeAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai_fake)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="lang-pass")
    s.add_transcript("What is a hash map?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()
    # The fake records the language it was called with -> English by default.
    assert ai_fake.last_language == "en"
    mgr.shutdown()


# ── API layer ──────────────────────────────────────────────────────────────────

def test_api_health_and_start_report_english_default():
    server = pytest.importorskip("server")
    if server.interview_manager is None:
        pytest.skip("interview engine unavailable")
    server.app.testing = True
    with server.app.test_client() as client:
        health = client.get("/api/health").get_json()
        assert health["default_language"] == "en"
        assert health["default_speech_locale"] == "en-IN"
        assert any(l["code"] == "en" for l in health["supported_languages"])

        started = client.post("/api/interview/start", json={}).get_json()
        assert started["language"] == "en"
        assert started["speech_locale"] == "en-IN"
        server.interview_manager.stop_session(started["session_id"])

        # Unsupported language on start -> English fallback.
        bad = client.post("/api/interview/start", json={"language": "fr"}).get_json()
        assert bad["language"] == "en"
        server.interview_manager.stop_session(bad["session_id"])
