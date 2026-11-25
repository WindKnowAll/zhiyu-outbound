"""进化页的数量口径。只汇总已落盘的记录，不生成曲线，也不把待审当成成果。"""

from __future__ import annotations

import re
from datetime import datetime, timezone

_DIGITS = re.compile(r"\d{5,}")
_SECRET = re.compile(r"(密钥|token|bearer|password)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def learning_counts(items: list[dict]) -> dict[str, int]:
    counts = {"pending": 0, "approved_enabled": 0, "disabled": 0, "rejected": 0, "followup": 0, "other": 0}
    for item in items:
        status = str(item.get("status") or "")
        enabled = bool(item.get("enabled")) and bool(str(item.get("speak") or "").strip())
        if status == "pending":
            counts["pending"] += 1
        elif status == "approved" and enabled:
            counts["approved_enabled"] += 1
        elif status in {"disabled", "approved"}:
            counts["disabled"] += 1
        elif status == "rejected":
            counts["rejected"] += 1
        elif status == "followup":
            counts["followup"] += 1
        else:
            counts["other"] += 1
    return counts


def build_overview(*, incidents: list[dict], reviews: list[dict], items: list[dict]) -> dict:
    learning = learning_counts(items)
    incident_rows = [item for item in incidents if isinstance(item, dict) and item.get("id")]
    review_rows = [item for item in reviews if isinstance(item, dict)]
    with_note = 0
    for item in review_rows:
        feedback = item.get("feedback") if isinstance(item.get("feedback"), dict) else {}
        if str((feedback or {}).get("incident") or "").strip():
            with_note += 1
        elif item.get("has_incident_note"):
            with_note += 1
    linked = sum(1 for item in incident_rows if item.get("ticket_attached"))
    effective = learning["approved_enabled"]
    return {
        "rsi": "human_review_only",
        "model_training": False,
        "auto_approve": False,
        "improvement_curve": False,
        "generated_at": _now(),
        "effective_count": effective,
        "pending_is_evolution": False,
        "pipeline": [
            {"step": "异常反馈", "count": len(incident_rows), "counts_as_evolution": False},
            {"step": "人工试听记录", "count": len(review_rows), "counts_as_evolution": False},
            {"step": "候选改进", "count": learning["pending"], "counts_as_evolution": False},
            {"step": "审核后生效", "count": effective, "counts_as_evolution": True},
            {
                "step": "停用或回滚",
                "count": learning["disabled"] + learning["rejected"],
                "counts_as_evolution": False,
            },
        ],
        "learning": learning,
        "incidents": {"count": len(incident_rows), "linked_tickets": linked},
        "reviews": {"count": len(review_rows), "with_incident_note": with_note},
        "followup_count": learning["followup"],
        "detail": "明细需要管理员令牌。通话口令不能查看。",
    }


_HIDDEN_KEYS = {"text", "image", "session_id", "call_session_id", "speak", "note", "pseudonym", "turns", "feedback"}


def public_overview(payload: dict) -> dict:
    """再扫一遍，确认公开接口没有原文、编号和图片名。"""

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _HIDDEN_KEYS:
                    raise ValueError("公开概览含有不该出现的字段")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str) and (_DIGITS.search(node) or "<" in node or _SECRET.search(node)):
            raise ValueError("公开概览含有不该出现的内容")

    walk(payload)
    return payload


def detail_learning(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        history = []
        for step in item.get("history") or []:
            if isinstance(step, dict):
                history.append({"at": str(step.get("at") or ""), "action": str(step.get("action") or "")})
        rows.append(
            {
                "id": str(item.get("id") or ""),
                "source_row": item.get("source_row"),
                "intent": str(item.get("intent") or ""),
                "status": str(item.get("status") or ""),
                "enabled": bool(item.get("enabled")),
                "version": int(item.get("version") or 0),
                "created_at": str(item.get("created_at") or ""),
                "dispatch": str(item.get("dispatch") or ""),
                "history": history,
            }
        )
    return rows


def detail_incidents(rows: list[dict]) -> list[dict]:
    safe = []
    for item in rows:
        safe.append(
            {
                "id": str(item.get("id") or ""),
                "saved_at": str(item.get("saved_at") or ""),
                "ticket_attached": bool(item.get("ticket_attached")),
                "has_image": bool(item.get("has_image")),
                "source_row": item.get("source_row"),
            }
        )
    return safe


def detail_reviews(rows: list[dict]) -> list[dict]:
    safe = []
    for item in rows:
        safe.append(
            {
                "id": str(item.get("id") or ""),
                "saved_at": str(item.get("saved_at") or ""),
                "has_incident_note": bool(item.get("has_incident_note")),
                "scenario_row": item.get("scenario_row"),
            }
        )
    return safe
