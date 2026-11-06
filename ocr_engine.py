#!/usr/bin/env python3
"""
ocr_engine.py — unified OCR text extraction
============================================
Provides a single `extract_text(image_path, engine=...)` entry point so the
rest of the backend doesn't care which OCR engine is used.

Engines:
  - "easyocr"  : baseline. Fast to call; the server already loads an
                 easyocr.Reader at startup, which we reuse via set_easyocr_reader().
                 Runs IN-PROCESS (verified not to crash on large images).
  - "paddle"   : OCR.py's SmartQuestionOCR (PaddleOCR). Preferred for
                 question/option content (memory.md default).

Crash-safety notes
------------------
PaddleOCR can **segfault** (a native crash) on large images. A segfault kills
the whole Python process and CANNOT be caught by try/except. To keep the Flask
server alive we run PaddleOCR in a SHORT-LIVED SUBPROCESS: if that child
segfaults, times out, exits non-zero, or prints garbage, the parent survives,
logs a warning, and falls back to easyocr (in-process). Only if BOTH engines
fail do we raise OCRError, which the routes already turn into a clean JSON
error instead of a dead server.

Two layers of defense:
  1. Downscale oversized images with PIL LANCZOS before OCR (reduces — but does
     NOT eliminate — native crashes, and speeds things up).
  2. Isolate PaddleOCR in a subprocess so a crash is survivable.

Default engine comes from env OCR_ENGINE (default "paddle" per memory.md), but
callers can override per-request.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

DEFAULT_ENGINE = os.environ.get("OCR_ENGINE", "paddle").lower()

# Longest-side cap for the first-line downscale defense. Oversized images are
# resized (aspect preserved) before OCR. Env-overridable via OCR_MAX_SIDE.
try:
    OCR_MAX_SIDE = int(os.environ.get("OCR_MAX_SIDE", "2600"))
except (TypeError, ValueError):
    OCR_MAX_SIDE = 2600

# Generous wall-clock budget for the Paddle subprocess (model load + inference).
try:
    OCR_PADDLE_TIMEOUT = int(os.environ.get("OCR_PADDLE_TIMEOUT", "120"))
except (TypeError, ValueError):
    OCR_PADDLE_TIMEOUT = 120


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


# ── Downscaling (first-line defense against native crashes) ───────────────────

def _maybe_downscale(image_path: str):
    """
    If the image's longest side exceeds OCR_MAX_SIDE, write a LANCZOS-downscaled
    copy to a temp file (aspect preserved) and return (temp_path, True).
    Otherwise return (image_path, False). The caller must delete temp_path when
    the second value is True.
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            longest = max(width, height)
            if longest <= OCR_MAX_SIDE:
                return image_path, False

            scale = OCR_MAX_SIDE / float(longest)
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            resized = img.convert("RGB").resize(new_size, Image.LANCZOS)

            fd, tmp_path = tempfile.mkstemp(prefix="ocr_scaled_", suffix=".png")
            os.close(fd)
            resized.save(tmp_path, format="PNG")
            log.info(
                "Downscaled oversized image %sx%s -> %sx%s for OCR",
                width, height, new_size[0], new_size[1],
            )
            return tmp_path, True
    except Exception as exc:  # noqa: BLE001
        # Downscaling is best-effort; if it fails, OCR the original.
        log.warning("Downscale failed (%s); using original image", exc)
        return image_path, False


# ── PaddleOCR / SmartQuestionOCR (isolated in a subprocess) ───────────────────

