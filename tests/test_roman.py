"""Tests for Roman-output mode: romanize_text, directives, steering, session
plumbing, ws_audio behaviour and the API surface. No network."""
import json
import time

import pytest

import ai
import server
import interview_session as isess
from tests.test_interview_session import FakeAI, Collector, make_manager


# ── romanize_text ──────────────────────────────────────────────────────────────
class _Msg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _Client:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []
        outer = self
        self.chat = type("C", (), {"completions": type("CC", (), {
            "create": staticmethod(outer._create)})()})()

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return type("R", (), {"choices": [_Msg(self.reply)]})()


@pytest.fixture
def stub_client(monkeypatch):
    def install(reply=None, exc=None, configured=True):
        c = _Client(reply, exc)
        monkeypatch.setattr(ai, "_get_client", lambda: c)
        monkeypatch.setattr(ai, "is_configured", lambda: configured)
        return c
    return install


def test_romanize_skips_client_for_latin_and_empty(stub_client):
    c = stub_client("x")
    assert ai.romanize_text("already latin text") == ("already latin text", False)
    assert ai.romanize_text("") == ("", False)
    assert ai.romanize_text("   ") == ("   ", False)
    assert c.calls == []


def test_romanize_skips_client_when_unconfigured(stub_client):
    c = stub_client("x", configured=False)
    assert ai.romanize_text("यह क्या है") == ("यह क्या है", False)
    assert c.calls == []


def test_romanize_success(stub_client):
    c = stub_client("yeh kya hai")
    assert ai.romanize_text("यह क्या है", language="hi") == ("yeh kya hai", True)
    assert len(c.calls) == 1
    assert c.calls[0]["temperature"] == 0
    system = c.calls[0]["messages"][0]["content"].lower()
    assert "do not translate" in system
    assert "roman/latin" in system
    assert "hindi" in system   # language name appended


def test_romanize_failures_return_original(stub_client):
    src = "यह क्या है"
    stub_client(exc=RuntimeError("boom"))
    assert ai.romanize_text(src) == (src, False)
    stub_client("")
    assert ai.romanize_text(src) == (src, False)
    stub_client("यह क्या है")          # still non-Latin
    assert ai.romanize_text(src) == (src, False)


def test_romanize_input_capped(stub_client):
    c = stub_client("a" * 10)
    ai.romanize_text("क" * 5000)
    assert len(c.calls[0]["messages"][1]["content"]) == 2000


# ── language_instruction ───────────────────────────────────────────────────────
def test_instruction_non_roman_unchanged():
    assert ai.language_instruction("hing") == ai._ANSWER_LANGUAGE_DIRECTIVES["hing"]
    assert ai.language_instruction("hi") == (
        "- Always respond in Hindi, regardless of the input language. "
        "Match the language of the interviewer's question exactly.")
    assert ai.language_instruction("mr") == (
        "- Always respond in Marathi, regardless of the input language. "
        "Match the language of the interviewer's question exactly.")
    assert ai.language_instruction("en") == (
        "- Always respond in English, regardless of the input language. "
        "Match the language of the interviewer's question exactly.")
    assert ai.language_instruction("hi", False) == ai.language_instruction("hi")


def test_instruction_roman_hindi_family_uses_hinglish():
    h = ai._ANSWER_LANGUAGE_DIRECTIVES["hing"]
    for code in ("hi", "ur", "hing"):
        out = ai.language_instruction(code, True)
        assert out == h
        assert "Roman" in out


def test_instruction_roman_other_languages():
    for code, name in (("mr", "Marathi"), ("ta", "Tamil"), ("ml", "Malayalam")):
        out = ai.language_instruction(code, True)
        assert name in out
        assert "ENTIRELY" in out and "Roman/Latin" in out


def test_instruction_roman_english_unchanged():
    assert ai.language_instruction("en", True) == ai.language_instruction("en")
    assert ai.language_instruction(None, True) == ai.language_instruction(None)


def test_build_prompt_threads_roman():
    p = ai._build_interview_prompt("general", "mr", True)
    assert "ENTIRELY" in p
    assert "ENTIRELY" not in ai._build_interview_prompt("general", "mr")


# ── steering prompts ───────────────────────────────────────────────────────────
def test_steer_prompt_roman_vs_native():
    assert ai._steer_prompt_for("hi", True) == ai._ROMAN_STEER_PROMPTS["hi"]
    assert ai._steer_prompt_for("hi", True).isascii()
    assert ai._steer_prompt_for("hi", False) == ai._SCRIPT_STEER_PROMPTS["hi"]
    assert ai._steer_prompt_for("en", True) is None
    assert ai._steer_prompt_for("mr", True).isascii()
    for code in ("hi", "ur", "hing", "mr", "ta", "te", "bn", "gu", "pa", "kn", "ml"):
        assert code in ai._ROMAN_STEER_PROMPTS


