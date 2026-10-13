"""Integration tests for InterviewSession / SessionManager orchestration.

These avoid the network entirely via a FakeAI module and keep the end-of-
utterance window tiny so finalization happens quickly. The EOU loop uses a real
background thread + time.sleep, so helpers poll for emitted events with a bound.
"""
import threading
import time

import pytest

from interview_config import InterviewConfig
import question_detector as qd
import interview_session as isess


# ── Fakes ──────────────────────────────────────────────────────────────────────

class FakeAI:
    """Stand-in for ai.py. Configurable to stream, fail, or stall."""

    def __init__(self, answer="Final answer.", configured=True,
                 fail_times=0, chunks=None, delay=0.0):
        self.answer = answer
        self._configured = configured
        self.fail_times = fail_times
        self.chunks = chunks
        self.delay = delay
        self.calls = 0
        self.last_language = None
        self.lock = threading.Lock()

    def is_configured(self):
        return self._configured

    # Detector classifier path (unused when useLlmClassifier=False).
    def ask(self, text, system_prompt=None, model=None):
        return '{"is_question": true, "confidence": 0.9, "category": "general", "complete": true}'

    def answer_interview_question(self, question, category=None, context=None,
                                  candidate_profile=None, model=None, temperature=None,
                                  language=None):
        with self.lock:
            self.calls += 1
            self.last_language = language
            fail = self.fail_times > 0
            if fail:
                self.fail_times -= 1
        if fail:
            raise RuntimeError("generation boom")
        if self.delay:
            time.sleep(self.delay)
        return self.answer

    def answer_interview_question_stream(self, question, category=None, context=None,
                                         candidate_profile=None, model=None, temperature=None,
                                         language=None):
        with self.lock:
            self.calls += 1
            self.last_language = language
            fail = self.fail_times > 0
            if fail:
                self.fail_times -= 1
        if fail:
            raise RuntimeError("generation boom")
        chunks = self.chunks if self.chunks is not None else [self.answer]
        for c in chunks:
            if self.delay:
                time.sleep(self.delay)
            yield c


class Collector:
    """Thread-safe event sink with a wait-for helper."""

    def __init__(self):
        self.events = []
        self._cv = threading.Condition()

    def push(self, event):
        with self._cv:
            self.events.append(event)
            self._cv.notify_all()

    def types(self):
        with self._cv:
            return [e["type"] for e in self.events]

    def of(self, event_type):
        with self._cv:
            return [e for e in self.events if e["type"] == event_type]

    def wait_for(self, event_type, timeout=3.0, count=1):
        """Wait until at least `count` events of `event_type` have arrived."""
        end = time.time() + timeout
        with self._cv:
            while time.time() < end:
                if sum(1 for e in self.events if e["type"] == event_type) >= count:
                    return True
                self._cv.wait(end - time.time())
        return False


