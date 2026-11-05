"""Unit tests for ai.detect_language and ai.language_instruction (no network).

detect_language is exercised via a dedicated monkeypatched chat stub so it never
collides with the shared FakeAI.ask canned reply used elsewhere.
"""
import types

import ai


class _FakeResp:
    def __init__(self, content):
        self.choices = [types.SimpleNamespace(
            message=types.SimpleNamespace(content=content))]


class _FakeClient:
    def __init__(self, content):
        self._content = content

        class _Chat:
            class _Completions:
                @staticmethod
                def create(**kwargs):
                    return _FakeResp(content)
            completions = _Completions()
        self.chat = _Chat()


def _patch_client(monkeypatch, content):
    monkeypatch.setattr(ai, "is_configured", lambda: True)
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient(content))


def test_detect_language_returns_in_set_code(monkeypatch):
    _patch_client(monkeypatch, "hi")
    assert ai.detect_language("क्लोज़र क्या है।", ["hi", "en"]) == "hi"


def test_detect_language_coerces_off_set_reply_to_default(monkeypatch):
    # Model replies with an out-of-set code -> coerced to candidate_languages[0].
    _patch_client(monkeypatch, "fr")
    assert ai.detect_language("bonjour", ["hi", "en"]) == "hi"


def test_detect_language_handles_noisy_reply(monkeypatch):
    _patch_client(monkeypatch, "The language is: en.")
    assert ai.detect_language("hello there", ["en", "hi"]) == "en"


def test_detect_language_never_raises_on_error(monkeypatch):
    def _boom():
        raise RuntimeError("down")
    monkeypatch.setattr(ai, "is_configured", lambda: True)
    monkeypatch.setattr(ai, "_get_client", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert ai.detect_language("whatever", ["hi", "en"]) == "hi"


def test_detect_language_empty_text_is_default(monkeypatch):
    _patch_client(monkeypatch, "en")
    assert ai.detect_language("   ", ["mr", "en"]) == "mr"


def test_detect_language_not_configured_is_default(monkeypatch):
    monkeypatch.setattr(ai, "is_configured", lambda: False)
    assert ai.detect_language("hello", ["en", "hi"]) == "en"


def test_language_instruction_pins_supported_language():
    instr = ai.language_instruction("hi")
    assert "Hindi" in instr
    assert "Match the language" in instr


def test_language_instruction_unknown_falls_back_english():
    assert "English" in ai.language_instruction("xx")


def test_private_alias_still_works():
    assert ai._language_instruction("fr") == ai.language_instruction("fr")
