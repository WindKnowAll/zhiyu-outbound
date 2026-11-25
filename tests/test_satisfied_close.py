"""听懂以后收尾。末尾短杂音不算新问题，「明白了但是」不能结束。"""

from __future__ import annotations

import json

import pytest

from zhiyu.extensions import TurnRecord
from zhiyu.pipeline.timing import StageTimings
from zhiyu.qualification.catalog import load_catalog
from zhiyu.qualification.flow import (
    GOODBYE,
    RESULT_LINE,
    TicketStore,
    case_for_row,
    classify,
    is_positive_ack,
    is_satisfied_close,
    new_call,
    resolve_turn,
    scenario_of,
)
from zhiyu.qualification.hooks import QualificationHooks


def test_similar_group_is_the_table_reason():
    scenario = scenario_of(load_catalog(), 38)
    assert scenario.reason == "类似群不符合"
    assert scenario.close_method == "电话"
    assert "类似群不匹配" in scenario.script


def test_trailing_noise_is_still_acknowledgement():
    assert is_satisfied_close("好的，我明白了。超")
    assert is_satisfied_close("好的我明白了超")
    assert is_satisfied_close("清楚了。啊")
    assert is_satisfied_close("没问题了嗯")
    assert is_satisfied_close("没有了")
    assert is_positive_ack("好的，我明白了。超")
    assert classify("好的，我明白了。超") == "ack"
    assert not is_satisfied_close("明白了但是还有问题")
    assert not is_positive_ack("明白了但是还有问题")
    assert not is_satisfied_close("我明白了，为什么")
    assert not is_satisfied_close("我不明白")


def _confirmed(row: int):
    call = new_call(case_for_row(row), load_catalog())
    decision, _ = resolve_turn(call, "对的是我", '{"intent":"confirm","reply":"因为类似群不符合。您还有不清楚的吗？"}')
    call.pending = decision
    call.commit(False)
    return call


@pytest.mark.asyncio
async def test_understood_with_trailing_noise_closes_without_repeating_reason(tmp_path):
    call = _confirmed(38)
    hooks = QualificationHooks(call=call, store=TicketStore(tmp_path))
    first, _ = resolve_turn(call, "好的", '{"intent":"ack","reply":"因为类似群不符合。您还有不清楚的吗？"}')
    assert first.speak == RESULT_LINE
    assert first.closed is False
    await hooks.after_turn(TurnRecord("好的", first.speak, False, StageTimings(), []))
    assert call.stage == "ending"
    for text in ("好的，我明白了。超", "好的我明白了啊", "清楚了。超", "没问题了", "没有了哦", "好的。超"):
        decision, _ = resolve_turn(
            call,
            text,
            '{"intent":"question","reply":"因为类似群不符合。您还有不清楚的吗？"}',
        )
        assert decision.speak == GOODBYE, text
        assert decision.closed is True
        assert decision.result == "已知晓"
        assert "类似群" not in decision.speak
        assert "还有不清楚的吗" not in decision.speak
        assert "稍后由审核同事" not in decision.speak
    await hooks.after_turn(TurnRecord("好的，我明白了。超", GOODBYE, False, StageTimings(), []))
    files = list((tmp_path).glob("*.json"))
    assert len(files) == 1
    ticket = json.loads(files[0].read_text(encoding="utf-8"))
    assert ticket["result"] == "已知晓"
    assert ticket["source_row"] == 38
    assert ticket["mock"] is True


def test_acknowledgement_before_result_check_still_uses_the_existing_line():
    call = _confirmed(38)
    decision, _ = resolve_turn(call, "好的", '{"intent":"ack","reply":"因为类似群不符合。您还有不清楚的吗？"}')
    assert decision.speak == RESULT_LINE
    assert decision.closed is False


def test_reservation_after_understanding_does_not_end():
    call = _confirmed(38)
    call.stage = "ending"
    decision, _ = resolve_turn(
        call,
        "明白了但是还有问题",
        '{"intent":"ack","reply":"感谢您的接听，祝您生活愉快，再见！"}',
    )
    assert decision.closed is False
    assert decision.result != "已知晓"
    assert decision.speak != GOODBYE
    assert "还有不清楚的吗" not in decision.speak
    why, _ = resolve_turn(
        call,
        "我明白了，为什么",
        '{"intent":"ack","reply":"感谢您的接听，再见"}',
    )
    assert why.closed is False
    assert "类似群不符合" in why.speak
    assert "您还有不清楚的吗？" in why.speak
