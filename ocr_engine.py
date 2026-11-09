# [OCR-FILE-DISABLED] Entire file commented out (local OCR removed; app is vision-only).
# [OCR-FILE-DISABLED] Restore: sed -i '' 's/^# \[OCR-DISABLED\] //' ocr_engine.py  (then delete these 3 header lines)
# [OCR-FILE-DISABLED] Blank lines were left as-is; every other line is prefixed with '# [OCR-DISABLED] '.
# [OCR-DISABLED] #!/usr/bin/env python3
# [OCR-DISABLED] """
# [OCR-DISABLED] ocr_engine.py — unified OCR text extraction
# [OCR-DISABLED] ============================================
# [OCR-DISABLED] Provides a single `extract_text(image_path, engine=...)` entry point so the
# [OCR-DISABLED] rest of the backend doesn't care which OCR engine is used.

# [OCR-DISABLED] Engines:
# [OCR-DISABLED]   - "easyocr"  : baseline. Fast to call; the server already loads an
# [OCR-DISABLED]                  easyocr.Reader at startup, which we reuse via set_easyocr_reader().
# [OCR-DISABLED]                  Runs IN-PROCESS (verified not to crash on large images).
# [OCR-DISABLED]   - "paddle"   : OCR.py's SmartQuestionOCR (PaddleOCR). Preferred for
# [OCR-DISABLED]                  question/option content (memory.md default).

# [OCR-DISABLED] Crash-safety notes
# [OCR-DISABLED] ------------------
# [OCR-DISABLED] PaddleOCR can **segfault** (a native crash) on large images. A segfault kills
# [OCR-DISABLED] the whole Python process and CANNOT be caught by try/except. To keep the Flask
# [OCR-DISABLED] server alive we run PaddleOCR in a SHORT-LIVED SUBPROCESS: if that child
# [OCR-DISABLED] segfaults, times out, exits non-zero, or prints garbage, the parent survives,
# [OCR-DISABLED] logs a warning, and falls back to easyocr (in-process). Only if BOTH engines
# [OCR-DISABLED] fail do we raise OCRError, which the routes already turn into a clean JSON
# [OCR-DISABLED] error instead of a dead server.

# [OCR-DISABLED] Two layers of defense:
# [OCR-DISABLED]   1. Downscale oversized images with PIL LANCZOS before OCR (reduces — but does
# [OCR-DISABLED]      NOT eliminate — native crashes, and speeds things up).
# [OCR-DISABLED]   2. Isolate PaddleOCR in a subprocess so a crash is survivable.

# [OCR-DISABLED] Default engine comes from env OCR_ENGINE (default "paddle" per memory.md), but
# [OCR-DISABLED] callers can override per-request.
# [OCR-DISABLED] """

# [OCR-DISABLED] import json
# [OCR-DISABLED] import logging
# [OCR-DISABLED] import os
# [OCR-DISABLED] import subprocess
# [OCR-DISABLED] import sys
# [OCR-DISABLED] import tempfile

# [OCR-DISABLED] import numpy as np
# [OCR-DISABLED] from PIL import Image

# [OCR-DISABLED] log = logging.getLogger(__name__)

# [OCR-DISABLED] DEFAULT_ENGINE = os.environ.get("OCR_ENGINE", "paddle").lower()

# [OCR-DISABLED] # Longest-side cap for the first-line downscale defense. Oversized images are
# [OCR-DISABLED] # resized (aspect preserved) before OCR. Env-overridable via OCR_MAX_SIDE.
# [OCR-DISABLED] try:
# [OCR-DISABLED]     OCR_MAX_SIDE = int(os.environ.get("OCR_MAX_SIDE", "2600"))
# [OCR-DISABLED] except (TypeError, ValueError):
# [OCR-DISABLED]     OCR_MAX_SIDE = 2600

# [OCR-DISABLED] # Generous wall-clock budget for the Paddle subprocess (model load + inference).
# [OCR-DISABLED] try:
# [OCR-DISABLED]     OCR_PADDLE_TIMEOUT = int(os.environ.get("OCR_PADDLE_TIMEOUT", "120"))
# [OCR-DISABLED] except (TypeError, ValueError):
# [OCR-DISABLED]     OCR_PADDLE_TIMEOUT = 120


