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

import logging
import os

log = logging.getLogger("ai")

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


# ── Interview answer prompts (automatic question answering) ────────────────────
# One base prompt + per-category guidance. Reused by answer_interview_question()
# below, which routes to the existing ask()/ask_stream() plumbing.

INTERVIEW_BASE_PROMPT = (
    "You are assisting a candidate in a live technical interview. You are given "
    "the interviewer's question and (optionally) recent conversation context and "
    "the candidate's profile. Produce an answer the candidate can speak.\n"
    "Rules:\n"
    "- Lead with a direct answer, then a short explanation, then a practical "
    "example when it helps, then important caveats or trade-offs when relevant.\n"
    "- Be concise, natural, and technically accurate.\n"
    "- NEVER invent resume details, work history, benchmarks, or facts you are "
    "not given. If context is insufficient, say so briefly rather than "
    "fabricating.\n"
)

INTERVIEW_CATEGORY_PROMPTS = {
    "technical": (
        "This is a technical concept question. Explain clearly with correct "
        "terminology; include a small concrete example and one common pitfall."
    ),
    "coding": (
        "This is a coding question. Provide: (1) a brief approach, (2) a correct "
        "solution in a clearly fenced code block, (3) time/space complexity, and "
        "(4) key edge cases. Prefer the language implied by the question, else "
        "Python."
    ),
    "behavioral": (
        "This is a behavioral question. Structure the answer using STAR "
        "(Situation, Task, Action, Result). Use ONLY candidate details provided "
        "in context; do NOT invent experiences. If no relevant experience is "
        "provided, give a STAR-shaped template the candidate can fill in and say "
        "so."
    ),
    "system_design": (
        "This is a system-design question. Cover requirements/assumptions, a "
        "high-level architecture, key components, data flow, scaling and "
        "bottlenecks, and trade-offs. Keep it structured and concise."
    ),
    "general": (
        "Answer directly and concisely. If the question is ambiguous, state the "
        "most likely intent in one line, then answer."
    ),
}


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


# Per-language output-script steering prompts for transcription. Whisper-family
# models bias their output SCRIPT toward whatever script appears in `prompt`.
# The classic failure this fixes: Hindi speech transcribed into Urdu (Arabic)
# script because Hindi/Urdu are the same spoken language. A short Devanagari
# sample pins Hindi (and Marathi) output to Devanagari. Extend as needed for
# other script-ambiguous languages; absence just means "no steering".
_SCRIPT_STEER_PROMPTS = {
    "hi": "निम्नलिखित वार्तालाप हिंदी (देवनागरी लिपि) में लिखें।",
    "mr": "खालील संवाद मराठी (देवनागरी लिपी) मध्ये लिहा.",
    # Hinglish: transcribe the Hindi-English code-mixed speech in ROMAN/LATIN
    # script, keeping the natural mix (do NOT convert to Devanagari or to pure
    # English). The sample itself is Roman Hinglish to steer the output script.
    "hing": ("Transcribe this Hindi-English code-mixed speech in Roman script, "
             "e.g. 'yeh function kaise optimize karein aur iska time complexity "
             "kya hai'."),
}


def _normalize_language_set_local(codes) -> list[str]:
    """Best-effort normalize a list of language values to base codes, reusing
    the shared registry normalizer when available (never raises)."""
    out = []
    try:
        import interview_config as _ic
        for c in (codes or []):
            base = _ic.normalize_language(c, fallback=None) if hasattr(_ic, "normalize_language") else None
            if base is None and c:
                base = str(c).strip().lower().replace("_", "-").split("-")[0]
            if base and base not in out:
                out.append(base)
    except Exception:  # noqa: BLE001
        for c in (codes or []):
            if c:
                base = str(c).strip().lower().replace("_", "-").split("-")[0]
                if base and base not in out:
                    out.append(base)
    return out


