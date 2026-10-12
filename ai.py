#!/usr/bin/env python3
"""
ai.py — OpenAI integration helper
=================================
A thin, reusable layer over the OpenAI Chat Completions API. Keeps all
model/prompt logic in one place so the Flask routes stay small and later
phases (screenshot "solve", meeting suggestions) can reuse the same client.

Design notes:
- The API key is read from the environment (OPENAI_API_KEY), server-side only.
  It is NEVER sent to or exposed in the overlay.
- The client is created lazily so importing this module never fails just
  because a key isn't set yet (the server must still boot for gallery/OCR).
- Models are configurable via env; defaults match memory.md (gpt-4o-mini).
- Two entry points: `ask()` (returns the full answer) and `ask_stream()`
  (yields answer chunks for low-latency streaming to the overlay).
"""

import os

# The OpenAI SDK is a hard dependency (requirements.txt), but we import
# defensively so a missing install surfaces as a clean runtime error rather
# than crashing server startup.
try:
    from openai import OpenAI
    import openai as _openai_pkg
except ImportError:  # pragma: no cover
    OpenAI = None
    _openai_pkg = None


# ── Configuration ─────────────────────────────────────────────────────────────

# Default chat model (overridable via env). See memory.md "Chosen defaults".
CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")

# Transcription model (OQ-2 resolved: OpenAI gpt-4o-mini-transcribe).
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

# Request timeout (seconds) for a single OpenAI call.
REQUEST_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "30"))

# Answer-mode system prompt (Feature A default behavior): given text extracted
# from a screenshot (or typed), directly answer the on-screen question.
ANSWER_SYSTEM_PROMPT = (
    "You are a concise, accurate assistant. You are given text extracted from a "
    "user's screen (often a question, quiz item, form, or snippet of content). "
    "Determine what is being asked and give the best direct answer.\n"
    "- If it is a multiple-choice question, state the correct option and a one-"
    "line reason.\n"
    "- If it is an open question, answer directly and briefly.\n"
    "- If the text is ambiguous or incomplete, answer the most likely intended "
    "question and note the assumption in one short line.\n"
    "- Keep answers short and glanceable; the user is reading mid-task."
)


# Tone presets (Feature B/A UX). Appended to the system prompt to shape style.
TONE_SUFFIXES = {
    "concise": " Answer as briefly as possible — ideally one or two lines.",
    "detailed": " Give a thorough answer with brief reasoning or steps.",
    "professional": " Use a polished, professional tone suitable for work.",
    "casual": " Use a relaxed, conversational tone.",
}
DEFAULT_TONE = os.environ.get("ANSWER_TONE", "concise")


# Coach system prompt (Feature B): given the meeting dialogue, suggest what the
# user ("Me") could say next. Output is a short numbered list so we can split it.
COACH_SYSTEM_PROMPT = (
    "You are a real-time conversation coach helping the user during a live "
    "meeting. You are given the recent dialogue, where 'Me' is the user and "
    "'Them' is the other participant. Suggest what the user ('Me') could say "
    "next.\n"
    "- Provide 1 to 3 distinct, ready-to-say replies the user can speak "
    "verbatim.\n"
    "- Keep each suggestion to one or two sentences, natural and specific to "
    "the conversation.\n"
    "- Do not add commentary, labels, or explanations — only the reply options.\n"
    "- Return them as a numbered list (1., 2., 3.)."
)


class AIError(Exception):
    """Raised for any OpenAI-related failure, with a user-safe message."""


# ── Client ────────────────────────────────────────────────────────────────────

_client = None


def _get_client() -> "OpenAI":
    """
    Lazily build and cache the OpenAI client.

    Raises AIError (not ImportError / KeyError) so callers can convert it into
    a clean HTTP response.
    """
    global _client

    if _client is not None:
        return _client

    if OpenAI is None:
        raise AIError(
            "The 'openai' package is not installed. "
            "Run: pip3 install -r requirements.txt"
        )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AIError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your "
            "key, then restart the server."
        )

    _client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT)
    return _client


def is_configured() -> bool:
    """True if an API key is present (does not validate it with OpenAI)."""
    return bool(os.environ.get("OPENAI_API_KEY")) and OpenAI is not None


# ── Message assembly ──────────────────────────────────────────────────────────

