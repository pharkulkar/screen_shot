#!/usr/bin/env python3
"""
question_detector.py — Interview Question Detection Engine
==========================================================
Decides whether a (finalized) transcript segment is a genuine interview
question / request that deserves an auto-generated answer.

Design goals (from the feature spec):
  - Recognise direct, explanatory, coding, behavioural, scenario, follow-up and
    implicit questions.
  - Ignore greetings, acknowledgements, filler, interviewer explanations and
    incomplete speech.
  - Do NOT rely only on "?" or keywords like what/why/how.
  - Use heuristics first (free, instant); fall back to an LLM classifier for
    ambiguous cases only (cost control), reusing ai.py if it is configured.

The engine is intentionally dependency-light so it is trivially unit-testable:
heuristics are pure functions, and the LLM path is injected (ai_module) so tests
can stub it or run fully offline.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict

log = logging.getLogger("interview.detector")

# Question categories used downstream for prompt/format selection.
CATEGORY_TECHNICAL = "technical"
CATEGORY_CODING = "coding"
CATEGORY_BEHAVIORAL = "behavioral"
CATEGORY_SYSTEM_DESIGN = "system_design"
CATEGORY_GENERAL = "general"

ALL_CATEGORIES = {
    CATEGORY_TECHNICAL,
    CATEGORY_CODING,
    CATEGORY_BEHAVIORAL,
    CATEGORY_SYSTEM_DESIGN,
    CATEGORY_GENERAL,
}


@dataclass
class DetectionResult:
    is_question: bool
    confidence: float            # 0..1
    category: str = CATEGORY_GENERAL
    complete: bool = True        # False => looks like it's still being spoken
    reason: str = ""
    source: str = "heuristic"    # "heuristic" | "llm"

    def to_dict(self) -> dict:
        return asdict(self)


# ── Lexicons / patterns ───────────────────────────────────────────────────────

_WH_WORDS = (
    "what", "why", "how", "when", "where", "which", "who", "whom", "whose",
)

# Request / imperative openers that signal a question without a "?".
_REQUEST_OPENERS = (
    "explain", "describe", "tell me", "walk me through", "write", "implement",
    "design", "give me", "share", "can you", "could you", "would you",
    "how would you", "what would you", "let's talk about", "talk about",
    "define", "compare", "contrast", "elaborate", "show me",
)

# Phrases that indicate the utterance is NOT a question for the candidate.
_IGNORE_PATTERNS = (
    r"^\s*(hi|hey|hello|good (morning|afternoon|evening))\b",
    r"^\s*(thanks|thank you|great|awesome|perfect|cool|nice|okay|ok|sure|got it|understood|makes sense|sounds good)\b[\s.!]*$",
    r"^\s*(um+|uh+|hmm+|er+|ah+|like|so|well)\b[\s.,]*$",
    r"^\s*(let me (introduce|tell you)|my name is|i'?m\s+\w+,? (the|a|an)\b)",
    r"^\s*(we('| a)re|this (is|interview)|today (we|i)|i'?ll be)\b",
)

# Coding / implementation signal words.
_CODING_WORDS = (
    "function", "algorithm", "code", "implement", "program", "method",
    "linked list", "binary tree", "array", "string", "recursion", "sort",
    "reverse", "data structure", "leetcode", "time complexity", "big o",
    "snippet", "class", "api endpoint", "sql query", "regex",
)

# System-design signal words.
_SYSTEM_DESIGN_WORDS = (
    "design a", "architect", "scalab", "scale", "throughput", "concurrent",
    "distributed", "load balanc", "sharding", "caching", "high availability",
    "microservice", "rate limit", "requests per second", "qps",
    "handle 1", "handle thousand", "handle million", "system design",
)

# Behavioural signal words.
_BEHAVIORAL_WORDS = (
    "tell me about a time", "tell me about a", "describe a situation",
    "give me an example", "a time when", "how did you handle",
    "a challenge", "a conflict", "a production issue", "a mistake",
    "your experience", "worked on", "proud of", "disagree",
)

# Technical signal words (concept explanations).
_TECHNICAL_WORDS = (
    "dependency injection", "change detection", "indexing", "database",
    "garbage collection", "closure", "promise", "async", "thread",
    "difference between", "how does", "what is", "explain", "concept",
    "framework", "protocol", "http", "rest", "graphql", "transaction",
)

# Follow-up signals (depend on prior context).
_FOLLOWUP_OPENERS = (
    "why did you", "why that", "why not", "and why", "what about",
    "how about", "can you expand", "go deeper", "and then", "what else",
    "anything else",
)

# Trailing tokens that strongly imply the speaker is mid-sentence.
_INCOMPLETE_TRAILERS = (
    "and", "but", "so", "the", "a", "an", "to", "of", "for", "with", "in",
    "on", "or", "if", "when", "that", "this", "my", "your", "is", "are",
    "how", "what", "why", "because", "which",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _looks_incomplete(text: str, min_chars: int) -> bool:
    """
    Heuristic for "this utterance is probably still being spoken".

    True when the (final) text is very short, has no terminal punctuation and
    ends on a connective/filler word. This keeps us from answering a fragment
    that will become a real question once more words arrive.
    """
    norm = _normalize(text)
    if not norm:
        return True
    if len(norm) < max(3, min_chars):
        return True
    stripped = norm.rstrip(" .!?,")
    last_word = stripped.split(" ")[-1] if stripped else ""
    ends_terminal = norm.endswith(("?", ".", "!"))
    if not ends_terminal and last_word in _INCOMPLETE_TRAILERS:
        return True
    return False


def _classify_category(norm: str) -> str:
    """Pick the most specific matching category from heuristics."""
    if any(w in norm for w in _CODING_WORDS):
        return CATEGORY_CODING
    if any(w in norm for w in _SYSTEM_DESIGN_WORDS):
        return CATEGORY_SYSTEM_DESIGN
    if any(w in norm for w in _BEHAVIORAL_WORDS):
        return CATEGORY_BEHAVIORAL
    if any(w in norm for w in _TECHNICAL_WORDS):
        return CATEGORY_TECHNICAL
    return CATEGORY_GENERAL


def heuristic_detect(text: str, min_chars: int = 6) -> DetectionResult:
    """
    Pure, dependency-free detection. Returns a DetectionResult with a
    confidence in [0,1]. Confidence near 0.4-0.6 means "ambiguous" and is a
    good trigger for the optional LLM confirmation step.
    """
    norm = _normalize(text)
    if not norm:
        return DetectionResult(False, 0.0, reason="empty", complete=False)

    # Hard ignores (greetings, acks, filler, self-introductions).
    for pat in _IGNORE_PATTERNS:
        if re.search(pat, norm):
            return DetectionResult(
                False, 0.05, reason="matched ignore pattern", complete=True
            )

    incomplete = _looks_incomplete(text, min_chars)
    category = _classify_category(norm)

    score = 0.0
    reasons = []

    if norm.endswith("?"):
        score += 0.55
        reasons.append("ends with '?'")

    first_word = norm.split(" ")[0]
    if first_word in _WH_WORDS:
        score += 0.3
        reasons.append("wh-word opener")

    if any(norm.startswith(op) or (" " + op) in (" " + norm) for op in _REQUEST_OPENERS):
        score += 0.35
        reasons.append("request/imperative opener")

    if any(op in norm for op in _FOLLOWUP_OPENERS):
        score += 0.3
        reasons.append("follow-up opener")

    # Implicit question: a noun-phrase ending in "?" is already caught; also
    # treat short topic phrases ("your approach to X") as implicit requests.
    if re.search(r"\byour (approach|take|view|opinion|thoughts?|experience)\b", norm):
        score += 0.4
        reasons.append("implicit 'your ...' request")

    # Imperative verbs at the very start ("write ...", "design ...").
    if first_word in ("write", "implement", "design", "explain", "describe",
                       "compare", "define", "list", "name", "give"):
        score += 0.35
        reasons.append("imperative verb opener")

    # Category-specific nudges: coding / system-design / behavioral phrasing is
    # usually a task even without a trailing "?".
    if category in (CATEGORY_CODING, CATEGORY_SYSTEM_DESIGN):
        score += 0.15
        reasons.append(f"{category} signal")

    # Behavioural prompts ("tell me about a time...", "describe a situation...")
    # are genuine questions but rarely end in "?"; give them a solid signal.
    if any(w in norm for w in _BEHAVIORAL_WORDS):
        score += 0.3
        reasons.append("behavioral prompt signal")

    score = max(0.0, min(1.0, score))

    if incomplete:
        # Penalise but don't zero out — the orchestrator may still wait.
        score *= 0.5
        reasons.append("looks incomplete")

    is_q = score >= 0.5 and not incomplete
    return DetectionResult(
        is_question=is_q,
        confidence=round(score, 3),
        category=category,
        complete=not incomplete,
        reason="; ".join(reasons) or "no question signals",
        source="heuristic",
    )


# ── LLM confirmation (optional) ────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = (
    "You are a classifier inside an interview-assistant. Given a transcript "
    "segment spoken by an interviewer, decide if it is a genuine question or "
    "request that the candidate must answer. Ignore greetings, small talk, "
    "acknowledgements, filler, and the interviewer merely explaining things. "
    "Respond with ONLY compact JSON: "
    '{"is_question": true|false, "confidence": 0.0-1.0, '
    '"category": "technical|coding|behavioral|system_design|general", '
    '"complete": true|false}. No prose.'
)


def _parse_llm_json(raw: str) -> dict | None:
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def llm_detect(text: str, ai_module, model: str | None = None) -> DetectionResult | None:
    """
    Ask the LLM to confirm an ambiguous case. Returns None if the AI layer is
    unavailable / unconfigured / errors, so the caller can fall back to the
    heuristic result. Never raises.
    """
    if ai_module is None:
        return None
    try:
        if not ai_module.is_configured():
            return None
        raw = ai_module.ask(
            text,
            system_prompt=_LLM_SYSTEM_PROMPT,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001 — classification must never crash
        log.debug("llm_detect failed, falling back to heuristic: %s", exc)
        return None

    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return None

    category = str(data.get("category", CATEGORY_GENERAL)).lower()
    if category not in ALL_CATEGORIES:
        category = CATEGORY_GENERAL
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return DetectionResult(
        is_question=bool(data.get("is_question", False)),
        confidence=max(0.0, min(1.0, conf)),
        category=category,
        complete=bool(data.get("complete", True)),
        reason="llm classification",
        source="llm",
    )


class QuestionDetector:
    """
    Combines heuristics with an optional LLM confirmation step.

    `ai_module` is injected (defaults to the project's ai.py when available) so
    unit tests can run fully offline or stub the classifier.
    """

    # Confidence band treated as "ambiguous" -> worth an LLM confirmation.
    AMBIGUOUS_LOW = 0.35
    AMBIGUOUS_HIGH = 0.75

    def __init__(self, config, ai_module=None):
        self.config = config
        self.ai_module = ai_module

    def detect(self, text: str) -> DetectionResult:
        base = heuristic_detect(text, min_chars=self.config.minTranscriptChars)

        # A clear ignore or an obviously strong question: trust the heuristic.
        use_llm = (
            self.config.useLlmClassifier
            and self.ai_module is not None
            and base.complete  # never spend tokens on half-spoken fragments
            and self.AMBIGUOUS_LOW <= base.confidence <= self.AMBIGUOUS_HIGH
        )
        if not use_llm:
            return base

        llm = llm_detect(text, self.ai_module, model=self.config.llmClassifierModel)
        if llm is None:
            return base

        # Blend: prefer the LLM decision but keep the heuristic category when the
        # LLM is vague (general) and the heuristic was specific.
        if llm.category == CATEGORY_GENERAL and base.category != CATEGORY_GENERAL:
            llm.category = base.category
        return llm
