"""合成复现截图顺序。不是线上逐轮原话，工单里没有 history。"""

from __future__ import annotations

import json

import pytest

from zhiyu.extensions import TurnRecord
from zhiyu.learning.store import LearningStore
from zhiyu.pipeline.timing import StageTimings
from zhiyu.qualification.catalog import load_catalog
from zhiyu.qualification.flow import (
    SAFE_FALLBACK,
    TicketStore,
    case_for_row,
    classify,
    new_call,
    resolve_turn,
    scenario_of,
)
from zhiyu.qualification.hooks import QualificationHooks


def _open(row: int, store: LearningStore | None = None):
    call = new_call(case_for_row(row), load_catalog())
    call.learning = store
    call.session_id = f"sim-text-{row}"
    decision, _ = resolve_turn(call, "对的是我", '{"intent":"confirm","reply":"稍后由审核同事确认。"}')
    call.pending = decision
    call.commit(False)
    return call


def test_negation_is_not_an_acknowledgement():
    assert classify("我不明白") == "confused"
    assert classify("我不清楚") == "confused"
    assert classify("没听懂") == "confused"
    assert classify("还是不懂") == "confused"
    assert classify("我明白了") == "ack"
    assert classify("清楚了") == "ack"
    assert classify("我不明白了") == "confused"


@pytest.mark.asyncio
async def test_repeated_confusion_writes_pending_review_not_understood(tmp_path):
    catalog = load_catalog()
    assert "不符合业务要求" in scenario_of(catalog, 66).reason
    store = LearningStore(tmp_path / "learning")
    tickets = TicketStore(tmp_path / "tickets")
    call = _open(66, store)
    call.session_id = "sim-r66"
    hooks = QualificationHooks(call=call, store=tickets)
    turns = []
    for text in ("这是为什么呢？", "我不明白", "我不明白"):
        decision, _ = resolve_turn(call, text, '{"intent":"ack","reply":"具体能否通过，还需要查看到最新的资质才能确定。您清楚了吗？"}')
        turns.append({"user": text, "speak": decision.speak, "closed": decision.closed, "result": decision.result})
        call.pending = decision
        await hooks.after_turn(TurnRecord(text, decision.speak, False, StageTimings(), []))
    assert "因为不符合业务要求" in turns[0]["speak"]
    assert turns[0]["closed"] is False
    assert "最新资质" not in turns[1]["speak"]
    assert "不符合业务要求" in turns[1]["speak"]
    assert turns[1]["closed"] is False
    assert turns[2]["result"] == "未解决待审核"
    assert "已记录您的疑问" in turns[2]["speak"]
    files = list((tmp_path / "tickets").glob("*.json"))
    assert len(files) == 1
    ticket = json.loads(files[0].read_text(encoding="utf-8"))
    assert ticket["result"] == "未解决待审核"
    assert ticket["call_session_id"] == "sim-r66"
    assert ticket["source_row"] == 66
    assert ticket["handoff"] == ""
    assert ticket["mock"] is True
    followups = [item for item in store.list_items() if item["status"] == "followup"]
    assert len(followups) == 1
    assert followups[0]["enabled"] is False
    assert followups[0]["source_row"] == 66
    other = _open(67, store)
    other_why, _ = resolve_turn(other, "为什么？", '{"intent":"ack","reply":""}')
    assert "不符合业务要求" not in other_why.speak
    assert "资质上传有误" in other_why.speak
    fresh = _open(66, store)
    assert fresh.unclear_count == 0
    again, _ = resolve_turn(call, "我不明白", '{"intent":"ack","reply":""}')
    assert "已经结束" in again.speak
    hooks.on_hangup()
    assert len(list((tmp_path / "tickets").glob("*.json"))) == 1
    evidence = {
        "simulation": True,
        "not_a_production_replay": True,
        "note": "合成顺序对照截图里的三轮。不是工单里的逐轮原话。用户建议句不是已核实客服原话。",
        "scenario_row": 66,
        "reason": scenario_of(catalog, 66).reason,
        "turns": turns,
        "ticket": {"result": ticket["result"], "call_session_id": ticket["call_session_id"], "handoff": ticket["handoff"], "mock": True},
        "followup_enabled": False,
        "dispatch": "local_only",
    }
    (tmp_path / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


def test_failed_followup_write_does_not_claim_success(tmp_path):
    class Broken(LearningStore):
        def record_unresolved(self, **_kwargs) -> bool:
            raise OSError("disk")

    call = _open(66, Broken(tmp_path))
    resolve_turn(call, "我不明白", '{"intent":"ack","reply":""}')
    decision, _ = resolve_turn(call, "我不明白", '{"intent":"ack","reply":""}')
    assert "没能把疑问记下来" in decision.speak
    assert "已记录您的疑问" not in decision.speak


def test_identity_denial_and_empty_script_do_not_invent():
    denied = new_call(case_for_row(66), load_catalog())
    denial, _ = resolve_turn(denied, "我不是这家", '{"intent":"ack","reply":"不符合业务要求"}')
    assert denial.closed is True
    assert "不符合业务要求" not in denial.speak
    stopped, _ = resolve_turn(_open(66), "别打了", '{"intent":"ack","reply":"不符合业务要求"}')
    assert stopped.closed is True
    assert "已记录您的疑问" not in stopped.speak
    empty = new_call(case_for_row(28), load_catalog())
    closed, _ = resolve_turn(empty, "对的是我", '{"intent":"confirm","reply":""}')
    assert closed.speak == SAFE_FALLBACK or closed.closed is True
    assert "不符合业务要求" not in closed.speak
