"""缺配置时服务拒绝建立通话。调用现有 create_app。"""

import pytest
from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.server import create_app


@pytest.mark.case(
    id="FLOW-13",
    scenario="没有密钥时拒绝通话",
    kind="离线配置",
    expected="页面能打开，/api/status 说明缺 DASHSCOPE_API_KEY，/api/offer 返回 503",
)
def test_missing_key_blocks_offer(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    app = create_app(load_settings({"DASHSCOPE_API_KEY": ""}), preload_vad=False)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "智语外呼" in page.text
        status = client.get("/api/status")
        assert status.status_code == 200
        assert status.json()["ok"] is False
        offer = client.post("/api/offer", json={"sdp": "v=0", "type": "offer"})
        assert offer.status_code == 503
