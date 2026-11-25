"""TURN 短期凭据。不连接 coturn，不读取 .env。"""

from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.server import create_app
from zhiyu.turn_ice import TurnConfig


SECRET = "test-secret-16xx"


def test_mint_matches_coturn_hmac_and_does_not_return_the_secret():
    turn = TurnConfig(
        secret=SECRET,
        public_host="203.0.113.8",
        listen_host="172.31.77.255",
        ttl_seconds=600,
    )
    username, credential = turn.mint("browser", now=1699999400)
    assert username == "1700000000:browser"
    assert credential == "5NDOeP/CvMLWd03jbOmiebSFPos="
    check = base64.b64encode(hmac.new(SECRET.encode(), username.encode(), hashlib.sha1).digest()).decode()
    assert credential == check
    assert SECRET not in credential


def test_browser_uses_public_host_and_aiortc_uses_private_host():
    turn = TurnConfig(secret=SECRET, public_host="203.0.113.8", listen_host="172.31.77.255")
    stun = ("stun:stun.qq.com:3478", "stun:stun.miwifi.com:3478")
    browser = turn.browser_servers(stun, now=1699999400)
    server = turn.aiortc_servers(stun, now=1699999400)
    assert browser[0] == {"urls": "stun:stun.qq.com:3478"}
    relays = [item for item in browser if item["urls"].startswith("turn:")]
    assert [item["urls"] for item in relays] == [
        "turn:203.0.113.8:3478?transport=udp",
        "turn:203.0.113.8:3478?transport=tcp",
    ]
    assert all(item["credential"] != SECRET for item in relays)
    assert server[0].urls == "stun:stun.qq.com:3478"
    assert server[-1].urls == "turn:172.31.77.255:3478?transport=udp"
    assert server[-1].username.endswith(":aiortc")
    assert server[-1].credential
    assert "203.0.113.8" not in server[-1].urls
    assert len([item for item in server if str(item.urls).startswith("turn:")]) == 1


def test_short_secret_keeps_turn_off():
    turn = TurnConfig(secret="short", public_host="203.0.113.8", listen_host="172.31.77.255")
    assert turn.enabled is False
    assert turn.browser_servers(("stun:stun.qq.com:3478",)) == [{"urls": "stun:stun.qq.com:3478"}]


def test_ice_endpoint_hides_secret_and_respects_call_token(tmp_path):
    settings = load_settings(
        {
            "DASHSCOPE_API_KEY": "",
            "ZHIYU_TURN_SECRET": SECRET,
            "ZHIYU_TURN_PUBLIC_HOST": "203.0.113.8",
            "ZHIYU_TURN_LISTEN_HOST": "172.31.77.255",
        }
    )
    app = create_app(
        settings,
        preload_vad=False,
        review_dir=tmp_path,
        collect_enabled=False,
        call_token="call-token-16chars",
    )
    with TestClient(app) as client:
        status = client.get("/api/status")
        assert status.json()["turn_enabled"] is True
        assert SECRET not in status.text
        assert "credential" not in status.text
        blocked = client.get("/api/ice")
        assert blocked.status_code == 401
        allowed = client.get("/api/ice", headers={"X-Zhiyu-Call-Token": "call-token-16chars"})
        assert allowed.status_code == 200
        body = allowed.json()
        assert body["turn_enabled"] is True
        turn = [item for item in body["ice_servers"] if "turn:" in item["urls"]]
        assert turn
        assert SECRET not in allowed.text
        assert turn[0]["credential"] != SECRET
        assert "203.0.113.8" in turn[0]["urls"]
        assert "172.31.77.255" not in turn[0]["urls"]
