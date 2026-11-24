"""异常图片提交。不连接服务器，不读取密钥。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.qualification.flow import TicketStore, new_call
from zhiyu.server import create_app

JPEG = b"\xff\xd8\xff" + b"\x00" * 32
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
CALL = "call-token-16chars"
ADMIN = "admin-token-16xx"
SUBMIT = "submit-token-16x"


def _app(tmp_path, *, call_token: str = ""):
    return create_app(
        load_settings({"DASHSCOPE_API_KEY": ""}),
        preload_vad=False,
        review_dir=tmp_path / "reviews",
        incident_dir=tmp_path / "incidents",
        ticket_dir=tmp_path / "tickets",
        collect_enabled=True,
        collect_token=ADMIN,
        collect_submit_token=SUBMIT,
        call_token=call_token,
    )


def _ticket(tmp_path, session_id: str) -> None:
    call = new_call()
    call.session_id = session_id
    call.result = "未完成"
    TicketStore(tmp_path / "tickets").write(call.to_ticket(interrupted=False))


def test_upload_links_the_mock_ticket_and_rejects_bad_images(tmp_path):
    _ticket(tmp_path, "pc-test-1")
    app = _app(tmp_path, call_token=CALL)
    with TestClient(app) as client:
        denied = client.post("/api/incidents", data={"text": "播到一半停了", "call_session_id": "pc-test-1"})
        assert denied.status_code == 401
        assert "口令" in denied.json()["message"]
        headers = {"X-Zhiyu-Call-Token": CALL}
        saved = client.post(
            "/api/incidents",
            data={"text": "播到一半停了", "call_session_id": "pc-test-1"},
            files={"image": ("../../etc/passwd.jpg", JPEG, "image/jpeg")},
            headers=headers,
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["message"] == "提交成功"
        assert body["ticket_attached"] is True
        assert body["image"].endswith(".jpg")
        assert ".." not in body["image"]
        assert "/" not in body["image"]
        ticket = next((tmp_path / "tickets").glob("*.json")).read_text(encoding="utf-8")
        assert "播到一半停了" in ticket
        assert body["image"] in ticket
        assert "passwd" not in ticket
        listed = client.get("/api/incidents", headers={"Authorization": "Bearer " + ADMIN})
        assert listed.status_code == 200
        assert listed.json()["incidents"][0]["text"] == "播到一半停了"
        assert client.get("/api/incidents").status_code == 401
        image = client.get(
            f"/api/incidents/{body['id']}/image",
            headers={"Authorization": "Bearer " + ADMIN},
        )
        assert image.status_code == 200
        assert image.content.startswith(b"\xff\xd8\xff")
        huge = client.post(
            "/api/incidents",
            data={"text": "太大", "call_session_id": "pc-test-1"},
            files={"image": ("big.jpg", JPEG + b"\x00" * (5 * 1024 * 1024), "image/jpeg")},
            headers=headers,
        )
        assert huge.status_code == 400
        assert "5MB" in huge.json()["message"]
        wrong = client.post(
            "/api/incidents",
            data={"text": "格式不对", "call_session_id": "pc-test-1"},
            files={"image": ("a.gif", GIF, "image/gif")},
            headers=headers,
        )
        assert wrong.status_code == 400
        assert "格式" in wrong.json()["message"]
        heic = client.post(
            "/api/incidents",
            data={"text": "手机原图", "call_session_id": ""},
            files={"image": ("IMG.HEIC", HEIC, "image/heic")},
            headers=headers,
        )
        assert heic.status_code == 200
        assert heic.json()["ticket_attached"] is False
        assert heic.json()["image"].endswith(".heic")
        png = client.post(
            "/api/incidents",
            data={"text": "只有文字也可以", "call_session_id": "missing-call"},
            headers=headers,
        )
        assert png.status_code == 200
        assert png.json()["ticket_attached"] is False
        assert png.json()["image"] == ""
