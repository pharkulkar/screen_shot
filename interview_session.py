#!/usr/bin/env python3
"""
interview_session.py — session state, finalization, dedup & answer orchestration
================================================================================
The brain behind automatic interview-question answering. It sits between the
transport (WebSocket / REST in server.py) and the two building blocks:

  - question_detector.QuestionDetector  — "is this a question?"
  - ai.answer_interview_question[_stream] — "answer it"

Responsibilities (from the feature spec):
  * Accept partial + final transcript segments per session.
  * Accumulate partials, merge consecutive same-utterance segments.
  * Finalize using an end-of-utterance (EOU) window, NOT a fixed timer alone:
    a FINAL segment arms the window; the window simply debounces so late words
    can still merge in before we commit.
  * Deduplicate repeated questions (normalized text + time window).
  * Assign a unique question id; support cancel/replace before generation.
  * Ensure at-most-one active generation per question; bound global concurrency.
  * Emit structured events: TRANSCRIPT_PARTIAL, TRANSCRIPT_FINAL,
    QUESTION_DETECTED, ANSWER_GENERATION_STARTED, ANSWER_CHUNK,
    ANSWER_COMPLETED, ERROR, plus QUESTION_CANCELLED.
  * Independent sessions never share transcript/context.

Threading model mirrors the existing /ws/audio handler: a per-session timer
thread handles EOU debouncing; a bounded ThreadPoolExecutor runs generations so
a slow LLM call never blocks ingestion. All emits go through a user-supplied
callback (the transport decides how to deliver them).
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("interview.session")


# ── Event types ───────────────────────────────────────────────────────────────

EVT_TRANSCRIPT_PARTIAL = "TRANSCRIPT_PARTIAL"
EVT_TRANSCRIPT_FINAL = "TRANSCRIPT_FINAL"
EVT_QUESTION_DETECTED = "QUESTION_DETECTED"
EVT_ANSWER_STARTED = "ANSWER_GENERATION_STARTED"
EVT_ANSWER_CHUNK = "ANSWER_CHUNK"
EVT_ANSWER_COMPLETED = "ANSWER_COMPLETED"
EVT_QUESTION_CANCELLED = "QUESTION_CANCELLED"
EVT_ERROR = "ERROR"


def _normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, drop trailing punctuation for dedup."""
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return norm.rstrip(" .?!,:;")


def _now() -> float:
    return time.time()


class Question:
    """A detected question and the lifecycle of its answer generation."""

    def __init__(self, qid: str, text: str, category: str, confidence: float):
        self.id = qid
        self.text = text
        self.category = category
        self.confidence = confidence
        self.created_at = _now()
        self.status = "detected"   # detected -> generating -> completed/error/cancelled
        self.answer = ""
        self.cancelled = threading.Event()

    def to_dict(self) -> dict:
        return {
            "question_id": self.id,
            "text": self.text,
            "category": self.category,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at,
        }


