"""Tests for /api/cancel and request_id cancellation. Fully offline."""
import base64
import io
import types
import pytest
from PIL import Image
import ai
import db
import server


def make_data_url(w=64, h=48):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class _Resp:
    def __init__(self, content):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]


class _FakeClient:
    def __init__(self, content="ANSWER"):
        class _Completions:
            @staticmethod
            def create(**kwargs):
                return _Resp(content)
        self.chat = types.SimpleNamespace(completions=_Completions())


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    monkeypatch.setattr(server, "SHOTS_DIR", tmp_path / "shots")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    server._cancelled.clear()
    server.app.testing = True
    yield server.app.test_client()
    server._cancelled.clear()
    if db._conn is not None:
        db._conn.close()
    db._conn = None


@pytest.fixture
def stub_ask(monkeypatch):
    monkeypatch.setattr(ai, "ask", lambda *a, **k: "A")


@pytest.fixture
def stub_vision(monkeypatch):
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient("ANSWER"))


def cancel(client, rid):
    return client.post("/api/cancel", json={"request_id": rid})


def shot_files():
    d = server.SHOTS_DIR
    return [p for p in d.rglob("*") if p.is_file()] if d.exists() else []


def history_count():
    return db._connect().execute("SELECT COUNT(*) FROM answer_history").fetchone()[0]


# ── /api/cancel ──
def test_cancel_validation(client):
    assert client.post("/api/cancel").status_code == 400
    assert client.post("/api/cancel", data="nope", content_type="text/plain").status_code == 400
    for bad in (123, "", "   ", None, "x" * 129, ["a"]):
        r = cancel(client, bad)
        assert r.status_code == 400 and r.get_json()["success"] is False
    assert client.post("/api/cancel", json=["x"]).status_code == 400


def test_cancel_ok_and_idempotent(client):
    for _ in range(2):
        r = cancel(client, "abc")
        assert r.status_code == 200 and r.get_json() == {"success": True}


def test_registry_bounded_eviction(client, monkeypatch):
    monkeypatch.setattr(server, "_CANCEL_MAX", 3)
    for i in range(5):
        server._mark_cancelled(f"id{i}")
    assert list(server._cancelled) == ["id2", "id3", "id4"]
    assert server._consume_cancelled("id0") is False
    assert server._consume_cancelled("id4") is True
    assert server._consume_cancelled("id4") is False


# ── /api/ask ──
def test_cancelled_ask_persists_nothing(client, stub_ask):
    cancel(client, "X")
    r = client.post("/api/ask", json={"text": "hi", "request_id": "X"})
    assert r.status_code == 200
    assert r.get_json() == {"success": False, "cancelled": True, "error": "Cancelled"}
    assert db.list_records() == []
    assert history_count() == 0


def test_cancelled_ask_existing_record_unchanged(client, stub_ask):
    rec = db.create_record(source_type="manual", input_ref=None,
                           extracted_text="old", status="captured")
    cancel(client, "X")
    r = client.post("/api/ask", json={"text": "new", "record_id": rec["id"], "request_id": "X"})
    assert r.get_json()["cancelled"] is True
    after = db.get_record(rec["id"])
    assert after["extracted_text"] == "old"
    assert after["status"] == "captured"
    assert not after["answer"]


def test_cancelled_ask_ai_error_does_not_set_error(client, monkeypatch):
    def boom(*a, **k):
        raise ai.AIError("upstream")
    monkeypatch.setattr(ai, "ask", boom)
    rec = db.create_record(source_type="manual", input_ref=None,
                           extracted_text="old", status="captured")
    cancel(client, "X")
    r = client.post("/api/ask", json={"text": "t", "record_id": rec["id"], "request_id": "X"})
    assert r.get_json()["cancelled"] is True
    assert db.get_record(rec["id"])["status"] == "captured"


def test_ask_without_request_id_unchanged(client, stub_ask):
    r = client.post("/api/ask", json={"text": "hi"})
    j = r.get_json()
    assert j["success"] is True and j["answer"] == "A"
    assert len(db.list_records()) == 1


def test_ask_uncancelled_request_id_then_late_cancel(client, stub_ask):
    r = client.post("/api/ask", json={"text": "hi", "request_id": "Y"})
    assert r.get_json()["success"] is True
    cancel(client, "Y")
    rec = db.get_record(r.get_json()["record_id"])
    assert rec["answer"] == "A"


def test_cancel_id_cleared_once_handled(client, stub_ask):
    cancel(client, "Z")
    assert client.post("/api/ask", json={"text": "a", "request_id": "Z"}).get_json()["cancelled"]
    r = client.post("/api/ask", json={"text": "a", "request_id": "Z"})
    assert r.get_json()["success"] is True


# ── /api/vision-ask ──
def test_cancelled_vision_ask_persists_nothing(client, stub_vision):
    cancel(client, "V")
    r = client.post("/api/vision-ask", json={
        "images": [make_data_url()], "mode": "coding", "request_id": "V"})
    assert r.status_code == 200
    assert r.get_json() == {"success": False, "cancelled": True, "error": "Cancelled"}
    assert db.list_records() == []
    assert shot_files() == []
    assert history_count() == 0


def test_vision_ask_without_request_id_unchanged(client, stub_vision):
    r = client.post("/api/vision-ask", json={"images": [make_data_url()], "mode": "coding"})
    j = r.get_json()
    assert j["success"] is True and j["answer"] == "ANSWER"
    assert len(db.list_records()) == 1
    assert len(shot_files()) == 1