def transcribe_detailed(
    audio_bytes: bytes,
    filename: str = "chunk.webm",
    model: str | None = None,
    language: str | None = None,
    candidate_languages: list[str] | None = None,
) -> tuple[str, str | None]:
    """
    Transcribe a short audio chunk and (best-effort) report its language.

    Returns a 2-tuple ``(text, detected_language | None)``. `language`, when
    given, is passed to STT as a single hard hint (a base ISO code). We attempt
    ``response_format="verbose_json"`` so the response can carry a language;
    if the model rejects that format or returns no usable language, we fall
    back to a plain transcription and report ``None`` (the caller then runs the
    LLM classifier). Raises AIError on auth/rate/timeout/connection failures.

    `candidate_languages` is accepted for interface symmetry with the caller;
    the OpenAI transcription `language` param takes a single code only, so the
    set itself is used upstream to decide whether to pass a hard hint.
    """
    if not audio_bytes:
        return "", None
    client = _get_client()
    import io

    # `sem_lang` is the SEMANTIC language we're steering toward (may be the
    # pseudo-code "hing"). `hint` is the real ISO code we hand to STT's
    # `language` param — which must be a genuine code, so Hinglish passes NO
    # hard code (forcing "hi" would push Devanagari; we rely on the Roman
    # steering prompt instead to keep the output in Latin script).
    sem_lang = None
    if language and str(language).strip():
        sem_lang = str(language).strip().lower().replace("_", "-")
        # Preserve the 4-letter "hing" pseudo-code; otherwise take the base.
        sem_lang = sem_lang if sem_lang == "hing" else sem_lang.split("-")[0]

    # When the caller gave no single semantic language but the candidate set
    # points unambiguously at one script-sensitive language, steer by that.
    if sem_lang is None and candidate_languages:
        norm = _normalize_language_set_local(candidate_languages)
        if "hing" in norm:
            sem_lang = "hing"              # code-mixed, Roman script
        elif "hi" in norm and "ur" not in norm:
            sem_lang = "hi"               # Hindi, Devanagari

    # The real ISO code passed to STT: Hinglish -> none (don't force Devanagari);
    # any other pseudo-handling maps here. A normal code passes through.
    hint = None if sem_lang in (None, "hing") else sem_lang

    # Script-steering prompt: a short sample in the target script nudges the
    # model to emit that script. Fixes Hindi->Urdu (Arabic) script drift, and
    # keeps Hinglish in Roman/Latin. The `language` code biases detection but
    # does NOT control output script; the prompt does.
    steer_prompt = _SCRIPT_STEER_PROMPTS.get(sem_lang)

    # First attempt: verbose_json so we can read back a detected language.
    try:
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        kwargs: dict = {"model": model or TRANSCRIBE_MODEL, "file": buf,
                        "response_format": "verbose_json"}
        if hint:
            kwargs["language"] = hint
        if steer_prompt:
            kwargs["prompt"] = steer_prompt
        resp = client.audio.transcriptions.create(**kwargs)
        text = (getattr(resp, "text", "") or "").strip()
        detected = getattr(resp, "language", None)
        if detected:
            # The API may return a full name or a locale; normalize to a base
            # code via the registry so downstream comparisons are consistent.
            detected = _normalize_detected_language(str(detected))
        return text, (detected or None)
    except AIError:
        raise
    except Exception:  # noqa: BLE001 — verbose_json unsupported / parse miss
        log.debug("transcribe_detailed: verbose_json failed, falling back to plain")

    # Fallback: plain transcription (text only), language unknown.
    try:
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        kwargs = {"model": model or TRANSCRIBE_MODEL, "file": buf}
        if hint:
            kwargs["language"] = hint
        if steer_prompt:
            kwargs["prompt"] = steer_prompt
        resp = client.audio.transcriptions.create(**kwargs)
        return (getattr(resp, "text", "") or "").strip(), None
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _wrap_openai_errors(exc)


