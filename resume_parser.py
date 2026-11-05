"""resume_parser — session-only resume text extraction + optional distillation.

Kept as its own module (mirroring the one-module-per-concern layout used by
``ocr_engine.py`` / ``question_detector.py``) so ``server.py``'s resume route
stays thin. Everything here is stateless: text is extracted from an in-memory
stream and (best-effort) distilled by the LLM into a concise candidate profile.
Nothing is written to disk or the DB — the profile rides the existing
``/ws/interview`` start-frame ``candidate_profile`` field and lives only for the
session's lifetime.

Security: NEVER log raw file bytes or extracted resume text (it is user PII).
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)

# ── Char budgets (pinned constants — see design.md Feature 2b) ───────────────
# RESUME_DISTILL_INPUT_BUDGET caps how much extracted text is fed to the LLM;
# RESUME_RAW_PROFILE_BUDGET caps the raw-text fallback profile (when distill is
# off or the LLM is unavailable). A profile is flagged ``truncated`` whenever it
# was built from a source longer than the budget it was capped to.
RESUME_DISTILL_INPUT_BUDGET = 6000
RESUME_RAW_PROFILE_BUDGET = 8000

RESUME_DISTILL_PROMPT = (
    "Summarize this resume into a concise candidate profile: role, years, key "
    "skills, notable projects/achievements. Use ONLY facts present; do not invent."
)


class ResumeParseError(Exception):
    """Raised when a resume cannot be read into usable text."""


def _ext(filename: str) -> str:
    name = (filename or "").lower().strip()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        raise ResumeParseError("PDF support is unavailable on the server.") from exc
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except ResumeParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ResumeParseError("Could not read the file.") from exc


def _extract_docx(file_bytes: bytes) -> str:
    try:
        import docx  # python-docx
    except Exception as exc:  # noqa: BLE001
        raise ResumeParseError("DOCX support is unavailable on the server.") from exc
    try:
        document = docx.Document(io.BytesIO(file_bytes))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text:
                        parts.append(cell.text)
        return "\n".join(parts)
    except ResumeParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ResumeParseError("Could not read the file.") from exc


def _extract_txt(file_bytes: bytes) -> str:
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return file_bytes.decode("latin-1")
        except Exception as exc:  # noqa: BLE001
            raise ResumeParseError("Could not read the file.") from exc


def extract_text(file_stream, filename: str, content_type: str | None = None) -> str:
    """Extract plain text from a resume upload.

    Dispatches by extension (``.pdf`` / ``.docx`` / ``.txt``). Reads the whole
    stream into memory (a ``BytesIO``) so no temp file is ever written to disk.
    Raises ``ResumeParseError`` for unsupported types or unreadable files. The
    returned text may be empty/whitespace — the caller decides what to do.
    """
    ext = _ext(filename)
    ctype = (content_type or "").lower()

    # Read the stream once; libraries all accept bytes/BytesIO.
    if hasattr(file_stream, "read"):
        file_bytes = file_stream.read()
    else:
        file_bytes = bytes(file_stream)

    if ext == ".pdf" or "pdf" in ctype:
        return _extract_pdf(file_bytes)
    if ext == ".docx" or "wordprocessingml" in ctype:
        return _extract_docx(file_bytes)
    if ext == ".txt" or ctype.startswith("text/"):
        return _extract_txt(file_bytes)

    raise ResumeParseError("Unsupported file type; upload PDF, DOCX, or TXT.")


def distill(text: str, ai_module) -> tuple[str, bool, bool]:
    """Turn extracted resume text into a candidate profile.

    Returns ``(profile, distilled, truncated)``:
      - ``profile``   — the text used as ``candidate_profile``.
      - ``distilled`` — True when the LLM produced the summary; False for the
                        raw-text fallback.
      - ``truncated`` — True when the profile was built from a source longer
                        than the budget it was capped to.

    Called ONLY on non-empty text (the route runs the empty-extraction guard
    first), so ``ai.ask``'s empty-input ``AIError`` is unreachable here. The
    LLM call is best-effort: on any ``AIError`` / not-configured, we fall back
    to the (capped) raw text, which is always a valid profile. Never logs the
    file bytes or extracted text.
    """
    configured = False
    if ai_module is not None:
        try:
            configured = bool(ai_module.is_configured())
        except Exception:  # noqa: BLE001
            configured = False

    if configured:
        try:
            profile = ai_module.ask(
                text[:RESUME_DISTILL_INPUT_BUDGET],
                system_prompt=RESUME_DISTILL_PROMPT,
            )
            truncated = len(text) > RESUME_DISTILL_INPUT_BUDGET
            return (profile or "").strip(), True, truncated
        except Exception as exc:  # noqa: BLE001 — AIError or anything upstream
            log.debug("resume distillation failed; falling back to raw text (%s)", exc)

    # Raw-text fallback (distill off, AI unconfigured, or distillation failed).
    truncated = len(text) > RESUME_RAW_PROFILE_BUDGET
    return text[:RESUME_RAW_PROFILE_BUDGET], False, truncated
