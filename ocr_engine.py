#!/usr/bin/env python3
"""
ocr_engine.py — unified OCR text extraction
============================================
Provides a single `extract_text(image_path, engine=...)` entry point so the
rest of the backend doesn't care which OCR engine is used.

Engines:
  - "easyocr"  : baseline. Fast to call; the server already loads an
                 easyocr.Reader at startup, which we reuse via set_easyocr_reader().
  - "paddle"   : OCR.py's SmartQuestionOCR (PaddleOCR). Preferred for
                 question/option content (memory.md default). Loaded lazily on
                 first use because the PaddleOCR models are heavy.

Default engine comes from env OCR_ENGINE (default "paddle" per memory.md), but
callers can override per-request.
"""

import os

import numpy as np
from PIL import Image

DEFAULT_ENGINE = os.environ.get("OCR_ENGINE", "paddle").lower()


class OCRError(Exception):
    """Raised when text extraction fails or an engine is unavailable."""


# ── easyocr (reader injected by the server to avoid double-loading) ───────────

_easyocr_reader = None


def set_easyocr_reader(reader) -> None:
    """Let server.py share its already-initialized easyocr.Reader."""
    global _easyocr_reader
    _easyocr_reader = reader


def _extract_easyocr(image_path: str) -> str:
    if _easyocr_reader is None:
        # Fallback: build one on demand (slow first call).
        try:
            import easyocr
            globals()["_easyocr_reader"] = easyocr.Reader(["en"], gpu=False)
        except Exception as exc:  # noqa: BLE001
            raise OCRError(f"easyocr unavailable: {exc}")

    try:
        with Image.open(image_path) as img:
            img_np = np.array(img.convert("RGB"))
        lines = _easyocr_reader.readtext(img_np, detail=0, paragraph=False)
        return "\n".join(lines).strip()
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"easyocr extraction failed: {exc}")


# ── PaddleOCR / SmartQuestionOCR (lazy, heavy) ────────────────────────────────

_smart_ocr = None


def _get_smart_ocr():
    global _smart_ocr
    if _smart_ocr is None:
        try:
            from OCR import SmartQuestionOCR
            _smart_ocr = SmartQuestionOCR()
        except Exception as exc:  # noqa: BLE001
            raise OCRError(f"PaddleOCR/SmartQuestionOCR unavailable: {exc}")
    return _smart_ocr


def _extract_paddle(image_path: str) -> str:
    """
    Use SmartQuestionOCR. Prefer its detected questions (clean, question-focused
    text ideal for the OpenAI prompt); fall back to raw OCR lines if none found.
    """
    smart = _get_smart_ocr()
    try:
        result = smart.process_image(image_path)
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"PaddleOCR extraction failed: {exc}")

    questions = result.get("possible_questions") or []
    if questions:
        return "\n".join(
            q.get("possible_question", "").strip()
            for q in questions
            if q.get("possible_question")
        ).strip()

    # No structured questions — fall back to raw recognized text.
    raw = result.get("raw_items") or []
    return "\n".join(
        item.get("text", "").strip() for item in raw if item.get("text")
    ).strip()


# ── Public API ────────────────────────────────────────────────────────────────

def extract_text(image_path: str, engine: str | None = None) -> str:
    """
    Extract text from an image file using the chosen engine.

    engine: "easyocr" | "paddle" (defaults to DEFAULT_ENGINE).
    Raises OCRError on failure.
    """
    if not image_path or not os.path.exists(image_path):
        raise OCRError(f"Image not found: {image_path}")

    chosen = (engine or DEFAULT_ENGINE).lower()
    if chosen in ("paddle", "paddleocr", "smart"):
        return _extract_paddle(image_path)
    if chosen in ("easyocr", "easy"):
        return _extract_easyocr(image_path)
    raise OCRError(f"Unknown OCR engine: {chosen}")
