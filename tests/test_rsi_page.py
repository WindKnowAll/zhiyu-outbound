"""进化页只读本地数量。待审不算成果，明细不带原文。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from zhiyu.config import load_settings
from zhiyu.learning.store import LearningStore
from zhiyu.server import create_app

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "admin-token-16chars"
CALL = "call-token-16chars"


def _app(tmp_path):
    return create_app(
        load_settings({"DASHSCOPE_API_KEY": ""}),
        preload_vad=False,
        ticket_dir=tmp_path / "tickets",
        incident_dir=tmp_path / "incidents",
        review_dir=tmp_path / "reviews",
        learning_dir=tmp_path / "learning",
        learning_admin_token=ADMIN,
        call_token=CALL,
    )


def test_empty_store_reports_zero(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        body = client.get("/api/rsi/overview").json()
    assert body["effective_count"] == 0
    assert body["incidents"]["count"] == 0
    assert body["reviews"]["count"] == 0
    assert body["reviews"]["with_incident_note"] == 0
    assert body["learning"]["pending"] == 0
    assert body["learning"]["approved_enabled"] == 0
    assert body["followup_count"] == 0
    assert body["model_training"] is False
    assert body["improvement_curve"] is False


def test_pages_link_to_rsi_without_voice_or_approval():
    home = (ROOT / "zhiyu/static/index.html").read_text(encoding="utf-8")
    debug = (ROOT / "zhiyu/static/debug.html").read_text(encoding="utf-8")
    page = (ROOT / "zhiyu/static/rsi.html").read_text(encoding="utf-8")
    script = (ROOT / "zhiyu/static/rsi.js").read_text(encoding="utf-8")
    assert ">进化记录<" in home
    assert ">进化记录<" in debug
    assert "不是模型自训练" in page
    assert "/api/learning/" not in script
    assert "rollback" not in script
    assert "innerHTML" not in script
    assert "getUserMedia" not in page + script
    app = _app(ROOT / "var" / "rsi-test-empty")
    with TestClient(app) as client:
        opened = client.get("/rsi")
    assert opened.status_code == 200
    assert "话术进化" in opened.text


def test_overview_reads_live_counts_and_hides_sensitive_text(tmp_path):
    (tmp_path / "incidents").mkdir()
    (tmp_path / "reviews").mkdir()
    (tmp_path / "incidents" / ("a" * 32 + ".json")).write_text(
        json.dumps(
            {
                "id": "a" * 32,
                "call_session_id": "text-demo",
                "text": "手机 13800138000 <script>alert(1)</script>",
                "image": "secret.png",
                "ticket_attached": True,
                "saved_at": "2026-11-24T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "reviews" / "rev.json").write_text(
        json.dumps(
            {
                "id": "rev-1",
                "saved_at": "2026-11-24T00:00:00Z",
                "pseudonym": "甲",
                "turns": [{"text": "13800138000"}],
                "feedback": {"incident": "", "suggestion": "整本流水"},
                "scenario": {"row": 66},
            }
        ),
        encoding="utf-8",
    )
    store = LearningStore(tmp_path / "learning")
    store.propose(source_row=66, intent="other", note="待审原文 13800138000", incident_id="a" * 32)
    pending_only = _app(tmp_path)
    with TestClient(pending_only) as client:
        overview = client.get("/api/rsi/overview")
        assert overview.status_code == 200
        body = overview.json()
        assert body["effective_count"] == 0
        assert body["learning"]["pending"] == 1
        assert body["pending_is_evolution"] is False
        assert body["model_training"] is False
        assert body["incidents"]["count"] == 1
        assert body["incidents"]["linked_tickets"] == 1
        assert body["reviews"]["count"] == 1
        assert body["reviews"]["with_incident_note"] == 0
        blob = overview.text
        assert "13800138000" not in blob
        assert "<script>" not in blob
        assert "secret.png" not in blob
        assert "待审原文" not in blob
        detail = client.get("/api/rsi/detail", headers={"Authorization": f"Bearer {CALL}"})
        assert detail.status_code == 401
        shown = client.get("/api/rsi/detail", headers={"Authorization": f"Bearer {ADMIN}"})
        assert shown.status_code == 200
        detail_blob = shown.text
        assert "13800138000" not in detail_blob
        assert "<script>" not in detail_blob
        assert "secret.png" not in detail_blob
        assert shown.json()["learning"][0]["status"] == "pending"
        assert shown.json()["learning"][0]["enabled"] is False
        assert "speak" not in shown.json()["learning"][0]
        store.approve(shown.json()["learning"][0]["id"], "因为不符合业务要求。您还有不清楚的吗？")
        enabled = client.get("/api/rsi/overview")
        assert enabled.status_code == 200
        assert enabled.json()["effective_count"] == 1
        assert enabled.json()["learning"]["approved_enabled"] == 1
        assert "不符合业务要求" not in enabled.text
