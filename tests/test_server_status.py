from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.server import create_app


def test_homepage_and_status_open_without_a_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    app = create_app(load_settings({"DASHSCOPE_API_KEY": ""}), preload_vad=False)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "智语外呼" in page.text
        assert "echoCancellation" in client.get("/static/app.js").text

        status = client.get("/api/status")
        assert status.status_code == 200
        body = status.json()
        assert body["ok"] is False
        assert "DASHSCOPE_API_KEY" in body["message"]

        offer = client.post("/api/offer", json={"sdp": "v=0", "type": "offer"})
        assert offer.status_code == 503
        assert offer.json()["ok"] is False


def test_unknown_session_is_a_clear_404():
    app = create_app(load_settings({"DASHSCOPE_API_KEY": "sk-test"}), preload_vad=False)
    with TestClient(app) as client:
        missing = client.get("/api/sessions/nope")
        assert missing.status_code == 404