# [OCR-DISABLED] class OCRError(Exception):
# [OCR-DISABLED]     """Raised when text extraction fails or an engine is unavailable."""


# [OCR-DISABLED] # ── easyocr (reader injected by the server to avoid double-loading) ───────────

# [OCR-DISABLED] _easyocr_reader = None


# [OCR-DISABLED] def set_easyocr_reader(reader) -> None:
# [OCR-DISABLED]     """Let server.py share its already-initialized easyocr.Reader."""
# [OCR-DISABLED]     global _easyocr_reader
# [OCR-DISABLED]     _easyocr_reader = reader


# [OCR-DISABLED] def _extract_easyocr(image_path: str) -> str:
# [OCR-DISABLED]     if _easyocr_reader is None:
# [OCR-DISABLED]         # Fallback: build one on demand (slow first call).
# [OCR-DISABLED]         try:
# [OCR-DISABLED]             import easyocr
# [OCR-DISABLED]             globals()["_easyocr_reader"] = easyocr.Reader(["en"], gpu=False)
# [OCR-DISABLED]         except Exception as exc:  # noqa: BLE001
# [OCR-DISABLED]             raise OCRError(f"easyocr unavailable: {exc}")

# [OCR-DISABLED]     try:
# [OCR-DISABLED]         with Image.open(image_path) as img:
# [OCR-DISABLED]             img_np = np.array(img.convert("RGB"))
# [OCR-DISABLED]         lines = _easyocr_reader.readtext(img_np, detail=0, paragraph=False)
# [OCR-DISABLED]         return "\n".join(lines).strip()
# [OCR-DISABLED]     except Exception as exc:  # noqa: BLE001
# [OCR-DISABLED]         raise OCRError(f"easyocr extraction failed: {exc}")


# [OCR-DISABLED] # ── Downscaling (first-line defense against native crashes) ───────────────────

# [OCR-DISABLED] def _maybe_downscale(image_path: str):
# [OCR-DISABLED]     """
# [OCR-DISABLED]     If the image's longest side exceeds OCR_MAX_SIDE, write a LANCZOS-downscaled
# [OCR-DISABLED]     copy to a temp file (aspect preserved) and return (temp_path, True).
# [OCR-DISABLED]     Otherwise return (image_path, False). The caller must delete temp_path when
# [OCR-DISABLED]     the second value is True.
# [OCR-DISABLED]     """
# [OCR-DISABLED]     try:
# [OCR-DISABLED]         with Image.open(image_path) as img:
# [OCR-DISABLED]             width, height = img.size
# [OCR-DISABLED]             longest = max(width, height)
# [OCR-DISABLED]             if longest <= OCR_MAX_SIDE:
# [OCR-DISABLED]                 return image_path, False

# [OCR-DISABLED]             scale = OCR_MAX_SIDE / float(longest)
# [OCR-DISABLED]             new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
# [OCR-DISABLED]             resized = img.convert("RGB").resize(new_size, Image.LANCZOS)

# [OCR-DISABLED]             fd, tmp_path = tempfile.mkstemp(prefix="ocr_scaled_", suffix=".png")
# [OCR-DISABLED]             os.close(fd)
# [OCR-DISABLED]             resized.save(tmp_path, format="PNG")
# [OCR-DISABLED]             log.info(
# [OCR-DISABLED]                 "Downscaled oversized image %sx%s -> %sx%s for OCR",
# [OCR-DISABLED]                 width, height, new_size[0], new_size[1],
# [OCR-DISABLED]             )
# [OCR-DISABLED]             return tmp_path, True
# [OCR-DISABLED]     except Exception as exc:  # noqa: BLE001
# [OCR-DISABLED]         # Downscaling is best-effort; if it fails, OCR the original.
# [OCR-DISABLED]         log.warning("Downscale failed (%s); using original image", exc)
# [OCR-DISABLED]         return image_path, False


# [OCR-DISABLED] # ── PaddleOCR / SmartQuestionOCR (isolated in a subprocess) ───────────────────