def _build_messages(
    text: str,
    system_prompt: str | None = None,
    tone: str | None = None,
) -> list[dict]:
    text = (text or "").strip()
    if not text:
        raise AIError("No text provided to answer.")
    base = system_prompt or ANSWER_SYSTEM_PROMPT
    tone_key = (tone or DEFAULT_TONE).lower()
    base += TONE_SUFFIXES.get(tone_key, "")
    return [
        {"role": "system", "content": base},
        {"role": "user", "content": text},
    ]


def _wrap_openai_errors(exc: Exception) -> AIError:
    """Translate SDK exceptions into a single, user-safe AIError."""
    # Known OpenAI SDK error types (auth, rate limit, timeout, API error).
    name = type(exc).__name__
    msg = str(exc)
    if "AuthenticationError" in name:
        return AIError("OpenAI rejected the API key (authentication failed).")
    if "RateLimitError" in name:
        return AIError("OpenAI rate limit or quota exceeded. Try again shortly.")
    if "APITimeoutError" in name or "Timeout" in name:
        return AIError(f"OpenAI request timed out after {REQUEST_TIMEOUT:.0f}s.")
    if "APIConnectionError" in name:
        return AIError("Could not reach OpenAI (network/connection error).")
    return AIError(f"OpenAI request failed: {msg}")


# ── Public API ────────────────────────────────────────────────────────────────

def ask(
    text: str,
    system_prompt: str | None = None,
    model: str | None = None,
    tone: str | None = None,
) -> str:
    """
    Send `text` to OpenAI and return the complete answer as a string.

    Raises AIError on any failure (missing key, API error, timeout, empty input).
    """
    client = _get_client()
    messages = _build_messages(text, system_prompt, tone)
    try:
        resp = client.chat.completions.create(
            model=model or CHAT_MODEL,
            messages=messages,
        )
        return (resp.choices[0].message.content or "").strip()
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001 — normalized into AIError below
        raise _wrap_openai_errors(exc)


def transcribe(audio_bytes: bytes, filename: str = "chunk.webm", model: str | None = None) -> str:
    """
    Transcribe a short audio chunk to text using OpenAI.

    `audio_bytes` is a complete, decodable audio file (e.g. a webm/opus or wav
    segment). `filename` just hints the format to the API via its extension.
    Returns the transcript text (may be empty for silence). Raises AIError.

    NOTE: local Whisper (faster-whisper) is the planned zero-cost fallback
    (OQ-2); hook it in here if OPENAI is unavailable or cost must be avoided.
    """
    if not audio_bytes:
        return ""
    client = _get_client()
    try:
        import io
        buf = io.BytesIO(audio_bytes)
        buf.name = filename  # the SDK uses the name to infer the format
        resp = client.audio.transcriptions.create(
            model=model or TRANSCRIBE_MODEL,
            file=buf,
        )
        return (getattr(resp, "text", "") or "").strip()
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _wrap_openai_errors(exc)


def ask_stream(
    text: str,
    system_prompt: str | None = None,
    model: str | None = None,
    tone: str | None = None,
):
    """
    Stream the answer from OpenAI, yielding text chunks as they arrive.

    Yields str deltas. Raises AIError on failure (before/while streaming).
    """
    client = _get_client()
    messages = _build_messages(text, system_prompt, tone)
    try:
        stream = client.chat.completions.create(
            model=model or CHAT_MODEL,
            messages=messages,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                yield piece
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001 — normalized into AIError below
        raise _wrap_openai_errors(exc)


def _parse_suggestions(text: str) -> list[str]:
    """Split a numbered/bulleted model reply into a clean list of suggestions."""
    import re
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading "1.", "2)", "- ", "* " markers.
        line = re.sub(r"^\s*(?:\d+[\.\)]|[-*•])\s*", "", line).strip()
        # Strip surrounding quotes the model sometimes adds.
        line = line.strip('"').strip("'").strip()
        if line:
            out.append(line)
    # Fallback: if nothing parsed, return the whole thing as one suggestion.
    if not out and text and text.strip():
        out = [text.strip()]
    return out[:3]


def suggest(dialogue: str, tone: str | None = None, model: str | None = None) -> list[str]:
    """
    Given the recent 'Me'/'Them' dialogue, return 1-3 short reply suggestions.

    Raises AIError on failure. Returns [] if there's no dialogue to work from.
    """
    dialogue = (dialogue or "").strip()
    if not dialogue:
        return []
    client = _get_client()
    system = COACH_SYSTEM_PROMPT + TONE_SUFFIXES.get((tone or DEFAULT_TONE).lower(), "")
    try:
        resp = client.chat.completions.create(
            model=model or CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": dialogue},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        return _parse_suggestions(content)
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _wrap_openai_errors(exc)