# Worker run via `sys.executable -c`. It imports OCR.SmartQuestionOCR, processes
# the given image, and prints the extracted text as JSON to stdout. It applies
# the SAME "prefer detected questions, else raw text" logic that _extract_paddle
# used to apply in-process, so output is identical for images that succeed.
#
# NOTE: each call loads PaddleOCR models fresh in the child process — Paddle
# can't be shared across processes, so we accept the per-call model-load cost
# (OCR.py already lazy-loads today). Crash isolation is worth it.
_PADDLE_WORKER = r"""
import json, sys
from OCR import SmartQuestionOCR

image_path = sys.argv[1]
smart = SmartQuestionOCR()
result = smart.process_image(image_path)

questions = result.get("possible_questions") or []
if questions:
    text = "\n".join(
        q.get("possible_question", "").strip()
        for q in questions
        if q.get("possible_question")
    ).strip()
else:
    raw = result.get("raw_items") or []
    text = "\n".join(
        item.get("text", "").strip() for item in raw if item.get("text")
    ).strip()

sys.stdout.write("\n__OCR_RESULT__" + json.dumps({"text": text}))
"""


def _extract_paddle_subprocess(image_path: str) -> str:
    """
    Run PaddleOCR in a short-lived child process so a native crash (segfault)
    can't kill the server. Returns the extracted text on success.

    Raises OCRError if the child crashes (negative return code / signal), exits
    non-zero, times out, or prints unparseable output — the caller catches this
    and falls through to the easyocr fallback.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PADDLE_WORKER, image_path],
            capture_output=True,
            text=True,
            timeout=OCR_PADDLE_TIMEOUT,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except subprocess.TimeoutExpired:
        raise OCRError(f"PaddleOCR subprocess timed out after {OCR_PADDLE_TIMEOUT}s")
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"PaddleOCR subprocess failed to launch: {exc}")

    # Negative return code => killed by a signal (e.g. -11 == SIGSEGV).
    if proc.returncode < 0:
        raise OCRError(
            f"PaddleOCR subprocess crashed (signal {-proc.returncode}); "
            "likely a native segfault on this image"
        )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        raise OCRError(f"PaddleOCR subprocess exited {proc.returncode}: {tail[0]}")

    # The worker prints lots of model logs; our result is the last marked line.
    marker = "__OCR_RESULT__"
    idx = proc.stdout.rfind(marker)
    if idx == -1:
        raise OCRError("PaddleOCR subprocess produced no parseable result")
    try:
        payload = json.loads(proc.stdout[idx + len(marker):])
        return str(payload.get("text", "")).strip()
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OCRError(f"PaddleOCR subprocess output unparseable: {exc}")


# ── Public API ────────────────────────────────────────────────────────────────

def extract_text(image_path: str, engine: str | None = None) -> str:
    """
    Extract text from an image file using the chosen engine.

    engine: "easyocr" | "paddle" (defaults to DEFAULT_ENGINE).

    Crash-safe: oversized images are downscaled first, PaddleOCR runs in an
    isolated subprocess, and easyocr is used as an automatic fallback. Never
    crashes the host process; raises OCRError only if every attempt fails.
    """
    if not image_path or not os.path.exists(image_path):
        raise OCRError(f"Image not found: {image_path}")

    chosen = (engine or DEFAULT_ENGINE).lower()

    # Layer 1: downscale oversized images (aspect preserved) to a temp file.
    ocr_path, is_temp = _maybe_downscale(image_path)
    try:
        # Explicit easyocr request: skip paddle entirely.
        if chosen in ("easyocr", "easy"):
            return _extract_easyocr(ocr_path)

        if chosen in ("paddle", "paddleocr", "smart"):
            # Layer 2: isolate Paddle in a subprocess; fall back to easyocr on
            # ANY failure (crash / timeout / non-zero / unparseable).
            try:
                return _extract_paddle_subprocess(ocr_path)
            except OCRError as paddle_exc:
                log.warning(
                    "PaddleOCR failed (%s); falling back to easyocr", paddle_exc
                )
                try:
                    return _extract_easyocr(ocr_path)
                except OCRError as easy_exc:
                    raise OCRError(
                        "OCR failed for this image (both engines). "
                        "Try a smaller/clearer crop. "
                        f"[paddle: {paddle_exc}] [easyocr: {easy_exc}]"
                    )

        raise OCRError(f"Unknown OCR engine: {chosen}")
    finally:
        # Always clean up the downscaled temp file, even on error.
        if is_temp:
            try:
                os.remove(ocr_path)
            except OSError:
                pass
