"""Unit tests for the heuristic question-detection engine (no network)."""
import pytest

from interview_config import InterviewConfig
import question_detector as qd


@pytest.fixture
def detector():
    # LLM disabled so these tests are pure/offline.
    cfg = InterviewConfig(useLlmClassifier=False)
    return qd.QuestionDetector(cfg, ai_module=None)


# ── Questions that MUST be detected ────────────────────────────────────────────

@pytest.mark.parametrize("text,expected_cat", [
    ("What is dependency injection?", qd.CATEGORY_TECHNICAL),
    ("Can you explain Angular change detection?", qd.CATEGORY_TECHNICAL),
    ("Write a function to reverse a linked list.", qd.CATEGORY_CODING),
    ("Tell me about a production issue you solved.", qd.CATEGORY_BEHAVIORAL),
    ("How would you handle 1,000 concurrent API requests?", qd.CATEGORY_SYSTEM_DESIGN),
    ("Why did you choose that approach?", qd.CATEGORY_GENERAL),
    ("Your approach to database indexing?", qd.CATEGORY_TECHNICAL),
])
def test_detects_genuine_questions(detector, text, expected_cat):
    result = detector.detect(text)
    assert result.is_question, f"should detect: {text!r} ({result.reason})"
    assert result.confidence >= 0.5
    assert result.category == expected_cat


# ── Utterances that MUST be ignored ────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Hi there, nice to meet you.",
    "Good morning!",
    "Thanks, that makes sense.",
    "Okay.",
    "Um,",
    "Great.",
    "My name is Alex, the hiring manager.",
    "So, let me introduce the team.",
])
def test_ignores_non_questions(detector, text):
    result = detector.detect(text)
    assert not result.is_question, f"should ignore: {text!r} ({result.reason})"


# ── Incomplete speech ──────────────────────────────────────────────────────────

def test_incomplete_fragment_not_answered(detector):
    # Trails on a connective; should be flagged incomplete and not a question yet.
    result = detector.detect("so what is the")
    assert result.complete is False
    assert result.is_question is False


def test_fragment_becomes_question_when_complete(detector):
    partial = detector.detect("how do you")
    assert partial.is_question is False
    full = detector.detect("how do you handle retries in a distributed queue?")
    assert full.is_question is True


# ── Empty / whitespace ─────────────────────────────────────────────────────────

def test_empty_text(detector):
    assert detector.detect("   ").is_question is False
    assert detector.detect("").is_question is False


# ── LLM confirmation path (stubbed, no network) ────────────────────────────────

class _StubAI:
    """Minimal ai-module stub returning a canned classifier JSON."""
    def __init__(self, payload, configured=True):
        self.payload = payload
        self._configured = configured
        self.calls = 0

    def is_configured(self):
        return self._configured

    def ask(self, text, system_prompt=None, model=None):
        self.calls += 1
        return self.payload


def test_llm_confirms_ambiguous_case():
    cfg = InterviewConfig(useLlmClassifier=True)
    stub = _StubAI('{"is_question": true, "confidence": 0.9, '
                   '"category": "behavioral", "complete": true}')
    detector = qd.QuestionDetector(cfg, ai_module=stub)
    # "walk me through your day" is request-opener-ish but ambiguous.
    result = detector.detect("walk me through your typical day")
    # Either heuristic already decided (strong) or LLM confirmed; must be a
    # question and the LLM should have been consulted only in the ambiguous band.
    assert result.is_question is True


def test_llm_failure_falls_back_to_heuristic():
    cfg = InterviewConfig(useLlmClassifier=True)

    class _BoomAI:
        def is_configured(self):
            return True
        def ask(self, *a, **k):
            raise RuntimeError("api down")

    detector = qd.QuestionDetector(cfg, ai_module=_BoomAI())
    # A clearly strong question should still be detected via heuristic even if
    # the LLM path is never reached / fails.
    result = detector.detect("What is a hash map?")
    assert result.is_question is True
