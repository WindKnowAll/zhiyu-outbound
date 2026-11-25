"""模拟复现。不是线上逐轮原话，工单没有留下「为什么」前后的记录。"""

from __future__ import annotations

from zhiyu.qualification.catalog import load_catalog
from zhiyu.qualification.flow import (
    GOODBYE,
    SAFE_FALLBACK,
    case_for_row,
    customer_wording,
    filled_script,
    new_call,
    resolve_turn,
    scenario_of,
    split_reason_action,
)
from zhiyu.extensions import TurnRecord
from zhiyu.pipeline.timing import StageTimings
from zhiyu.qualification.hooks import QualificationHooks
from zhiyu.qualification.flow import TicketStore

import pytest


def _confirmed(row: int):
    catalog = load_catalog()
    call = new_call(case_for_row(row), catalog)
    decision, _ = resolve_turn(call, "对的是我", '{"intent":"confirm","reply":"稍后由审核同事确认。"}')
    call.pending = decision
    call.commit(False)
    return call, catalog


def test_row67_reason_has_no_reusable_action_step():
    catalog = load_catalog()
    scenario = scenario_of(catalog, 67)
    assert scenario.category == "行业资质"
    assert "资质上传有误" in scenario.reason
    text, complete = filled_script(scenario, "甲乙合成")
    spoken = customer_wording(text)
    reason, action = split_reason_action(spoken)
    assert complete is True
    assert "资质上传有误" in reason
    assert action == ""
    assert "协助操作" not in spoken


@pytest.mark.asyncio
async def test_simulated_why_uses_existing_reason_and_does_not_close(tmp_path):
    """合成商家说「为什么？」。不断言这是线上客服原话。"""

    call, _catalog = _confirmed(67)
    hooks = QualificationHooks(call=call, store=TicketStore(tmp_path))
    assert call.disclosed is True
    decision, _ = resolve_turn(
        call,
        "为什么？",
        '{"intent":"question","reply":"这个情况我帮您记录下来，稍后由审核同事和您进一步确认。"}',
    )
    assert decision.closed is False
    assert decision.result != "无标准回答转人工"
    assert SAFE_FALLBACK not in decision.speak
    assert "稍后由审核同事" not in decision.speak
    assert "资质上传有误" in decision.speak
    assert "协助操作" not in decision.speak
    assert "您还有不清楚的吗？" in decision.speak
    await hooks.after_turn(TurnRecord("为什么？", decision.speak, False, StageTimings(), []))
    assert call.stage != "closed"


def test_other_scenario_does_not_borrow_the_upload_reason():
    call, _catalog = _confirmed(36)
    decision, _ = resolve_turn(call, "为什么不通过", '{"intent":"question","reply":"资质上传有误"}')
    assert "资质上传有误" not in decision.speak
    assert "图形商标" in decision.speak
    assert decision.closed is False


def test_why_before_identity_does_not_disclose():
    call = new_call(case_for_row(67), load_catalog())
    decision, _ = resolve_turn(call, "为什么？", '{"intent":"question","reply":"资质上传有误"}')
    assert "资质上传有误" not in decision.speak
    assert decision.closed is False


def test_empty_script_why_after_confirm_is_already_closed():
    call, _catalog = _confirmed(28)
    assert call.stage == "closed"
    decision, _ = resolve_turn(call, "为什么？", '{"intent":"question","reply":"随便编"}')
    assert "已经结束" in decision.speak
    assert "资质上传有误" not in decision.speak


def test_explicit_goodbye_ends_and_plain_why_does_not():
    call, _catalog = _confirmed(67)
    why, _ = resolve_turn(call, "为什么？", '{"intent":"unclear","reply":""}')
    assert why.closed is False
    bye, _ = resolve_turn(call, "再见", '{"intent":"question","reply":"再问一句"}')
    assert bye.closed is True
    assert "再见" in bye.speak
    assert SAFE_FALLBACK not in bye.speak


def test_refuse_still_ends_without_extra_reason():
    call, _catalog = _confirmed(67)
    decision, _ = resolve_turn(call, "别打了", '{"intent":"question","reply":"资质上传有误"}')
    assert decision.closed is True
    assert GOODBYE in decision.speak or "不再展开" in decision.speak