class InterviewSession:
    """
    One interview session. Owns its transcript, dedup state, and in-flight
    generations. Thread-safe for concurrent ingest + generation.

    emit(event_dict) is called for every event; it must be non-blocking and
    tolerate being called from worker threads (the transport should queue/send
    safely, like the existing safe_send in /ws/audio).
    """

    def __init__(self, session_id, config, detector, ai_module, emit,
                 executor: ThreadPoolExecutor, candidate_profile: str | None = None,
                 db_module=None, clock=_now, language: str | None = None):
        self.id = session_id
        self.config = config
        self.detector = detector
        self.ai = ai_module
        self.emit = emit
        self.executor = executor
        self.candidate_profile = candidate_profile
        self.db = db_module
        self._clock = clock

        # Resolve the session language once. If the frontend did not provide one
        # (or provided an unsupported value), fall back to the configured
        # default (English). We never auto-switch mid-session on a stray phrase.
        self.language = self._resolve_language(language)
        self.speech_locale = self._resolve_speech_locale()

        self._lock = threading.RLock()
        self.turns: "deque[dict]" = deque(maxlen=max(1, config.maxHistoryTurns))

        # Pending (not-yet-finalized) utterance accumulation.
        self._pending_text = ""
        self._pending_deadline = 0.0   # EOU deadline (0 => not armed)
        self._pending_final = False

        # De-duplication of EMITTED transcript events. Many STT engines stream
        # growing/cumulative results, which otherwise show the same line over
        # and over on the client. We suppress re-emitting a transcript whose
        # normalized text we just sent.
        self._last_partial_norm = ""
        self._last_final_norm = ""

        # Grace window used when a final segment already looks complete: short,
        # just enough to coalesce an immediate trailing final, but far below the
        # full EOU window so answers start quickly. Bounded by the EOU window.
        self._complete_grace_s = min(self.config.end_of_utterance_s, 0.15)

        # Dedup: normalized question text -> last-emitted timestamp.
        self._recent_questions: "dict[str, float]" = {}

        # The question currently awaiting / undergoing generation.
        self._active_question: Question | None = None
        self._closed = False

        # EOU debounce timer thread.
        self._timer = threading.Thread(target=self._eou_loop, daemon=True)
        self._timer.start()

    # ── Language resolution ──────────────────────────────────────────────────

    def _resolve_language(self, language: str | None) -> str:
        """Normalize the requested language, else fall back to config default."""
        default = getattr(self.config, "language", None) or getattr(
            self.config, "defaultLanguage", "en"
        )
        try:
            import interview_config as _ic
            return _ic.normalize_language(language, fallback=_ic.normalize_language(default))
        except Exception:  # noqa: BLE001 — stay usable without the config module
            if language and str(language).strip():
                return str(language).strip().lower().split("-")[0]
            return (default or "en").lower().split("-")[0]

    def _resolve_speech_locale(self) -> str:
        try:
            import interview_config as _ic
            return _ic.speech_locale_for(self.language)
        except Exception:  # noqa: BLE001
            return getattr(self.config, "defaultSpeechLocale", "en-IN")

    # ── Public API ─────────────────────────────────────────────────────────

    def add_transcript(self, text: str, is_final: bool, speaker: str = "them",
                       timestamp: float | None = None) -> None:
        """
        Ingest a transcript segment. Partial segments update the pending buffer
        and emit TRANSCRIPT_PARTIAL. A final segment emits TRANSCRIPT_FINAL and
        arms the EOU window; actual question detection happens when the window
        elapses (so trailing words can still merge).
        """
        text = (text or "").strip()
        if self._closed:
            return
        ts = timestamp if timestamp is not None else self._clock()

        with self._lock:
            if not is_final:
                if not text:
                    return
                # Partial: treat as the current best guess of the utterance.
                self._pending_text = text
                norm = _normalize_text(text)
                # Suppress re-emitting an identical partial (growing STT streams
                # often repeat the same text), which would double it on the UI.
                if norm and norm != self._last_partial_norm:
                    self._last_partial_norm = norm
                    self._emit(EVT_TRANSCRIPT_PARTIAL,
                               {"text": text, "speaker": speaker, "ts": ts})
                return

            # Final segment: merge with any pending text from the same utterance.
            merged = self._merge_final(text)
            self._pending_text = merged
            self._pending_final = True
            merged_norm = _normalize_text(merged)

            # Choose the EOU window adaptively. A final segment that already
            # looks like a complete sentence/question only needs a short grace
            # window to catch stray trailing finals; this removes most of the
            # perceived answer lag. An open-ended final keeps the full window so
            # late words can still merge.
            window = self.config.end_of_utterance_s
            if self._looks_complete(merged):
                window = min(window, self._complete_grace_s)
            # Arm / re-arm the EOU window (debounce). A later final re-arms it,
            # letting consecutive finals of one question coalesce.
            self._pending_deadline = ts + window

            # Suppress a duplicate TRANSCRIPT_FINAL for text we already emitted
            # as final (repeated finals of the same utterance).
            if merged_norm and merged_norm != self._last_final_norm:
                self._last_final_norm = merged_norm
                # A new final supersedes the last partial line on the client.
                self._last_partial_norm = merged_norm
                self._emit(EVT_TRANSCRIPT_FINAL,
                           {"text": merged, "speaker": speaker, "ts": ts})

    def cancel_active(self, reason: str = "cancelled") -> bool:
        """Cancel the active question's generation if any. Returns True if one
        was cancelled."""
        with self._lock:
            q = self._active_question
            if q is None or q.status in ("completed", "error", "cancelled"):
                return False
            q.cancelled.set()
            q.status = "cancelled"
            self._emit(EVT_QUESTION_CANCELLED,
                       {"question_id": q.id, "reason": reason})
            return True

    def history(self) -> list[dict]:
        with self._lock:
            return list(self.turns)

    def close(self) -> None:
        """Stop the timer thread and cancel any in-flight work."""
        with self._lock:
            self._closed = True
            if self._active_question and self._active_question.status in (
                "detected", "generating"
            ):
                self._active_question.cancelled.set()
                self._active_question.status = "cancelled"

    # ── EOU finalization loop ───────────────────────────────────────────────

    def _eou_loop(self) -> None:
        # Poll fast enough to honor the short "complete" grace window, but no
        # finer than needed. The deadline is the real decision, not a fixed
        # tick — late finals push the deadline out.
        tick = max(0.03, min(self._complete_grace_s, self.config.end_of_utterance_s / 4))
        while not self._closed:
            time.sleep(tick)
            fire = False
            with self._lock:
                if (self._pending_final and self._pending_deadline
                        and self._clock() >= self._pending_deadline):
                    fire = True
                    self._pending_deadline = 0.0
                    self._pending_final = False
                    candidate = self._pending_text
                    self._pending_text = ""
                    # New utterance starts fresh: allow its transcript events to
                    # emit even if they repeat earlier text.
                    self._last_partial_norm = ""
                    self._last_final_norm = ""
            if fire:
                try:
                    self._finalize_utterance(candidate)
                except Exception as exc:  # noqa: BLE001 — never kill the loop
                    log.exception("finalize failed: %s", exc)
                    self._emit(EVT_ERROR,
                               {"error": f"finalize failed: {exc}", "recoverable": True})

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _looks_complete(text: str) -> bool:
        """True when a final segment reads like a finished utterance (ends with
        terminal punctuation), so we can finalize on a short grace window."""
        stripped = (text or "").strip()
        return bool(stripped) and stripped.endswith(("?", ".", "!"))

    def _merge_final(self, text: str) -> str:
        """Merge a new final segment with pending text, avoiding duplication."""
        prev = (self._pending_text or "").strip()
        if not prev:
            return text
        if not text:
            return prev
        # If the new text already contains the previous (STT re-emits growing
        # transcripts), keep the longer. Otherwise concatenate.
        if _normalize_text(text).startswith(_normalize_text(prev)):
            return text
        if _normalize_text(prev).startswith(_normalize_text(text)):
            return prev
        return (prev + " " + text).strip()

    def _finalize_utterance(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Always record the turn into bounded history (context for follow-ups).
        with self._lock:
            self.turns.append({"speaker": "them", "text": text, "ts": self._clock()})

        result = self.detector.detect(text)
        if not (result.is_question
                and result.confidence >= self.config.detectionConfidenceThreshold):
            log.debug("not a question (conf=%.2f): %r", result.confidence, text)
            return

        norm = _normalize_text(text)
        now = self._clock()
        with self._lock:
            # Dedup within the configured window.
            self._prune_recent(now)
            last = self._recent_questions.get(norm)
            if last is not None and (now - last) <= self.config.duplicateWindowS:
                log.debug("duplicate question suppressed: %r", text)
                return
            self._recent_questions[norm] = now

            # Replace any still-pending (not yet generating) active question.
            if self._active_question and self._active_question.status == "detected":
                self._active_question.cancelled.set()
                self._active_question.status = "cancelled"
                self._emit(EVT_QUESTION_CANCELLED,
                           {"question_id": self._active_question.id,
                            "reason": "replaced by newer question"})

            qid = uuid.uuid4().hex
            question = Question(qid, text, result.category, result.confidence)
            self._active_question = question

        self._emit(EVT_QUESTION_DETECTED, {
            **question.to_dict(),
            "detection_source": result.source,
            "reason": result.reason,
        })

        # Hand off to the bounded pool so ingestion is never blocked.
        try:
            self.executor.submit(self._generate, question)
        except RuntimeError as exc:
            # Executor shutting down.
            self._emit(EVT_ERROR, {"question_id": question.id,
                                   "error": f"could not schedule generation: {exc}",
                                   "recoverable": False})

    def _prune_recent(self, now: float) -> None:
        window = self.config.duplicateWindowS
        stale = [k for k, t in self._recent_questions.items() if now - t > window]
        for k in stale:
            self._recent_questions.pop(k, None)

    def _build_context(self, exclude_text: str) -> str:
        """Recent dialogue (excluding the current question) for follow-ups."""
        with self._lock:
            turns = list(self.turns)
        lines = []
        for t in turns:
            if t["text"].strip() == exclude_text.strip():
                continue
            label = "Me" if t["speaker"] == "me" else "Interviewer"
            lines.append(f"{label}: {t['text']}")
        return "\n".join(lines)

    def _generate(self, question: Question) -> None:
        """Run (streamed if enabled) answer generation for one question."""
        if question.cancelled.is_set():
            return
        with self._lock:
            # Guard: at-most-one active generation; if replaced, bail.
            if self._active_question is not question:
                return
            question.status = "generating"

        self._emit(EVT_ANSWER_STARTED, {"question_id": question.id,
                                        "category": question.category})

        if self.ai is None or not getattr(self.ai, "is_configured", lambda: False)():
            self._emit(EVT_ERROR, {
                "question_id": question.id,
                "error": "AI not configured (set OPENAI_API_KEY).",
                "recoverable": False,
            })
            question.status = "error"
            return

        context = self._build_context(question.text)
        model = self.config.chatModel
        temperature = self.config.temperature

        # Run generation with a timeout guard. We execute the (blocking) call in
        # this worker; a watchdog sets the cancel flag past the deadline so
        # streaming stops and we emit a recoverable timeout.
        deadline = self._clock() + self.config.answerTimeoutS

        try:
            if self.config.streaming and hasattr(self.ai, "answer_interview_question_stream"):
                collected = []
                for piece in self.ai.answer_interview_question_stream(
                    question.text, category=question.category, context=context,
                    candidate_profile=self.candidate_profile,
                    model=model, temperature=temperature, language=self.language,
                ):
                    if question.cancelled.is_set():
                        return
                    if self._clock() > deadline:
                        raise TimeoutError(
                            f"answer timed out after {self.config.answerTimeoutS}s")
                    collected.append(piece)
                    self._emit(EVT_ANSWER_CHUNK,
                               {"question_id": question.id, "text": piece})
                answer = "".join(collected).strip()
            else:
                answer = self.ai.answer_interview_question(
                    question.text, category=question.category, context=context,
                    candidate_profile=self.candidate_profile,
                    model=model, temperature=temperature, language=self.language,
                )
                if question.cancelled.is_set():
                    return
        except TimeoutError as exc:
            question.status = "error"
            self._emit(EVT_ERROR, {"question_id": question.id,
                                   "error": str(exc), "recoverable": True})
            return
        except Exception as exc:  # noqa: BLE001 — AIError or anything else
            question.status = "error"
            self._emit(EVT_ERROR, {"question_id": question.id,
                                   "error": str(exc), "recoverable": True})
            return

        if question.cancelled.is_set():
            return

        question.answer = answer
        question.status = "completed"
        self._persist(question)
        self._emit(EVT_ANSWER_COMPLETED, {
            "question_id": question.id,
            "answer": answer,
            "category": question.category,
            "confidence": question.confidence,
        })

    def _persist(self, question: Question) -> None:
        """Best-effort: store the Q/A as a record (reuses db.py)."""
        if self.db is None:
            return
        try:
            rec = self.db.create_record(
                source_type="audio",
                input_ref=f"interview:{self.id}",
                extracted_text=question.text,
                answer=question.answer,
                status="answered",
            )
            self.db.add_history(rec["id"], question.text, question.answer)
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            log.debug("persist failed: %s", exc)

    # ── Emit wrapper (adds envelope) ─────────────────────────────────────────

    def _emit(self, event_type: str, data: dict) -> None:
        envelope = {
            "type": event_type,
            "session_id": self.id,
            "ts": self._clock(),
            **data,
        }
        try:
            self.emit(envelope)
        except Exception as exc:  # noqa: BLE001 — transport must never crash us
            log.debug("emit failed (%s): %s", event_type, exc)


class SessionManager:
    """
    Owns all live sessions and the shared, bounded generation thread pool.
    Independent sessions never share transcript/context.
    """

    def __init__(self, config, detector, ai_module, db_module=None):
        self.config = config
        self.detector = detector
        self.ai = ai_module
        self.db = db_module
        self._sessions: "dict[str, InterviewSession]" = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, config.maxConcurrentGenerations),
            thread_name_prefix="interview-gen",
        )

    def start_session(self, emit, session_id: str | None = None,
                      candidate_profile: str | None = None,
                      language: str | None = None) -> InterviewSession:
        sid = session_id or uuid.uuid4().hex
        with self._lock:
            existing = self._sessions.get(sid)
            if existing is not None and not existing._closed:
                return existing
            session = InterviewSession(
                sid, self.config, self.detector, self.ai, emit,
                self._executor, candidate_profile=candidate_profile,
                db_module=self.db, language=language,
            )
            self._sessions[sid] = session
            return session

    def get(self, session_id: str) -> InterviewSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def stop_session(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.close()
        return True

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.close()
        self._executor.shutdown(wait=False)