# [OCR-DISABLED] # Worker run via `sys.executable -c`. It imports OCR.SmartQuestionOCR, processes
# [OCR-DISABLED] # the given image, and prints the extracted text as JSON to stdout. It applies
# [OCR-DISABLED] # the SAME "prefer detected questions, else raw text" logic that _extract_paddle
# [OCR-DISABLED] # used to apply in-process, so output is identical for images that succeed.
# [OCR-DISABLED] #
# [OCR-DISABLED] # NOTE: each call loads PaddleOCR models fresh in the child process — Paddle
# [OCR-DISABLED] # can't be shared across processes, so we accept the per-call model-load cost
# [OCR-DISABLED] # (OCR.py already lazy-loads today). Crash isolation is worth it.
# [OCR-DISABLED] _PADDLE_WORKER = r"""
# [OCR-DISABLED] import json, sys
# [OCR-DISABLED] from OCR import SmartQuestionOCR

# [OCR-DISABLED] image_path = sys.argv[1]
# [OCR-DISABLED] smart = SmartQuestionOCR()
# [OCR-DISABLED] result = smart.process_image(image_path)

# [OCR-DISABLED] questions = result.get("possible_questions") or []
# [OCR-DISABLED] if questions:
# [OCR-DISABLED]     text = "\n".join(
# [OCR-DISABLED]         q.get("possible_question", "").strip()
# [OCR-DISABLED]         for q in questions
# [OCR-DISABLED]         if q.get("possible_question")
# [OCR-DISABLED]     ).strip()
# [OCR-DISABLED] else:
# [OCR-DISABLED]     raw = result.get("raw_items") or []
# [OCR-DISABLED]     text = "\n".join(
# [OCR-DISABLED]         item.get("text", "").strip() for item in raw if item.get("text")
# [OCR-DISABLED]     ).strip()

# [OCR-DISABLED] sys.stdout.write("\n__OCR_RESULT__" + json.dumps({"text": text}))
# [OCR-DISABLED] """


# [OCR-DISABLED] def _extract_paddle_subprocess(image_path: str) -> str:
# [OCR-DISABLED]     """
# [OCR-DISABLED]     Run PaddleOCR in a short-lived child process so a native crash (segfault)
# [OCR-DISABLED]     can't kill the server. Returns the extracted text on success.

# [OCR-DISABLED]     Raises OCRError if the child crashes (negative return code / signal), exits
# [OCR-DISABLED]     non-zero, times out, or prints unparseable output — the caller catches this
# [OCR-DISABLED]     and falls through to the easyocr fallback.
# [OCR-DISABLED]     """
# [OCR-DISABLED]     try:
# [OCR-DISABLED]         proc = subprocess.run(
# [OCR-DISABLED]             [sys.executable, "-c", _PADDLE_WORKER, image_path],
# [OCR-DISABLED]             capture_output=True,
# [OCR-DISABLED]             text=True,
# [OCR-DISABLED]             timeout=OCR_PADDLE_TIMEOUT,
# [OCR-DISABLED]             cwd=os.path.dirname(os.path.abspath(__file__)),
# [OCR-DISABLED]         )
# [OCR-DISABLED]     except subprocess.TimeoutExpired:
# [OCR-DISABLED]         raise OCRError(f"PaddleOCR subprocess timed out after {OCR_PADDLE_TIMEOUT}s")
# [OCR-DISABLED]     except Exception as exc:  # noqa: BLE001
# [OCR-DISABLED]         raise OCRError(f"PaddleOCR subprocess failed to launch: {exc}")

# [OCR-DISABLED]     # Negative return code => killed by a signal (e.g. -11 == SIGSEGV).
# [OCR-DISABLED]     if proc.returncode < 0:
# [OCR-DISABLED]         raise OCRError(
# [OCR-DISABLED]             f"PaddleOCR subprocess crashed (signal {-proc.returncode}); "
# [OCR-DISABLED]             "likely a native segfault on this image"
# [OCR-DISABLED]         )
# [OCR-DISABLED]     if proc.returncode != 0:
# [OCR-DISABLED]         tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
# [OCR-DISABLED]         raise OCRError(f"PaddleOCR subprocess exited {proc.returncode}: {tail[0]}")

