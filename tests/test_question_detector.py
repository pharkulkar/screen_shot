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


# ── Non-Latin / non-English detection ──────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "क्लोज़र क्या है।",   # Devanagari danda
    "什么是闭包？",         # full-width question mark
    "ما هو الإغلاق؟",      # Arabic question mark
])
def test_non_latin_question_clears_threshold_without_llm(text):
    """A bare non-Latin question with the LLM disabled must be detected with
    confidence >= the 0.6 finalization threshold (the lenient non-en floor)."""
    cfg = InterviewConfig(useLlmClassifier=False)
    detector = qd.QuestionDetector(cfg, ai_module=None)
    # Infer a plausible non-en language code from the script.
    lang = "hi" if any("\u0900" <= c <= "\u097f" for c in text) else (
        "zh" if any("\u4e00" <= c <= "\u9fff" for c in text) else "ar")
    result = detector.detect(text, language=lang)
    assert result.is_question is True, result.reason
    assert result.confidence >= cfg.detectionConfidenceThreshold


def test_non_english_detected_via_llm_stub():
    """With an LLM stub + a non-en language, the classifier confirms a question."""
    cfg = InterviewConfig(useLlmClassifier=True)
    stub = _StubAI('{"is_question": true, "confidence": 0.95, '
                   '"category": "technical", "complete": true}')
    detector = qd.QuestionDetector(cfg, ai_module=stub)
    result = detector.detect("क्लोज़र क्या है।", language="hi")
    assert result.is_question is True
    assert stub.calls == 1  # the LLM path was consulted for non-en


def test_english_path_unchanged_by_language_default():
    """Passing no language (English) keeps the existing behavior."""
    cfg = InterviewConfig(useLlmClassifier=False)
    detector = qd.QuestionDetector(cfg, ai_module=None)
    assert detector.detect("What is a closure?").is_question is True
    assert detector.detect("Thanks, that makes sense.").is_question is False
