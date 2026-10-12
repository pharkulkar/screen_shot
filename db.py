#!/usr/bin/env python3
"""
db.py — SQLite data layer (records + answer caching)
====================================================
Portable, zero-install datastore (Python stdlib `sqlite3`). Holds one row per
"answer" record — whether from a screenshot or from audio — enabling the
caching behavior (Feature C): once a record has an answer, revisiting it is a
cache hit with no OCR and no OpenAI call.

Storage split (requirements.md DS-2):
  - SQLite holds metadata + text (small).
  - The actual screenshot PNGs stay on disk; the DB references them by path.

Record model (requirements.md §11a):
  id, created_at, source_type, input_ref, extracted_text, answer, status

  source_type : 'screenshot-full' | 'screenshot-region' | 'audio'
  status      : 'captured' | 'processing' | 'answered' | 'error'
"""

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# DB file location. Dev: project folder. Packaged build overrides via env
# (set to the per-user app-data dir — requirements.md DS-4).
DB_PATH = Path(os.environ.get("APP_DB_PATH", ROOT / "app.db"))

# Valid enum values (kept in Python; SQLite itself is untyped here).
# 'manual' = a typed question with no screenshot/audio source.
SOURCE_TYPES = {"screenshot-full", "screenshot-region", "audio", "manual"}
STATUSES = {"captured", "processing", "answered", "error"}

# One connection guarded by a lock. SQLite serializes writes anyway; for a
# single-user local app this is simple and safe. WAL keeps reads smooth.
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


# ── Connection / schema ───────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,   # guarded by _lock
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")   # smooth concurrent reads (DS-3)
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _conn = conn
    return conn


def init_db() -> None:
    """Create the schema if it doesn't exist. Safe to call repeatedly."""
    with _lock:
        conn = _connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id             TEXT PRIMARY KEY,
                created_at     REAL NOT NULL,
                source_type    TEXT NOT NULL,
                input_ref      TEXT,
                extracted_text TEXT,
                answer         TEXT,
                status         TEXT NOT NULL DEFAULT 'captured'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_records_created ON records(created_at)"
        )
        # Answer history: every Ask on a record appends a (question, answer) row.
        # The record's own `answer` column always holds the LATEST answer; this
        # table keeps the full history for review.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS answer_history (
                id         TEXT PRIMARY KEY,
                record_id  TEXT NOT NULL,
                question   TEXT,
                answer     TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_record ON answer_history(record_id, created_at)"
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


# ── Create / update ───────────────────────────────────────────────────────────

def create_record(
    source_type: str,
    input_ref: str | None = None,
    extracted_text: str | None = None,
    answer: str | None = None,
    status: str = "captured",
    record_id: str | None = None,
) -> dict:
    """Insert a new record and return it. Generates a UUID id if none given."""
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Invalid source_type: {source_type}")
    if status not in STATUSES:
        raise ValueError(f"Invalid status: {status}")

    rec_id = record_id or uuid.uuid4().hex
    created = time.time()

    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO records
                (id, created_at, source_type, input_ref, extracted_text, answer, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rec_id, created, source_type, input_ref, extracted_text, answer, status),
        )
        conn.commit()

    return get_record(rec_id)


def update_record(record_id: str, **fields) -> dict | None:
    """Update allowed columns on a record; returns the updated row (or None)."""
    allowed = {"input_ref", "extracted_text", "answer", "status"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_record(record_id)

    if "status" in sets and sets["status"] not in STATUSES:
        raise ValueError(f"Invalid status: {sets['status']}")

    cols = ", ".join(f"{k} = ?" for k in sets)
    values = list(sets.values()) + [record_id]

    with _lock:
        conn = _connect()
        conn.execute(f"UPDATE records SET {cols} WHERE id = ?", values)
        conn.commit()

    return get_record(record_id)


# ── Read ──────────────────────────────────────────────────────────────────────

def get_record(record_id: str) -> dict | None:
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


# ── Answer history ─────────────────────────────────────────────────────────────

def add_history(record_id: str, question: str, answer: str) -> dict:
    """Append a (question, answer) pair to a record's history."""
    entry = {
        "id": uuid.uuid4().hex,
        "record_id": record_id,
        "question": question or "",
        "answer": answer or "",
        "created_at": time.time(),
    }
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO answer_history (id, record_id, question, answer, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (entry["id"], entry["record_id"], entry["question"], entry["answer"], entry["created_at"]),
        )
        conn.commit()
    return entry


def get_history(record_id: str) -> list[dict]:
    """Return a record's history, NEWEST first (latest answer first)."""
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM answer_history WHERE record_id = ? ORDER BY created_at DESC",
            (record_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_records(limit: int = 500, offset: int = 0) -> list[dict]:
    """Newest first. (Grouping by day is done in the API/UI layer.)"""
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM records ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def has_answer(record_id: str) -> bool:
    """Cache check: True if the record already has a stored answer."""
    rec = get_record(record_id)
    return bool(rec and rec.get("status") == "answered" and rec.get("answer"))


# ── Delete / retention ────────────────────────────────────────────────────────

def delete_record(record_id: str) -> bool:
    """Delete a record. Returns True if a row was removed.

    NOTE: the on-disk image (input_ref) is NOT deleted here — the caller
    decides, since images may be shared across versions.
    """
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        conn.execute("DELETE FROM answer_history WHERE record_id = ?", (record_id,))
        conn.commit()
        return cur.rowcount > 0


def delete_older_than(days: float) -> int:
    """Retention policy (DS-8): delete records older than `days`. Returns count."""
    cutoff = time.time() - days * 86400
    with _lock:
        conn = _connect()
        # Remove history for the records being deleted, then the records.
        conn.execute(
            "DELETE FROM answer_history WHERE record_id IN "
            "(SELECT id FROM records WHERE created_at < ?)",
            (cutoff,),
        )
        cur = conn.execute("DELETE FROM records WHERE created_at < ?", (cutoff,))
        conn.commit()
        return cur.rowcount


def clear_all() -> int:
    """Manual 'clear history' (DS-8). Returns number of records removed."""
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM answer_history")
        cur = conn.execute("DELETE FROM records")
        conn.commit()
        return cur.rowcount