def _normalize_detected_language(value: str) -> str | None:
    """Map an STT-reported language (base code, locale, or English name) to a
    supported base code, or None if it isn't recognized."""
    v = (value or "").strip().lower()
    if not v:
        return None
    try:
        import interview_config as _ic
        registry = _ic.SUPPORTED_LANGUAGES
    except Exception:  # noqa: BLE001
        registry = {"en": {"name": "English"}}
    base = v.replace("_", "-").split("-")[0]
    if base in registry:
        return base
    # Match an English language name (OpenAI sometimes returns e.g. "english").
    for code, meta in registry.items():
        if v == str(meta.get("name", "")).lower():
            return code
    return None


def transcribe(audio_bytes: bytes, filename: str = "chunk.webm", model: str | None = None) -> str:
    """
    Transcribe a short audio chunk to text using OpenAI.

    `audio_bytes` is a complete, decodable audio file (e.g. a webm/opus or wav
    segment). `filename` just hints the format to the API via its extension.
    Returns the transcript text (may be empty for silence). Raises AIError.

    Text-only wrapper over transcribe_detailed() so existing callers (the Audio
    tab, tests) keep the same signature and return type.

    NOTE: local Whisper (faster-whisper) is the planned zero-cost fallback
    (OQ-2); hook it in here if OPENAI is unavailable or cost must be avoided.
    """
    text, _ = transcribe_detailed(audio_bytes, filename=filename, model=model)
    return text


# System prompt for the tiny, set-constrained language classifier.
_DETECT_LANGUAGE_SYSTEM_PROMPT = (
    "You identify the language of a short transcript. Respond with ONLY a "
    "language code chosen strictly from this allowed set: {codes}. "
    "The code 'hing' means Hinglish — Hindi and English mixed together in one "
    "utterance (often in Roman script), e.g. 'yeh approach scalable hai kya'; "
    "prefer 'hing' over 'hi' or 'en' when the speech clearly mixes both. "
    "If you are unsure, return {default}. Output nothing but the code."
)


def detect_language(text: str, candidate_languages: list[str], model: str | None = None) -> str:
    """
    Classify `text` into one of `candidate_languages` (base ISO codes) with a
    single short chat call. NEVER raises: on any error, unparseable reply, or an
    off-set answer, it coerces to ``candidate_languages[0]`` (the set default).
    """
    allowed = [c for c in (candidate_languages or []) if c]
    if not allowed:
        return "en"
    default = allowed[0]
    text = (text or "").strip()
    if not text:
        return default
    try:
        if not is_configured():
            return default
        client = _get_client()
        system = _DETECT_LANGUAGE_SYSTEM_PROMPT.format(
            codes=", ".join(allowed), default=default)
        resp = client.chat.completions.create(
            model=model or CHAT_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": text}],
        )
        raw = (resp.choices[0].message.content or "").strip().lower()
    except Exception as exc:  # noqa: BLE001 — classification must never crash
        log.debug("detect_language failed, using set default %r: %s", default, exc)
        return default
    base = raw.replace("_", "-").split("-")[0].strip()
    # Keep only the first token of letters (the model may add stray words).
    # Allow up to 4 letters so the "hing" (Hinglish) pseudo-code survives.
    import re as _re
    m = _re.search(r"[a-z]{2,4}", base)
    code = m.group(0) if m else ""
    return code if code in allowed else default


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


# ── Interview answer generation (automatic question answering) ─────────────────

# Human-readable names for the language codes we support. These are looked up
# from the canonical registry in interview_config so ai.py and the config stay
# in lockstep; a tiny local fallback keeps ai.py usable even if the config
# import fails (mirrors the defensive OpenAI import above).
_FALLBACK_LANGUAGE_NAMES = {"en": "English"}


def _language_names() -> dict:
    """Return {code: English name} from the interview_config registry, with a
    local English-only fallback if the config module can't be imported."""
    try:
        import interview_config as _ic
        return {code: meta.get("name", code)
                for code, meta in _ic.SUPPORTED_LANGUAGES.items()}
    except Exception:  # noqa: BLE001 — degrade gracefully to English only
        return dict(_FALLBACK_LANGUAGE_NAMES)