def make_manager(ai=None, **cfg_over):
    base = dict(useLlmClassifier=False, endOfUtteranceMs=80,
                duplicateWindowS=60, streaming=True, answerTimeoutS=5)
    base.update(cfg_over)
    cfg = InterviewConfig(**base)
    detector = qd.QuestionDetector(cfg, ai_module=ai)
    mgr = isess.SessionManager(cfg, detector, ai_module=ai, db_module=None)
    return mgr, cfg


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_direct_question_full_flow():
    ai = FakeAI(chunks=["Dependency ", "injection ", "is..."])
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s1")

    s.add_transcript("What is dependency injection?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()

    assert col.of(isess.EVT_QUESTION_DETECTED)
    assert col.of(isess.EVT_ANSWER_STARTED)
    assert col.of(isess.EVT_ANSWER_CHUNK)
    done = col.of(isess.EVT_ANSWER_COMPLETED)[0]
    assert done["answer"] == "Dependency injection is..."
    assert ai.calls == 1
    mgr.shutdown()


def test_statement_is_ignored():
    ai = FakeAI()
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s2")

    s.add_transcript("Thanks, that makes sense.", is_final=True)
    # Give the EOU loop time to run; nothing should be generated.
    time.sleep(0.4)
    assert not col.of(isess.EVT_QUESTION_DETECTED)
    assert ai.calls == 0
    mgr.shutdown()


def test_partial_then_final_merges_into_one_question():
    ai = FakeAI(chunks=["ok"])
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s3")

    s.add_transcript("how would you", is_final=False)
    s.add_transcript("how would you scale a web service", is_final=False)
    s.add_transcript("how would you scale a web service?", is_final=True)

    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()
    detected = col.of(isess.EVT_QUESTION_DETECTED)
    assert len(detected) == 1
    assert "scale a web service" in detected[0]["text"]
    assert col.of(isess.EVT_TRANSCRIPT_PARTIAL)  # partials were emitted
    mgr.shutdown()


def test_duplicate_question_suppressed():
    ai = FakeAI(chunks=["a"])
    mgr, _ = make_manager(ai=ai, duplicateWindowS=60)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s4")

    s.add_transcript("What is a closure?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()
    first = ai.calls

    # Same question again within the window -> suppressed.
    s.add_transcript("What is a closure?", is_final=True)
    time.sleep(0.4)
    assert ai.calls == first == 1
    assert len(col.of(isess.EVT_QUESTION_DETECTED)) == 1
    mgr.shutdown()


def test_follow_up_uses_history_context():
    captured = {}

    class ContextAI(FakeAI):
        def answer_interview_question_stream(self, question, category=None, context=None,
                                             candidate_profile=None, model=None, temperature=None,
                                             language=None):
            captured["context"] = context
            yield "ok"

    ai = ContextAI()
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s5")

    s.add_transcript("What is indexing in databases?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED), col.types()

    s.add_transcript("Why did you choose that approach?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED, timeout=3.0, count=2)
    # The follow-up's context should include the earlier turn.
    assert "indexing" in (captured.get("context") or "").lower()
    mgr.shutdown()


def test_multiple_sessions_are_independent():
    ai = FakeAI(chunks=["x"])
    mgr, _ = make_manager(ai=ai)
    c1, c2 = Collector(), Collector()
    s1 = mgr.start_session(emit=c1.push, session_id="a")
    s2 = mgr.start_session(emit=c2.push, session_id="b")

    s1.add_transcript("What is TCP?", is_final=True)
    s2.add_transcript("What is UDP?", is_final=True)

    assert c1.wait_for(isess.EVT_ANSWER_COMPLETED)
    assert c2.wait_for(isess.EVT_ANSWER_COMPLETED)

    assert s1.history() and s2.history()
    assert "TCP" in s1.history()[-1]["text"]
    assert "UDP" in s2.history()[-1]["text"]
    # No cross-contamination of history.
    assert all("UDP" not in t["text"] for t in s1.history())
    mgr.shutdown()


def test_generation_failure_emits_recoverable_error():
    ai = FakeAI(fail_times=1)
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s6")

    s.add_transcript("What is a mutex?", is_final=True)
    assert col.wait_for(isess.EVT_ERROR), col.types()
    err = col.of(isess.EVT_ERROR)[0]
    assert err["recoverable"] is True
    assert not col.of(isess.EVT_ANSWER_COMPLETED)
    mgr.shutdown()


def test_not_configured_emits_error():
    ai = FakeAI(configured=False)
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s7")

    s.add_transcript("What is a semaphore?", is_final=True)
    assert col.wait_for(isess.EVT_ERROR), col.types()
    assert ai.calls == 0  # never attempted the call
    mgr.shutdown()


def test_cancel_before_completion():
    # Slow streaming so we can cancel mid-flight.
    ai = FakeAI(chunks=["a", "b", "c", "d"], delay=0.15)
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s8")

    s.add_transcript("Explain the CAP theorem.", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_STARTED), col.types()
    time.sleep(0.1)
    assert s.cancel_active(reason="test") is True
    # After cancel, no ANSWER_COMPLETED should arrive.
    time.sleep(0.8)
    assert not col.of(isess.EVT_ANSWER_COMPLETED)
    assert col.of(isess.EVT_QUESTION_CANCELLED)
    mgr.shutdown()


def test_at_most_one_generation_per_question():
    ai = FakeAI(chunks=["one"])
    mgr, _ = make_manager(ai=ai)
    col = Collector()
    s = mgr.start_session(emit=col.push, session_id="s9")

    s.add_transcript("What is a B-tree?", is_final=True)
    assert col.wait_for(isess.EVT_ANSWER_COMPLETED)
    assert ai.calls == 1
    assert len(col.of(isess.EVT_ANSWER_STARTED)) == 1
    mgr.shutdown()