class _STTClient:
    def __init__(self):
        self.kwargs = []
        outer = self
        self.audio = type("A", (), {"transcriptions": type("T", (), {
            "create": staticmethod(outer._create)})()})()

    def _create(self, **kw):
        self.kwargs.append(kw)
        return type("R", (), {"text": "hello", "language": None})()


def test_transcribe_detailed_roman_prompt_and_hint(monkeypatch):
    c = _STTClient()
    monkeypatch.setattr(ai, "_get_client", lambda: c)
    # No single language and no legacy Hindi steering: derived from the set.
    ai.transcribe_detailed(b"x", candidate_languages=["en", "mr", "ur"], roman=True)
    assert c.kwargs[0]["prompt"] == ai._ROMAN_STEER_PROMPTS["ur"]
    assert "language" not in c.kwargs[0]
    ai.transcribe_detailed(b"x", language="ta", roman=True)
    assert c.kwargs[1]["prompt"] == ai._ROMAN_STEER_PROMPTS["ta"]
    assert c.kwargs[1]["language"] == "ta"
    ai.transcribe_detailed(b"x", candidate_languages=["en"], roman=True)
    assert "prompt" not in c.kwargs[2]
    # Non-roman keeps the native-script prompt.
    ai.transcribe_detailed(b"x", language="hi")
    assert c.kwargs[3]["prompt"] == ai._SCRIPT_STEER_PROMPTS["hi"]