# Back-compat module attribute (kept so existing importers still see a map).
LANGUAGE_NAMES = _language_names()
DEFAULT_ANSWER_LANGUAGE = os.environ.get("INTERVIEW_DEFAULT_LANGUAGE", "en").split("-")[0].lower()


# Per-code overrides for the answer-language directive, where the generic
# "respond in <Name>" wording isn't precise enough (e.g. Hinglish needs the
# code-mixed, Roman-script style spelled out).
_ANSWER_LANGUAGE_DIRECTIVES = {
    "hing": (
        "- Respond in Hinglish: natural Hindi-English code-mixing written in "
        "Roman/Latin script (NOT Devanagari, NOT pure English), the same "
        "conversational style the interviewer used, e.g. \"Dekho, is problem "
        "ko hum hashmap se solve kar sakte hain, time complexity O(n) rahegi.\" "
        "Keep technical terms in English as a natural speaker would."
    ),
}


def language_instruction(language: str | None) -> str:
    """Return a one-line instruction pinning the answer language (English by
    default). Unknown/empty values fall back to English — we never silently
    switch to an unsupported language. This is the shared source of the
    answer-language directive string (reused by server.py's /api/ask path)."""
    raw = (language or DEFAULT_ANSWER_LANGUAGE or "en").strip().lower().replace("_", "-")
    code = raw if raw == "hing" else raw.split("-")[0]
    if code in _ANSWER_LANGUAGE_DIRECTIVES:
        return _ANSWER_LANGUAGE_DIRECTIVES[code]
    name = _language_names().get(code, "English")
    return (f"- Always respond in {name}, regardless of the input language. "
            "Match the language of the interviewer's question exactly.")


# Backward-compat alias for internal callers (the public name is preferred).
_language_instruction = language_instruction


def _build_interview_prompt(category: str | None, language: str | None = None) -> str:
    """Compose the base interview prompt with category-specific guidance and a
    language directive (defaults to English)."""
    cat = (category or "general").lower()
    guidance = INTERVIEW_CATEGORY_PROMPTS.get(cat, INTERVIEW_CATEGORY_PROMPTS["general"])
    return (INTERVIEW_BASE_PROMPT + "\n" + guidance
            + "\n" + _language_instruction(language))


def _build_interview_user_content(
    question: str,
    context: str | None = None,
    candidate_profile: str | None = None,
) -> str:
    """Assemble the user message: question + optional context/profile blocks."""
    question = (question or "").strip()
    if not question:
        raise AIError("No question provided to answer.")
    parts = []
    if candidate_profile and candidate_profile.strip():
        parts.append("Candidate profile:\n" + candidate_profile.strip())
    if context and context.strip():
        parts.append("Recent conversation (for context only):\n" + context.strip())
    parts.append("Interviewer's question:\n" + question)
    return "\n\n".join(parts)


def answer_interview_question(
    question: str,
    category: str | None = None,
    context: str | None = None,
    candidate_profile: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    language: str | None = None,
) -> str:
    """
    Generate a complete interview answer for `question`. Reuses the Chat
    Completions client. `language` pins the answer language (English by
    default). Raises AIError on failure.
    """
    client = _get_client()
    system = _build_interview_prompt(category, language)
    user = _build_interview_user_content(question, context, candidate_profile)
    kwargs: dict = {"model": model or CHAT_MODEL,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}]}
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _wrap_openai_errors(exc)


def answer_interview_question_stream(
    question: str,
    category: str | None = None,
    context: str | None = None,
    candidate_profile: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    language: str | None = None,
):
    """
    Stream an interview answer, yielding text chunks. `language` pins the answer
    language (English by default). Raises AIError on failure.
    """
    client = _get_client()
    system = _build_interview_prompt(category, language)
    user = _build_interview_user_content(question, context, candidate_profile)
    kwargs: dict = {"model": model or CHAT_MODEL,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "stream": True}
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                yield piece
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _wrap_openai_errors(exc)
