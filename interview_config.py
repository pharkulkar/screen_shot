#!/usr/bin/env python3
"""
interview_config.py — configuration for automatic interview-question detection
==============================================================================
Centralises every tunable for the "smart auto-detect" feature so the detection
engine, the session manager, and the server routes all read one consistent set
of values.

Precedence (highest wins):
    1. Environment variables (INTERVIEW_* ) — handy for ops / per-run overrides.
    2. The "interview" block in config.json.
    3. Built-in defaults below.

Nothing here imports OpenAI or Flask, so it is cheap to import from tests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_CONFIG_PATH = ROOT / "config.json"


# ── Defaults ──────────────────────────────────────────────────────────────────
# Kept conservative: a short end-of-utterance window, a modest confidence bar,
# and a minimum length that still accepts short-but-valid questions.
_DEFAULTS: dict = {
    "detectionConfidenceThreshold": 0.6,   # 0..1 — below this we don't answer
    "endOfUtteranceMs": 700,               # silence/finalization window (500-1000)
    "minTranscriptChars": 6,               # don't reject short valid questions
    "answerTimeoutS": 45,                  # per-answer generation timeout
    "maxHistoryTurns": 40,                 # per-session conversation history cap
    "chatModel": None,                     # None -> ai.py default (gpt-4o-mini)
    "temperature": 0.3,
    "streaming": True,
    "duplicateWindowS": 120,               # dedup window for repeated questions
    "maxConcurrentGenerations": 4,         # global cap on in-flight LLM answers
    "useLlmClassifier": True,              # use LLM to confirm ambiguous cases
    "llmClassifierModel": None,            # None -> ai.py default
    "defaultLanguage": "en",               # default language code (English)
    "defaultSpeechLocale": "en-IN",        # preferred STT locale (Indian English)
}


# ── Language registry (extensible) ─────────────────────────────────────────────
# Maps a base language code -> human name + the speech-to-text locale we prefer.
# English is the default; add entries here to support more languages later. The
# session/detector/answer layers only need the base code; the locale is a hint
# the frontend's STT provider can use (falling back to its own English locale if
# en-IN is unavailable).
SUPPORTED_LANGUAGES: dict = {
    "en": {"name": "English", "default_locale": "en-IN"},
}

DEFAULT_LANGUAGE = "en"
DEFAULT_SPEECH_LOCALE = "en-IN"


def normalize_language(value: str | None, fallback: str = DEFAULT_LANGUAGE) -> str:
    """
    Normalize a client-supplied language value to a supported base code.

    Accepts either a base code ("en") or a locale ("en-IN", "en_US") and maps it
    to the base code. Unknown/empty values fall back to English (we never
    auto-switch to an unsupported language on a bad value).
    """
    if not value or not str(value).strip():
        return fallback
    base = str(value).strip().lower().replace("_", "-").split("-")[0]
    if base in SUPPORTED_LANGUAGES:
        return base
    return fallback


def speech_locale_for(language: str | None) -> str:
    """Return the preferred STT locale for a language code (default en-IN)."""
    base = normalize_language(language)
    return SUPPORTED_LANGUAGES.get(base, {}).get("default_locale", DEFAULT_SPEECH_LOCALE)


def _coerce(value, like):
    """Coerce an env string to the type of the default it overrides."""
    if value is None:
        return like
    if isinstance(like, bool):
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(like, int) and not isinstance(like, bool):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return like
    if isinstance(like, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return like
    return value


# Map each config key to its environment-variable override name.
_ENV_MAP = {
    "detectionConfidenceThreshold": "INTERVIEW_CONFIDENCE_THRESHOLD",
    "endOfUtteranceMs": "INTERVIEW_EOU_MS",
    "minTranscriptChars": "INTERVIEW_MIN_CHARS",
    "answerTimeoutS": "INTERVIEW_ANSWER_TIMEOUT_S",
    "maxHistoryTurns": "INTERVIEW_MAX_HISTORY_TURNS",
    "chatModel": "INTERVIEW_CHAT_MODEL",
    "temperature": "INTERVIEW_TEMPERATURE",
    "streaming": "INTERVIEW_STREAMING",
    "duplicateWindowS": "INTERVIEW_DUP_WINDOW_S",
    "maxConcurrentGenerations": "INTERVIEW_MAX_CONCURRENT",
    "useLlmClassifier": "INTERVIEW_USE_LLM_CLASSIFIER",
    "llmClassifierModel": "INTERVIEW_LLM_CLASSIFIER_MODEL",
    "defaultLanguage": "INTERVIEW_DEFAULT_LANGUAGE",
    "defaultSpeechLocale": "INTERVIEW_SPEECH_LOCALE",
}


@dataclass(frozen=True)
class InterviewConfig:
    detectionConfidenceThreshold: float = _DEFAULTS["detectionConfidenceThreshold"]
    endOfUtteranceMs: int = _DEFAULTS["endOfUtteranceMs"]
    minTranscriptChars: int = _DEFAULTS["minTranscriptChars"]
    answerTimeoutS: int = _DEFAULTS["answerTimeoutS"]
    maxHistoryTurns: int = _DEFAULTS["maxHistoryTurns"]
    chatModel: str | None = _DEFAULTS["chatModel"]
    temperature: float = _DEFAULTS["temperature"]
    streaming: bool = _DEFAULTS["streaming"]
    duplicateWindowS: float = _DEFAULTS["duplicateWindowS"]
    maxConcurrentGenerations: int = _DEFAULTS["maxConcurrentGenerations"]
    useLlmClassifier: bool = _DEFAULTS["useLlmClassifier"]
    llmClassifierModel: str | None = _DEFAULTS["llmClassifierModel"]
    defaultLanguage: str = _DEFAULTS["defaultLanguage"]
    defaultSpeechLocale: str = _DEFAULTS["defaultSpeechLocale"]

    @property
    def end_of_utterance_s(self) -> float:
        return self.endOfUtteranceMs / 1000.0

    @property
    def language(self) -> str:
        """The effective default language, normalized to a supported code."""
        return normalize_language(self.defaultLanguage)

    def to_dict(self) -> dict:
        return asdict(self)


def _read_file_block() -> dict:
    """Return the 'interview' block from config.json, or {} if absent/bad."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        block = data.get("interview", {})
        return block if isinstance(block, dict) else {}
    except (OSError, ValueError):
        return {}


def load_config() -> InterviewConfig:
    """Build an InterviewConfig from defaults <- config.json <- env vars."""
    merged = dict(_DEFAULTS)

    file_block = _read_file_block()
    for key in merged:
        if key in file_block and file_block[key] is not None:
            merged[key] = file_block[key]
        # A JSON null means "use the default" (lets config.json pin a model
        # to null while ai.py falls back to its own default).

    for key, env_name in _ENV_MAP.items():
        env_val = os.environ.get(env_name)
        if env_val is not None and env_val != "":
            merged[key] = _coerce(env_val, _DEFAULTS[key])

    return InterviewConfig(**merged)


# A module-level default instance for convenience; callers that want to pick up
# live changes should call load_config() themselves.
CONFIG = load_config()
