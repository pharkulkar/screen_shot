"""Integration tests for the REST interview endpoints via Flask's test client.

The LLM is replaced with a FakeAI injected into the live SessionManager that
server.py built at import time, so no network is used. WebSocket behaviour is
exercised indirectly: the REST routes drive the same InterviewSession engine,
and a disconnect/reconnect scenario is tested at the manager layer.
"""
import time

import pytest

import server
import interview_session as isess
from tests.test_interview_session import FakeAI


pytestmark = pytest.mark.skipif(
    server.interview_manager is None,
    reason="interview engine failed to initialize in server import",
)


@pytest.fixture
def client_with_fake_ai():
    # Swap the manager's AI (and its sessions' detector/ai) for the fake.
    mgr = server.interview_manager
    fake = FakeAI(chunks=["Answer ", "text."])
    orig_ai = mgr.ai
    orig_det_ai = mgr.detector.ai_module
    mgr.ai = fake
    mgr.detector.ai_module = fake
    server.app.testing = True
    with server.app.test_client() as client:
        yield client, fake
    # Cleanup: stop all sessions, restore AI.
    for sid in list(mgr._sessions.keys()):
        mgr.stop_session(sid)
    mgr.ai = orig_ai
    mgr.detector.ai_module = orig_det_ai


def _start(client, **body):
    r = client.post("/api/interview/start", json=body)
    assert r.status_code == 200
    return r.get_json()["session_id"]


def _drain_until(client, sid, event_type, timeout=4.0):
    end = time.time() + timeout
    seen = []
    while time.time() < end:
        r = client.get(f"/api/interview/{sid}/events")
        evs = r.get_json()["events"]
        seen.extend(evs)
        if any(e["type"] == event_type for e in seen):
            return seen
        time.sleep(0.05)
    return seen


def test_start_returns_config(client_with_fake_ai):
    client, _ = client_with_fake_ai
    r = client.post("/api/interview/start", json={})
    body = r.get_json()
    assert body["success"] is True
    assert "session_id" in body
    assert "detectionConfidenceThreshold" in body["config"]


def test_full_rest_flow_detects_and_answers(client_with_fake_ai):
    client, fake = client_with_fake_ai
    sid = _start(client)

    r = client.post(f"/api/interview/{sid}/transcript",
                    json={"text": "What is a deadlock?", "is_final": True})
    assert r.status_code == 200

    seen = _drain_until(client, sid, isess.EVT_ANSWER_COMPLETED)
    types = [e["type"] for e in seen]
    assert isess.EVT_QUESTION_DETECTED in types
    assert isess.EVT_ANSWER_COMPLETED in types
    completed = [e for e in seen if e["type"] == isess.EVT_ANSWER_COMPLETED][0]
    assert completed["answer"] == "Answer text."


def test_history_endpoint(client_with_fake_ai):
    client, _ = client_with_fake_ai
    sid = _start(client)
    client.post(f"/api/interview/{sid}/transcript",
                json={"text": "What is REST?", "is_final": True})
    _drain_until(client, sid, isess.EVT_ANSWER_COMPLETED)
    r = client.get(f"/api/interview/{sid}/history")
    hist = r.get_json()["history"]
    assert any("REST" in t["text"] for t in hist)


def test_unknown_session_404(client_with_fake_ai):
    client, _ = client_with_fake_ai
    r = client.post("/api/interview/does-not-exist/transcript",
                    json={"text": "hi", "is_final": True})
    assert r.status_code == 404


def test_cancel_endpoint(client_with_fake_ai):
    client, fake = client_with_fake_ai
    fake.chunks = ["a", "b", "c"]
    fake.delay = 0.2
    sid = _start(client)
    client.post(f"/api/interview/{sid}/transcript",
                json={"text": "Explain eventual consistency.", "is_final": True})
    _drain_until(client, sid, isess.EVT_ANSWER_STARTED)
    r = client.post(f"/api/interview/{sid}/cancel")
    assert r.get_json()["success"] is True


def test_stop_releases_session(client_with_fake_ai):
    client, _ = client_with_fake_ai
    sid = _start(client)
    r = client.post(f"/api/interview/{sid}/stop")
    assert r.get_json()["stopped"] is True
    # Session no longer known.
    r2 = client.get(f"/api/interview/{sid}/history")
    assert r2.status_code == 404


def test_disconnect_reconnect_same_session_id(client_with_fake_ai):
    """Simulate a WS drop: stop the session, then re-start with the same id.

    A fresh session is created (resources released); the client can resume
    sending transcript to the same logical id.
    """
    client, _ = client_with_fake_ai
    sid = "resume-me"
    _start(client, session_id=sid)
    client.post(f"/api/interview/{sid}/stop")        # "disconnect"
    sid2 = _start(client, session_id=sid)            # "reconnect"
    assert sid2 == sid
    r = client.post(f"/api/interview/{sid}/transcript",
                    json={"text": "What is a trie?", "is_final": True})
    assert r.status_code == 200
