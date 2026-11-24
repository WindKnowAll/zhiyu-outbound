"""文字调试不碰识别和合成。模型是测试替身，不读取密钥。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.providers.base import ProviderError
from zhiyu.qualification.catalog import load_catalog
from zhiyu.server import create_app
from zhiyu.text_debug import choose_row

ROOT = Path(__file__).resolve().parents[1]
BANNED = (
    "getUserMedia",
    "mediaDevices",
    "RTCPeerConnection",
    "SpeechRecognition",
    "speechSynthesis",
    "webkitSpeechRecognition",
    "webkitSpeechGrammar",
)


class ScriptModel:
    def __init__(self, pieces, fail_once=False):
        self.pieces = pieces
        self.fail_once = fail_once
        self.calls = 0

    async def stream(self, messages):
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise ProviderError("模型超时")
        for piece in self.pieces:
            yield piece


def test_debug_page_has_no_voice_api_and_voice_home_keeps_microphone_policy():
    page = (ROOT / "zhiyu/static/debug.html").read_text(encoding="utf-8")
    script = (ROOT / "zhiyu/static/debug.js").read_text(encoding="utf-8")
    logic = (ROOT / "zhiyu/text_debug.py").read_text(encoding="utf-8")
    for banned in BANNED:
        assert banned not in page
        assert banned not in script
    assert "app.js" not in page
    assert "call_ui.js" not in page
    for banned in ("create_recognizer", "create_synthesizer", "DashScopeRecognizer", "DashScopeSynthesizer"):
        assert banned not in logic
    app = create_app(load_settings({"DASHSCOPE_API_KEY": ""}), preload_vad=False)
    with TestClient(app) as client:
        debug = client.get("/debug")
        home = client.get("/")
    assert debug.status_code == 200
    assert "microphone=()" in debug.headers["permissions-policy"]
    assert "文字调试" in debug.text
    assert "返回语音首页" in debug.text
    assert "permissions-policy" not in {key.lower() for key in home.headers}
    assert "开始通话" in home.text
    assert home.text.count(">文字调试<") == 1
    assert 'id="open-debug"' in home.text
    assert "异常情况提交" in home.text
    assert "异常情况记录" not in home.text
    css = (ROOT / "zhiyu/static/style.css").read_text(encoding="utf-8")
    assert "a.text-link" not in css
    assert "\n#composer" not in css
    assert ".debug-page #composer" in css


def test_typed_turn_uses_model_and_never_starts_audio(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("文字调试不能启动识别或合成")

    monkeypatch.setattr("zhiyu.providers.factory.create_recognizer", forbidden)
    monkeypatch.setattr("zhiyu.providers.factory.create_synthesizer", forbidden)
    monkeypatch.setattr("zhiyu.text_debug.pick_scenario", lambda rows, index: 15)
    model = ScriptModel(['{"intent":"confirm","reply":"我保证审核通过，转接真人。"}'], fail_once=True)
    app = create_app(
        load_settings({"DASHSCOPE_API_KEY": ""}),
        preload_vad=False,
        ticket_dir=tmp_path,
        incident_dir=tmp_path / "incidents",
        text_model=model,
        call_token="call-token-16chars",
    )
    with TestClient(app) as client:
        blocked = client.post("/api/debug/session", json={"scenario_id": 36})
        assert blocked.status_code == 401
        headers = {"X-Zhiyu-Call-Token": "call-token-16chars"}
        random_row = client.post("/api/debug/session", json={"random": True}, headers=headers)
        assert random_row.status_code == 200
        assert random_row.json()["row"] == 15
        assert random_row.json()["audio"] is False
        started = client.post("/api/debug/session", json={"scenario_id": 36}, headers=headers)
        assert started.status_code == 200
        body = started.json()
        assert "比赛模拟" in body["opening"]
        session_id = body["session_id"]
        failed = client.post(
            f"/api/debug/session/{session_id}/say",
            json={"text": "是的，我是这家公司"},
            headers=headers,
        )
        assert failed.status_code == 502
        assert "超时" in failed.json()["message"]
        said = client.post(
            f"/api/debug/session/{session_id}/say",
            json={"text": "是的，我是这家公司"},
            headers=headers,
        )
        assert said.status_code == 200
        assert model.calls == 2
        assert "保证审核通过" not in said.json()["speak"]
        assert "转接真人" not in said.json()["speak"]
        assert said.json()["audio"] is False
        ended = client.post(f"/api/debug/session/{session_id}/end", headers=headers)
        assert ended.status_code == 200
        assert ended.json()["ticket_written"] is True
        stored = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
        assert ended.json()["call_session_id"] in stored
        noted = client.post(
            "/api/incidents",
            data={"text": "文字页记下的异常", "call_session_id": ended.json()["call_session_id"]},
            files={"image": ("shot.jpg", b"\xff\xd8\xff" + b"\x00" * 16, "image/jpeg")},
            headers=headers,
        )
        assert noted.status_code == 200
        assert noted.json()["message"] == "提交成功"
        assert noted.json()["ticket_attached"] is True
        stored = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
        assert "文字页记下的异常" in stored
        assert noted.json()["image"] in stored
        assert ".." not in noted.json()["image"]
    assert choose_row(load_catalog(), 36, False) == 36
