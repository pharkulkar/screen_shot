"""Tests for POST /api/register-capture (daemon -> Gallery, no OCR). Offline."""
import base64
import io
import os
import subprocess
import sys
from pathlib import Path
import pytest
from PIL import Image
import db
import server

def make_data_url(w=32, h=24):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 120, 200)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

@pytest.fixture
def client(tmp_path, monkeypatch):
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

def _files(tmp_path):
    d = tmp_path / "shots"
    return list(d.rglob("*.png")) if d.exists() else []

def test_success_creates_one_record_and_file(client, tmp_path):
    r = client.post("/api/register-capture",
                    json={"image": make_data_url(), "source_type": "screenshot-full"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["success"] is True and j["record_id"]
    recs = db.list_records()
    assert len(recs) == 1 and recs[0]["id"] == j["record_id"]
    assert recs[0]["source_type"] == "screenshot-full"
    assert not recs[0].get("extracted_text")
    assert len(_files(tmp_path)) == 1
    assert (tmp_path / recs[0]["input_ref"]).exists()

def test_source_type_as_sent_and_default(client):
    client.post("/api/register-capture",
                json={"image": make_data_url(), "source_type": "screenshot-region"})
    client.post("/api/register-capture", json={"image": make_data_url()})
    types_ = sorted(r["source_type"] for r in db.list_records())
    assert types_ == ["screenshot-full", "screenshot-region"]

def test_missing_image(client, tmp_path):
    for body in ({}, {"image": ""}, {"image": 5}, {"source_type": "screenshot-full"}):
        r = client.post("/api/register-capture", json=body)
        assert r.status_code == 400 and r.get_json()["success"] is False
    assert db.list_records() == [] and _files(tmp_path) == []

@pytest.mark.parametrize("bad", [
    "not a data url",
    "data:image/png;base64,@@@not-base64@@@",
    "data:image/png;base64,",
    "data:image/png;base64," + base64.b64encode(b"this is not an image").decode(),
])
def test_invalid_image(client, tmp_path, bad):
    r = client.post("/api/register-capture", json={"image": bad})
    assert r.status_code == 400
    assert r.get_json()["success"] is False
    assert "Traceback" not in r.get_data(as_text=True)
    assert db.list_records() == [] and _files(tmp_path) == []

@pytest.mark.parametrize("raw", ["not json", "[1, 2]", ""])
def test_bad_json(client, raw):
    r = client.post("/api/register-capture", data=raw, content_type="application/json")
    assert r.status_code == 400 and r.get_json()["success"] is False

def test_removed_ocr_routes_are_gone(client):
    for path in ("/api/ocr", "/api/ocr-only", "/api/solve"):
        assert client.post(path, json={}).status_code == 404

def test_import_server_does_not_load_ocr_libs():
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    code = ("import sys, server; "
            "bad=[m for m in ('easyocr','torch','paddleocr','paddle') if m in sys.modules]; "
            "sys.exit(1 if bad else 0)")
    root = Path(__file__).resolve().parent.parent
    assert subprocess.run([sys.executable, "-c", code], cwd=root, env=env).returncode == 0