# ── session plumbing ───────────────────────────────────────────────────────────
class RomanAI(FakeAI):
    """FakeAI that also accepts and records the `roman` kwarg."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.roman_seen = []

    def answer_interview_question_stream(self, question, category=None, context=None,
                                         candidate_profile=None, model=None,
                                         temperature=None, language=None, roman=False):
        self.roman_seen.append(roman)
        yield from super().answer_interview_question_stream(
            question, category=category, context=context,
            candidate_profile=candidate_profile, model=model,
            temperature=temperature, language=language)


class DetectSpy:
    def __init__(self):
        self.calls = []

    def detect(self, text, language=None):
        self.calls.append((text, language))
        return None


def test_session_roman_passes_kwarg_and_language():
    ai_ = RomanAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai_)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="r1",
                          languages=["en", "hi", "mr"], roman=True)
    assert s.roman is True
    s.add_transcript("Marathi madhe ha prashna kasa sodvaycha?", is_final=True,
                     language="mr")
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()
    assert ai_.roman_seen == [True]
    assert ai_.last_language == "mr"
    mgr.shutdown()


def test_session_roman_urdu_tag_coerced_in_set():
    ai_ = RomanAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai_)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="r2",
                          languages=["en", "hi"], roman=True)
    s.add_transcript("Yeh kya hai aur kaise kaam karta hai?", is_final=True,
                     language="ur")
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()
    # ur is out of the selected set -> coerced to a set member.
    assert ai_.last_language in ("en", "hi")
    assert ai_.roman_seen == [True]
    mgr.shutdown()


def test_session_non_roman_never_passes_kwarg_old_stub_works():
    ai_ = FakeAI(chunks=["ok"])   # no `roman` parameter at all
    mgr, _ = make_manager(ai=ai_)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="r3")
    assert s.roman is False
    s.add_transcript("What is a closure?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()
    mgr.shutdown()


def test_session_roman_non_stream_path_with_old_stub_fails_softly_only_if_roman():
    # roman=True with a stub lacking the kwarg is a programming error, but the
    # default (roman False) path must keep working with the non-streaming API.
    ai_ = FakeAI(answer="done")
    mgr, _ = make_manager(ai=ai_, streaming=False)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="r4")
    s.add_transcript("What is a closure?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()
    mgr.shutdown()


def test_romanized_hindi_turn_keeps_hi_tag_for_detection():
    spy = DetectSpy()
    ai_ = RomanAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai_)
    mgr.detector = spy
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="r5",
                          languages=["en", "hi"], roman=True)
    s.add_transcript("Mujhe batao ki angular vs react me kya difference hai",
                     is_final=True, language="hi")
    deadline = time.time() + 3
    while not spy.calls and time.time() < deadline:
        time.sleep(0.02)
    assert spy.calls and spy.calls[0][1] == "hi"
    mgr.shutdown()


# ── ws_audio behaviour via the wrapped route function ──────────────────────────
class FakeWS:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    def receive(self, timeout=None):
        return self.frames.pop(0) if self.frames else None

    def send(self, data):
        self.sent.append(json.loads(data))

    def close(self, *a, **k):
        pass


class FakeAIHelper:
    AIError = ai.AIError

    def __init__(self, stt_results, romanized=None):
        self.stt_results = list(stt_results)
        self.stt_calls = []
        self.romanized = romanized
        self.romanize_calls = []
        self.detect_calls = []

    def transcribe_detailed(self, audio, filename=None, language=None,
                            candidate_languages=None, **kw):
        self.stt_calls.append({"language": language, "kw": kw})
        return self.stt_results.pop(0)

    def transcribe(self, audio, filename=None):
        return "plain text"

    def detect_language(self, text, selected):
        self.detect_calls.append(text)
        return "hi"

    def romanize_text(self, text, language=None):
        self.romanize_calls.append((text, language))
        return (self.romanized, True) if self.romanized else (text, False)


def _run_ws(monkeypatch, helper, **envelope):
    import base64
    monkeypatch.setattr(server, "ai_helper", helper)
    monkeypatch.setattr(server, "convo", None)
    msg = {"speaker": "them", "filename": "them.webm",
           "audio": "data:audio/webm;base64," + base64.b64encode(b"abc").decode()}
    msg.update(envelope)
    ws = FakeWS([json.dumps(msg)])
    fn = server.app.view_functions["ws_audio"].__wrapped__
    fn(ws)
    return ws.sent, [m for m in ws.sent if m.get("type") == "transcript"]


pytestmark_ws = pytest.mark.skipif(
    "ws_audio" not in server.app.view_functions,
    reason="flask-sock not installed",
)


@pytestmark_ws
def test_ws_roman_reply_shape_and_conversion(monkeypatch):
    h = FakeAIHelper([("यह क्या है", None)], romanized="yeh kya hai")
    _, tr = _run_ws(monkeypatch, h, languages=["en", "hi"], roman=True)
    assert len(tr) == 1
    r = tr[0]
    assert r["text"] == "yeh kya hai"
    assert r["roman"] is True and r["converted"] is True
    assert r["language"] == "hi"                 # tagged from the ORIGINAL text
    assert r["speech_locale"]
    assert h.detect_calls == ["यह क्या है"]
    assert h.stt_calls[0]["kw"] == {"roman": True}


@pytestmark_ws
def test_ws_roman_latin_text_skips_romanize(monkeypatch):
    h = FakeAIHelper([("what is a closure", "en")])
    _, tr = _run_ws(monkeypatch, h, languages=["en", "hi"], roman="true")
    assert tr[0]["text"] == "what is a closure"
    assert tr[0]["roman"] is True and tr[0]["converted"] is False
    assert h.romanize_calls == []


@pytestmark_ws
def test_ws_without_roman_is_old_shape(monkeypatch):
    h = FakeAIHelper([("hello there", "en")])
    _, tr = _run_ws(monkeypatch, h, languages=["en", "hi"])
    assert set(tr[0]) == {"type", "speaker", "text", "language", "speech_locale"}
    assert h.stt_calls[0]["kw"] == {}            # no roman kwarg passed


@pytestmark_ws
def test_ws_audio_tab_shape_unchanged(monkeypatch):
    h = FakeAIHelper([])
    _, tr = _run_ws(monkeypatch, h, roman=True)   # no languages -> roman ignored
    assert tr == [{"type": "transcript", "speaker": "them", "text": "plain text"}]


@pytestmark_ws
def test_ws_roman_drops_implausible_after_one_retry(monkeypatch):
    h = FakeAIHelper([("这个函数是怎么工作的", "zh"), ("这个函数是怎么工作的", "zh")])
    sent, tr = _run_ws(monkeypatch, h, languages=["en", "hi", "mr"], roman=True)
    assert tr == []
    assert len(h.stt_calls) == 2
    assert not [m for m in sent if m.get("type") == "error"]


# ── API surface ────────────────────────────────────────────────────────────────
def test_health_lists_new_languages():
    server.app.testing = True
    with server.app.test_client() as c:
        h = c.get("/api/health").get_json()
    codes = [l["code"] for l in h["supported_languages"]] if "supported_languages" in h \
        else [l["code"] for l in h["languages"]]
    for code in ("kn", "ml", "ur"):
        assert code in codes
    assert codes[0] == "en"


@pytest.mark.skipif(server.interview_manager is None, reason="no interview engine")
def test_rest_start_echoes_roman():
    server.app.testing = True
    with server.app.test_client() as c:
        r1 = c.post("/api/interview/start", json={"roman": True}).get_json()
        r2 = c.post("/api/interview/start", json={}).get_json()
    assert r1["roman"] is True and r2["roman"] is False
    for sid in (r1["session_id"], r2["session_id"]):
        server.interview_manager.stop_session(sid)


def test_truthy():
    for v in (True, "true", "1", 1, "TRUE"):
        assert server._truthy(v)
    for v in (False, None, "false", "0", 0, "", "yes", [], {}):
        assert not server._truthy(v)
