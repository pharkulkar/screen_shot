#!/usr/bin/env python3
"""
conversation.py — rolling meeting transcript buffer
===================================================
Holds the recent, speaker-tagged dialogue of the current meeting so Phase 6
(suggestions) can build "what should I say" prompts from context.

Per the privacy decision (OQ-3), the raw live transcript is IN-MEMORY ONLY by
default — it is not persisted. A later phase can add an opt-in "save transcript"
that writes it out; by default it vanishes when the process ends / is cleared.
"""

import threading
import time
from collections import deque

# Keep the last N turns in memory (bounded, so long meetings don't grow forever).
MAX_TURNS = 60

_lock = threading.Lock()
_turns: "deque[dict]" = deque(maxlen=MAX_TURNS)


def add_turn(speaker: str, text: str) -> dict | None:
    """
    Append a transcript turn. speaker is 'me' | 'them'. Empty text is ignored
    (silence chunks transcribe to '' and should not create turns).
    Returns the stored turn, or None if ignored.
    """
    text = (text or "").strip()
    if not text:
        return None
    speaker = (speaker or "them").lower()
    if speaker not in ("me", "them"):
        speaker = "them"
    turn = {"speaker": speaker, "text": text, "ts": time.time()}
    with _lock:
        _turns.append(turn)
    return turn


def get_turns() -> list[dict]:
    with _lock:
        return list(_turns)


def as_dialogue(limit: int | None = None) -> str:
    """Render recent turns as 'Me: ...' / 'Them: ...' lines for an LLM prompt."""
    turns = get_turns()
    if limit:
        turns = turns[-limit:]
    label = {"me": "Me", "them": "Them"}
    return "\n".join(f"{label.get(t['speaker'], 'Them')}: {t['text']}" for t in turns)


def clear() -> None:
    with _lock:
        _turns.clear()
