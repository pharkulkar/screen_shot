"""Tests for resume_parser + the /api/resume/parse route.

Fully offline: no network, AI stubbed, no OPENAI_API_KEY. Resume text is held
only in memory (BytesIO) — nothing is written to disk or the DB.
"""
import io

import pytest

import resume_parser
import server


# ── Stub AIs (kept local so the shared FakeAI's canned answer can't leak in) ──
class StubAIConfigured:
    """Distills to a fixed marker so we can assert the distilled path ran."""

    def is_configured(self):
        return True

    def ask(self, text, system_prompt=None, model=None):
        return "DISTILLED PROFILE"


class StubAIOff:
    def is_configured(self):
        return False

    def ask(self, text, system_prompt=None, model=None):
        raise AssertionError("ask() must not be called when AI is unconfigured")


class StubAIRaises:
    def is_configured(self):
        return True

    def ask(self, text, system_prompt=None, model=None):
        raise RuntimeError("upstream failure")


# ── extract_text ─────────────────────────────────────────────────────────────
def test_extract_text_txt_utf8():
    data = "Jane Doe\nSenior Engineer\nPython, Flask".encode("utf-8")
    out = resume_parser.extract_text(io.BytesIO(data), "resume.txt", "text/plain")
    assert "Senior Engineer" in out
    assert "Flask" in out


def test_extract_text_txt_latin1_fallback():
    data = "café résumé".encode("latin-1")
    out = resume_parser.extract_text(io.BytesIO(data), "resume.txt", None)
    assert "caf" in out  # decoded without raising


def test_extract_text_docx():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Alice Smith")
    document.add_paragraph("Backend Developer — 5 years")
    table = document.add_table(rows=1, cols=1)
    table.rows[0].cells[0].text = "Skill: Kubernetes"
    buf = io.BytesIO()
    document.save(buf)
    buf.seek(0)
    out = resume_parser.extract_text(buf, "resume.docx",
                                     "application/vnd.openxmlformats-officedocument"
                                     ".wordprocessingml.document")
    assert "Alice Smith" in out
    assert "Backend Developer" in out
    assert "Kubernetes" in out


def test_extract_text_pdf():
    pypdf = pytest.importorskip("pypdf")
    # Build a valid PDF with pypdf's own writer (a blank page). Authoring text
    # into a PDF requires a renderer (reportlab) we don't depend on, so we assert
    # the real contract instead: a valid PDF is parsed into a string without
    # raising. (Scanned/text-less PDFs are a 422 at the route layer, covered by
    # test_route_empty_text_422.)
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    out = resume_parser.extract_text(buf, "resume.pdf", "application/pdf")
    assert isinstance(out, str)


def test_extract_text_unsupported_type():
    with pytest.raises(resume_parser.ResumeParseError):
        resume_parser.extract_text(io.BytesIO(b"data"), "resume.xyz", None)


# ── distill ───────────────────────────────────────────────────────────────────
def test_distill_with_configured_ai():
    profile, distilled, truncated = resume_parser.distill("some resume text", StubAIConfigured())
    assert profile == "DISTILLED PROFILE"
    assert distilled is True
    assert truncated is False


def test_distill_ai_off_falls_back_to_raw():
    text = "raw resume body"
    profile, distilled, truncated = resume_parser.distill(text, StubAIOff())
    assert profile == text
    assert distilled is False
    assert truncated is False


def test_distill_ai_raises_falls_back_to_raw():
    text = "raw resume body"
    profile, distilled, truncated = resume_parser.distill(text, StubAIRaises())
    assert profile == text[:resume_parser.RESUME_RAW_PROFILE_BUDGET]
    assert distilled is False


def test_distill_truncated_flag_when_over_input_budget():
    text = "x" * (resume_parser.RESUME_DISTILL_INPUT_BUDGET + 100)
    profile, distilled, truncated = resume_parser.distill(text, StubAIConfigured())
    assert distilled is True
    assert truncated is True


def test_distill_raw_truncated_when_over_raw_budget():
    text = "y" * (resume_parser.RESUME_RAW_PROFILE_BUDGET + 50)
    profile, distilled, truncated = resume_parser.distill(text, StubAIOff())
    assert distilled is False
    assert truncated is True
    assert len(profile) == resume_parser.RESUME_RAW_PROFILE_BUDGET


# ── route: /api/resume/parse ───────────────────────────────────────────────────
@pytest.fixture
def client():
    server.app.testing = True
    with server.app.test_client() as c:
        yield c


def _multipart(text_bytes, filename="resume.txt", distill=None):
    data = {"file": (io.BytesIO(text_bytes), filename)}
    if distill is not None:
        data["distill"] = distill
    return data


def test_route_txt_success_no_distill(client):
    body = b"Candidate profile: Python engineer with 7 years of experience."
    r = client.post("/api/resume/parse",
                    data=_multipart(body, distill="false"),
                    content_type="multipart/form-data")
    assert r.status_code == 200
    j = r.get_json()
    assert j["success"] is True
    assert "Python engineer" in j["profile"]
    assert j["chars"] == len(body.decode("utf-8"))
    assert j["distilled"] is False
    assert "truncated" in j
    assert j["filename"] == "resume.txt"


def test_route_missing_file_400(client):
    r = client.post("/api/resume/parse", data={}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert r.get_json()["success"] is False


def test_route_bad_type_415(client):
    r = client.post("/api/resume/parse",
                    data=_multipart(b"data", filename="resume.exe"),
                    content_type="multipart/form-data")
    assert r.status_code == 415


def test_route_empty_text_422(client):
    r = client.post("/api/resume/parse",
                    data=_multipart(b"   \n\t  ", distill="false"),
                    content_type="multipart/form-data")
    assert r.status_code == 422
    assert r.get_json()["success"] is False


def test_route_oversize_413(client):
    # content_length is set by the test client; a tiny body with a forged
    # large Content-Length is awkward, so send a real >8MB body.
    big = b"a" * (8 * 1024 * 1024 + 1024)
    r = client.post("/api/resume/parse",
                    data=_multipart(big, distill="false"),
                    content_type="multipart/form-data")
    assert r.status_code == 413


def test_route_chars_is_pre_truncation_length(client):
    body = ("z" * (resume_parser.RESUME_RAW_PROFILE_BUDGET + 500)).encode("utf-8")
    r = client.post("/api/resume/parse",
                    data=_multipart(body, distill="false"),
                    content_type="multipart/form-data")
    assert r.status_code == 200
    j = r.get_json()
    assert j["chars"] == len(body)                 # pre-truncation
    assert len(j["profile"]) == resume_parser.RESUME_RAW_PROFILE_BUDGET
    assert j["truncated"] is True
