"""队友试听记录。不打开麦克风，不调用百炼，不读取 .env。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.server import create_app
from zhiyu.teammate.review import ReviewRejected, validate_review


def _sample() -> dict:
    return {
        "schema": "zhiyu.teammate_review.v1",
        "synthetic": True,
        "raw_audio": False,
        "consent": True,
        "pseudonym": "甲",
        "page_version": "v1.8",
        "scenario": {
            "row": 36,
            "menu": "品牌",
            "category": "商标",
            "reason": "图形商标",
            "close_method": "电话",
            "script_complete": True,
        },
        "session_id": "local-1",
        "turns": [{"role": "user", "text": "是我们", "false_barge_in": True}],
        "provider_traces": [
            {
                "turn_id": 1,
                "provider_called": True,
                "provider_status": "empty",
                "intent": "confirm",
                "fallback_reason": "empty",
                "script_missing": False,
                "llm_first_token_ms": None,
            }
        ],
        "stage_timings": [],
        "feedback": {"expected": "说出原因", "actual": "说了原因"},
        "audio_constraints": {"echoCancellation": True, "noiseSuppression": False},
        "vad": {"confidence": 0.7, "start_secs": 0.2, "min_volume": 0.6},
    }


def test_review_rejects_audio_secrets_and_treats_empty_provider_as_given():
    bad = _sample()
    bad["raw_audio"] = True
    try:
        validate_review(bad)
    except ReviewRejected as exc:
        assert "录音" in str(exc)
    else:
        raise AssertionError("录音不应被接受")
    leaked = _sample()
    leaked["turns"][0]["text"] = "sk-secret"
    try:
        validate_review(leaked)
    except ReviewRejected as exc:
        assert "密钥" in str(exc)
    else:
        raise AssertionError("密钥不应被接受")
    saved = validate_review(_sample())
    assert saved["provider_traces"][0]["provider_status"] == "empty"
    assert saved["raw_audio"] is False
    real = _sample()
    real["session_id"] = "SmallWebRTCConnection#0-" + "cd" * 16
    kept = validate_review(real)
    assert kept["session_id"] == real["session_id"]
    unsafe = _sample()
    unsafe["session_id"] = "SmallWebRTCConnection#0/secret"
    try:
        validate_review(unsafe)
    except ReviewRejected as exc:
        assert "编号" in str(exc)
    else:
        raise AssertionError("带斜杠的通话编号不应留下")


def test_local_preview_save_export_and_collect_stays_off(tmp_path):
    app = create_app(
        load_settings({"DASHSCOPE_API_KEY": ""}),
        preload_vad=False,
        review_dir=tmp_path,
        collect_enabled=False,
        collect_token="",
    )
    with TestClient(app) as client:
        preview = client.post("/api/reviews/preview", json=_sample())
        assert preview.status_code == 200
        assert preview.json()["stored"] is False
        saved = client.post("/api/reviews", json=_sample())
        assert saved.status_code == 200
        review_id = saved.json()["id"]
        listed = client.get("/api/reviews")
        assert listed.json()["reviews"][0]["id"] == review_id
        exported = client.get(f"/api/reviews/{review_id}/export")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.json()["turns"][0]["text"] == "是我们"
        assert client.post("/api/collect", json=_sample()).status_code == 404
        vad = client.post(
            "/api/offer",
            json={"sdp": "v=0", "type": "offer", "scenario_id": "36", "vad": {"start_secs": 9}},
        )
        assert vad.status_code == 400


def test_collect_requires_admin_token_and_isolates_pseudonym(tmp_path):
    app = create_app(
        load_settings({"DASHSCOPE_API_KEY": ""}),
        preload_vad=False,
        review_dir=tmp_path,
        collect_enabled=True,
        collect_token="admin-token-16xx",
        collect_submit_token="submit-token-16x",
    )
    other = dict(_sample())
    other["pseudonym"] = "乙"
    with TestClient(app) as client:
        denied = client.post("/api/collect", json=_sample())
        assert denied.status_code == 401
        submit = {"Authorization": "Bearer submit-token-16x"}
        admin = {"Authorization": "Bearer admin-token-16xx"}
        first = client.post("/api/collect", json=_sample(), headers=submit)
        second = client.post("/api/collect", json=other, headers=submit)
        assert first.status_code == 200
        assert second.status_code == 200
        assert client.get("/api/collect", headers=submit).status_code == 401
        only_jia = client.get("/api/collect", params={"pseudonym": "甲"}, headers=admin)
        assert [item["pseudonym"] for item in only_jia.json()["reviews"]] == ["甲"]
        stored = client.get(f"/api/collect/{first.json()['id']}", headers=admin)
        assert stored.status_code == 200
        assert stored.json()["raw_audio"] is False
        assert stored.json()["consent"] is True
        assert client.get(f"/api/collect/{first.json()['id']}", headers=submit).status_code == 401
        assert client.get("/api/collect").status_code == 401
        assert client.get("/api/collection").json()["public_ready"] is False
        assert client.post("/api/reviews", json=_sample()).status_code == 403
        assert client.get("/api/reviews").status_code == 403


def test_incident_dedupes_and_admin_export_hides_tokens(tmp_path):
    app = create_app(
        load_settings({"DASHSCOPE_API_KEY": ""}),
        preload_vad=False,
        review_dir=tmp_path,
        collect_enabled=True,
        collect_token="admin-token-16xx",
        collect_submit_token="submit-token-16x",
        call_token="call-token-16chars",
    )
    incident = _sample()
    incident["call_link"] = "no_call"
    incident["session_id"] = ""
    incident["idempotency_key"] = "11111111-1111-1111-1111-111111111111"
    incident["feedback"] = {
        "expected": "",
        "actual": "",
        "incident": "播到一半停了",
        "suggestion": "先停再说明原因",
    }
    leaked = _sample()
    leaked["feedback"] = {"incident": "口令是 submit-token-16x", "expected": "", "actual": ""}
    scripted = _sample()
    scripted["feedback"] = {"incident": "<script>alert(1)</script>", "expected": "", "actual": ""}
    old = _sample()
    with TestClient(app) as client:
        submit = {"Authorization": "Bearer submit-token-16x"}
        admin = {"Authorization": "Bearer admin-token-16xx"}
        kept = validate_review(old)
        assert kept["call_link"] == "unspecified"
        assert kept["feedback"]["incident"] == ""
        assert kept["follow_up"] == "human_review_only"
        first = client.post("/api/collect", json=incident, headers=submit)
        second = client.post("/api/collect", json=incident, headers=submit)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["duplicate"] is True
        assert second.json()["call_link"] == "no_call"
        assert len(list(tmp_path.glob("*.json"))) == 1
        stored = client.get(f"/api/collect/{first.json()['id']}", headers=admin)
        assert stored.json()["raw_audio"] is False
        assert stored.json()["feedback"]["incident"] == "播到一半停了"
        assert "submit-token-16x" not in stored.text
        assert "admin-token-16xx" not in stored.text
        assert client.get("/api/collect/export", headers=submit).status_code == 401
        exported = client.get("/api/collect/export", params={"only": "incident"}, headers=admin)
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.json()["rsi"] == "human_review_only"
        assert exported.json()["raw_audio"] is False
        assert exported.json()["reviews"][0]["feedback"]["suggestion"] == "先停再说明原因"
        assert "submit-token-16x" not in exported.text
        assert "call-token-16chars" not in exported.text
        listed = client.get("/api/collect", headers=admin)
        assert listed.json()["reviews"][0]["has_incident"] is True
        assert listed.json()["reviews"][0]["call_link"] == "no_call"
        assert client.post("/api/collect", json=leaked, headers=submit).status_code == 400
        assert client.post("/api/collect", json=scripted, headers=submit).status_code == 400
        bad_link = _sample()
        bad_link["call_link"] = "next"
        assert client.post("/api/collect", json=bad_link, headers=submit).status_code == 400


def test_call_gate_blocks_offer_before_any_model(tmp_path):
    app = create_app(
        load_settings({"DASHSCOPE_API_KEY": ""}),
        preload_vad=False,
        review_dir=tmp_path,
        collect_enabled=False,
        collect_token="",
        collect_submit_token="",
        call_token="call-token-16chars",
    )
    with TestClient(app) as client:
        blocked = client.post("/api/offer", json={"sdp": "v=0", "type": "offer", "scenario_id": "36"})
        assert blocked.status_code == 401
        assert "sk-" not in blocked.text
        assert "口令" in blocked.text
        still = client.post(
            "/api/offer",
            json={"sdp": "v=0", "type": "offer", "scenario_id": "36"},
            headers={"X-Zhiyu-Call-Token": "call-token-16chars"},
        )
        assert still.status_code == 503
        assert "DASHSCOPE_API_KEY" in still.text
