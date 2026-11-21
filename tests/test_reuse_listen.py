"""重复启动判断。不绑定 7860，不读取 .env。"""

from zhiyu.config import load_settings, status_payload
from zhiyu.server import create_app
from fastapi.testclient import TestClient

from scripts.reuse_listen import is_this_app, listening_pids


NETSTAT = """
  TCP    0.0.0.0:7860           0.0.0.0:0              LISTENING       26056
  TCP    127.0.0.1:7860         0.0.0.0:0              LISTENING       26056
  TCP    127.0.0.1:78601        0.0.0.0:0              LISTENING       999
  TCP    127.0.0.1:80           0.0.0.0:0              LISTENING       111
"""


def test_listening_pids_match_only_the_exact_port():
    assert listening_pids(NETSTAT, 7860) == ["26056"]


def test_real_page_and_status_are_recognized_without_a_key():
    app = create_app(load_settings({"DASHSCOPE_API_KEY": ""}), preload_vad=False)
    with TestClient(app) as client:
        page = client.get("/")
        status = client.get("/api/status")
    assert is_this_app(page.text, status.status_code, status.text)


def test_closed_port_is_free():
    from tests.local_ws import closed_port
    from scripts.reuse_listen import classify

    assert classify(closed_port(), timeout=0.3) == "free"


def test_unknown_page_is_not_reused():
    status = status_payload(load_settings({"DASHSCOPE_API_KEY": ""}))
    assert is_this_app("<html><title>其他程序</title></html>", 200, __import__("json").dumps(status)) is False
    assert is_this_app("<html>智语外呼 比赛模拟</html>", 200, "not-json") is False
