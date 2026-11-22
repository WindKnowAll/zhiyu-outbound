from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.server import create_app


def test_homepage_and_status_open_without_a_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    app = create_app(load_settings({"DASHSCOPE_API_KEY": ""}), preload_vad=False)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        assert "<title>智语外呼</title>" in page.text
        assert "<h1>智语外呼</h1>" in page.text
        assert "选择测试场景" in page.text
        assert "京东 POP 商家资质审核比赛模拟客服" in page.text
        assert "不是京东官方服务" in page.text
        assert page.text.count("<option ") >= 68
        assert "v1.8" in page.text
        assert "serviceWorker.register" not in page.text
        for old in ("图书馆", "星河", "取书", "小语"):
            assert old not in page.text
        build = client.get("/api/build")
        assert build.status_code == 200
        assert build.json()["page_version"] == "v1.8"
        assert len(build.json()["build_hash"]) == 12
        assert build.json()["service_worker"] is False
        assert build.json()["scenario_count"] == 68
        script = client.get("/static/app.js")
        assert script.headers["cache-control"] == "no-store"
        assert "echoCancellation" in script.text
        assert "noiseSuppression" in script.text
        assert "试听记录" in page.text
        voices = client.get("/api/voices")
        assert voices.status_code == 200
        assert voices.json()["voices"][0]["engine"] == "cosyvoice"
        assert "Microsoft" in voices.json()["unsupported"]
        collection = client.get("/api/collection")
        assert collection.json()["enabled"] is False
        assert client.post("/api/collect", json={}).status_code == 404

        status = client.get("/api/status")
        assert status.status_code == 200
        body = status.json()
        assert body["page_version"] == "v1.8"
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
