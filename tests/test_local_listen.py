"""打开页面和查看状态不建立付费会话，也不打开麦克风。"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.server import create_app


def test_default_host_is_loopback_and_env_can_override():
    assert load_settings({}).host == "127.0.0.1"
    assert load_settings({"HOST": "0.0.0.0"}).host == "0.0.0.0"


def test_status_and_homepage_do_not_call_paid_providers_or_leak_key(monkeypatch):
    calls: list[str] = []

    def forbid(*_args, **_kwargs):
        calls.append("provider")
        raise AssertionError("查看状态不应创建语音供应商")

    monkeypatch.setattr("zhiyu.providers.factory.create_recognizer", forbid)
    monkeypatch.setattr("zhiyu.providers.factory.create_language_model", forbid)
    monkeypatch.setattr("zhiyu.providers.factory.create_synthesizer", forbid)
    secret = "sk-offline-not-for-status"
    app = create_app(load_settings({"DASHSCOPE_API_KEY": secret}), preload_vad=False)
    with TestClient(app) as client:
        page = client.get("/")
        status = client.get("/api/status")
    blob = page.text + json.dumps(status.json(), ensure_ascii=False)
    assert status.status_code == 200
    assert calls == []
    assert secret not in blob


def test_microphone_starts_only_from_the_call_button():
    text = Path("zhiyu/static/app.js").read_text(encoding="utf-8")
    assert text.count("getUserMedia") == 1
    assert text.index("async function connect") < text.index("getUserMedia")
    assert text.index("buttonEl.addEventListener") < text.index("await connect()")