# [OCR-DISABLED]     # The worker prints lots of model logs; our result is the last marked line.
# [OCR-DISABLED]     marker = "__OCR_RESULT__"
# [OCR-DISABLED]     idx = proc.stdout.rfind(marker)
# [OCR-DISABLED]     if idx == -1:
# [OCR-DISABLED]         raise OCRError("PaddleOCR subprocess produced no parseable result")
# [OCR-DISABLED]     try:
# [OCR-DISABLED]         payload = json.loads(proc.stdout[idx + len(marker):])
# [OCR-DISABLED]         return str(payload.get("text", "")).strip()
# [OCR-DISABLED]     except (json.JSONDecodeError, TypeError, ValueError) as exc:
# [OCR-DISABLED]         raise OCRError(f"PaddleOCR subprocess output unparseable: {exc}")


# [OCR-DISABLED] # ── Public API ────────────────────────────────────────────────────────────────

# [OCR-DISABLED] def extract_text(image_path: str, engine: str | None = None) -> str:
# [OCR-DISABLED]     """
# [OCR-DISABLED]     Extract text from an image file using the chosen engine.

# [OCR-DISABLED]     engine: "easyocr" | "paddle" (defaults to DEFAULT_ENGINE).

# [OCR-DISABLED]     Crash-safe: oversized images are downscaled first, PaddleOCR runs in an
# [OCR-DISABLED]     isolated subprocess, and easyocr is used as an automatic fallback. Never
# [OCR-DISABLED]     crashes the host process; raises OCRError only if every attempt fails.
# [OCR-DISABLED]     """
# [OCR-DISABLED]     if not image_path or not os.path.exists(image_path):
# [OCR-DISABLED]         raise OCRError(f"Image not found: {image_path}")

# [OCR-DISABLED]     chosen = (engine or DEFAULT_ENGINE).lower()

# [OCR-DISABLED]     # Layer 1: downscale oversized images (aspect preserved) to a temp file.
# [OCR-DISABLED]     ocr_path, is_temp = _maybe_downscale(image_path)
# [OCR-DISABLED]     try:
# [OCR-DISABLED]         # Explicit easyocr request: skip paddle entirely.
# [OCR-DISABLED]         if chosen in ("easyocr", "easy"):
# [OCR-DISABLED]             return _extract_easyocr(ocr_path)

# [OCR-DISABLED]         if chosen in ("paddle", "paddleocr", "smart"):
# [OCR-DISABLED]             # Layer 2: isolate Paddle in a subprocess; fall back to easyocr on
# [OCR-DISABLED]             # ANY failure (crash / timeout / non-zero / unparseable).
# [OCR-DISABLED]             try:
# [OCR-DISABLED]                 return _extract_paddle_subprocess(ocr_path)
# [OCR-DISABLED]             except OCRError as paddle_exc:
# [OCR-DISABLED]                 log.warning(
# [OCR-DISABLED]                     "PaddleOCR failed (%s); falling back to easyocr", paddle_exc
# [OCR-DISABLED]                 )
# [OCR-DISABLED]                 try:
# [OCR-DISABLED]                     return _extract_easyocr(ocr_path)
# [OCR-DISABLED]                 except OCRError as easy_exc:
# [OCR-DISABLED]                     raise OCRError(
# [OCR-DISABLED]                         "OCR failed for this image (both engines). "
# [OCR-DISABLED]                         "Try a smaller/clearer crop. "
# [OCR-DISABLED]                         f"[paddle: {paddle_exc}] [easyocr: {easy_exc}]"
# [OCR-DISABLED]                     )

# [OCR-DISABLED]         raise OCRError(f"Unknown OCR engine: {chosen}")
# [OCR-DISABLED]     finally:
# [OCR-DISABLED]         # Always clean up the downscaled temp file, even on error.
# [OCR-DISABLED]         if is_temp:
# [OCR-DISABLED]             try:
# [OCR-DISABLED]                 os.remove(ocr_path)
# [OCR-DISABLED]             except OSError:
# [OCR-DISABLED]                 pass
