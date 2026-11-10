"""Tests for ai.ask_with_images and POST /api/vision-ask. Fully offline."""
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
    def __init__(self, content="ANSWER", calls=None, exc=None):
        outer = self
        self.calls = calls if calls is not None else []

        class _Completions:
            @staticmethod
            def create(**kwargs):
                outer.calls.append(kwargs)
                if exc:
                    raise exc
                return _Resp(content)

        self.chat = types.SimpleNamespace(completions=_Completions())


@pytest.fixture
def stub(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient("  ANSWER ", calls))
    return calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    # db caches its connection; point it at a temp file and reset it.
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    monkeypatch.setattr(server, "SHOTS_DIR", tmp_path / "shots")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    server.app.testing = True
    yield server.app.test_client()
    if db._conn is not None:
        db._conn.close()
    db._conn = None


def post(client, **body):
    return client.post("/api/vision-ask", json=body)


# ── ai unit tests ──
def test_build_messages_structure():
    msgs = ai._build_vision_messages(["u1", "u2"], "coding")
    assert [m["role"] for m in msgs] == ["system", "user"]
    c = msgs[1]["content"]
    assert c[0]["type"] == "text"
    assert c[1:] == [{"type": "image_url", "image_url": {"url": "u1"}},
                     {"type": "image_url", "image_url": {"url": "u2"}}]


def test_modes_differ_and_invalid_raise():
    a = ai._build_vision_messages(["u"], "coding")[0]["content"]
    b = ai._build_vision_messages(["u"], "scenario")[0]["content"]
    assert a != b
    with pytest.raises(ai.AIError):
        ai._build_vision_messages(["u"], "bogus")
    with pytest.raises(ai.AIError):
        ai._build_vision_messages([], "coding")


def test_ask_with_images_uses_vision_model(stub):
    assert ai.ask_with_images(["u"], "coding") == "ANSWER"
    assert stub[0]["model"] == ai.VISION_MODEL


def test_ask_with_images_wraps_errors(monkeypatch):
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient(exc=RuntimeError("x")))
    with pytest.raises(ai.AIError):
        ai.ask_with_images(["u"], "coding")


# ── route tests ──
def test_single_image_success(client, stub):
    r = post(client, images=[make_data_url()], mode="coding", source_types=["screenshot-region"])
    j = r.get_json()
    assert r.status_code == 200 and j["success"] and j["answer"] == "ANSWER"
    assert j["image_count"] == 1
    rec = db.get_record(j["record_id"])
    assert rec["status"] == "answered" and rec["source_type"] == "screenshot-region"
    assert rec["extracted_text"].startswith("[Vision · coding · 1 image")
    assert len(db.get_history(j["record_id"])) == 1
    assert (server.ROOT / rec["input_ref"]).exists()


def test_three_images_one_record_one_call(client, stub):
    r = post(client, images=[make_data_url() for _ in range(3)], mode="scenario")
    assert r.get_json()["image_count"] == 3
    assert len(db.list_records()) == 1
    assert len(stub) == 1
    parts = [p for p in stub[0]["messages"][1]["content"] if p["type"] == "image_url"]
    assert len(parts) == 3
    assert stub[0]["messages"][0]["content"].startswith(ai.VISION_SCENARIO_PROMPT)
    assert db.list_records()[0]["source_type"] == "screenshot-full"


@pytest.mark.parametrize("body", [
    {"images": [], "mode": "coding"},
    {"mode": "coding"},
    {"images": "x", "mode": "coding"},
    {"images": ["data:image/png;base64,AAAA"], "mode": "nope"},
    {"images": ["not-a-data-url"], "mode": "coding"},
    {"images": ["data:image/png;base64,!!!notbase64"], "mode": "coding"},
    {"images": ["data:image/png;base64," + base64.b64encode(b"plain text").decode()],
     "mode": "coding"},
])
def test_bad_requests_400(client, stub, body):
    r = client.post("/api/vision-ask", json=body)
    assert r.status_code == 400 and r.get_json()["success"] is False
    assert db.list_records() == [] and stub == []


def test_non_json_body_400(client, stub):
    r = client.post("/api/vision-ask", data="nope", content_type="text/plain")
    assert r.status_code == 400


def test_too_many_images_413(client, stub):
    r = post(client, images=["x"] * (server.VISION_MAX_IMAGES + 1), mode="coding")
    assert r.status_code == 413


def test_oversized_bytes_413(client, stub, monkeypatch):
    monkeypatch.setattr(server, "VISION_MAX_IMAGE_BYTES", 10)
    r = post(client, images=[make_data_url()], mode="coding")
    assert r.status_code == 413


def test_aierror_502_no_record(client, monkeypatch):
    def boom(*a, **k):
        raise ai.AIError("boom")
    monkeypatch.setattr(ai, "ask_with_images", boom)
    r = post(client, images=[make_data_url()], mode="coding")
    assert r.status_code == 502 and "boom" in r.get_json()["error"]
    assert "Traceback" not in r.get_data(as_text=True)
    assert db.list_records() == []


def test_raw_client_exception_502(client, monkeypatch):
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient(exc=RuntimeError("kaput")))
    r = post(client, images=[make_data_url()], mode="coding")
    assert r.status_code == 502 and db.list_records() == []


def test_unconfigured_key_502(client, monkeypatch):
    def nokey():
        raise ai.AIError("OPENAI_API_KEY is not set")
    monkeypatch.setattr(ai, "_get_client", nokey)
    r = post(client, images=[make_data_url()], mode="coding")
    assert r.status_code == 502 and "OPENAI_API_KEY" in r.get_json()["error"]


def test_unexpected_error_500_generic(client, monkeypatch):
    def bad(*a, **k):
        raise ValueError("secret internals")
    monkeypatch.setattr(ai, "ask_with_images", bad)
    r = post(client, images=[make_data_url()], mode="coding")
    assert r.status_code == 500 and "secret internals" not in r.get_data(as_text=True)


def test_large_image_downscaled(client, stub, monkeypatch):
    monkeypatch.setattr(server, "VISION_MAX_SIDE", 2000)
    j = post(client, images=[make_data_url(3000, 1000)], mode="coding").get_json()
    rec = db.get_record(j["record_id"])
    with Image.open(server.ROOT / rec["input_ref"]) as im:
        assert max(im.size) <= 2000


def test_language_passthrough(client, stub):
    post(client, images=[make_data_url()], mode="coding", language="hi")
    system = stub[0]["messages"][0]["content"]
    assert ai.language_instruction("hi") in system
