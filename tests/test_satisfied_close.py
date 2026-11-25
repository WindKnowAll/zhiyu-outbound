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
    assert is_satisfied_close("嗯，好吧，我明白了。")
    assert is_satisfied_close("嗯好吧我明白了")
    assert is_satisfied_close("嗯好我明白了")
    assert is_satisfied_close("嗯好我明白了超")
    assert is_satisfied_close("好吧知道了")
    assert is_satisfied_close("哦，那行，清楚了")
    assert not is_satisfied_close("嗯，好吧")
    assert not is_satisfied_close("嗯，好吧，我明白了但是还有问题")


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
    for text in (
        "好的，我明白了。超",
        "好的我明白了啊",
        "清楚了。超",
        "没问题了",
        "没有了哦",
        "好的。超",
        "嗯，好吧，我明白了。",
        "好吧知道了",
        "哦，那行，清楚了",
    ):
        decision, _ = resolve_turn(
            call,
            text,
            '{"intent":"question","reply":"这个情况我帮您记录下来，稍后由审核同事和您进一步确认。"}',
        )
        assert decision.speak == GOODBYE, text
        assert decision.closed is True
        assert decision.result == "已知晓"
        assert decision.transfer is False
        assert "类似群" not in decision.speak
        assert "还有不清楚的吗" not in decision.speak
        assert "审核同事" not in decision.speak
    await hooks.after_turn(TurnRecord("好的，我明白了。超", GOODBYE, False, StageTimings(), []))
    files = list((tmp_path).glob("*.json"))
    assert len(files) == 1
    ticket = json.loads(files[0].read_text(encoding="utf-8"))
    assert ticket["result"] == "已知晓"
    assert ticket["source_row"] == 38
    assert ticket["mock"] is True


def test_acknowledgement_before_result_check_still_uses_the_existing_line():
    call = _confirmed(38)
    decision, _ = resolve_turn(
        call,
        "好的",
        '{"intent":"question","reply":"这个情况我帮您记录下来，稍后由审核同事和您进一步确认。"}',
    )
    assert decision.speak == RESULT_LINE
    assert decision.closed is False
    assert "审核同事" not in decision.speak


def test_reluctant_understanding_does_not_use_the_fallback():
    call = _confirmed(38)
    call.stage = "result"
    decision, _ = resolve_turn(
        call,
        "嗯，好吧，我明白了。",
        '{"intent":"question","reply":"这个情况我帮您记录下来，稍后由审核同事和您进一步确认。"}',
    )
    assert decision.speak == GOODBYE
    assert decision.closed is True
    assert decision.result == "已知晓"
    assert decision.transfer is False
    assert "审核同事" not in decision.speak
    stayed, _ = resolve_turn(
        call,
        "嗯，好吧，我明白了但是还有问题",
        '{"intent":"ack","reply":"感谢您的接听，祝您生活愉快，再见！"}',
    )
    assert stayed.closed is False
    assert stayed.speak != GOODBYE
    assert "审核同事" not in stayed.speak


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


_REPORTED = (
    "好的，我明白了。超",
    "嗯，好吧，我明白了。",
    "嗯好吧我明白了",
    "嗯好我明白了",
    "嗯好我明白了超",
    "好吧知道了",
    "哦，那行，清楚了",
    "我嗯明白了",
    "懂了啊",
    "没问题",
)


def _after_closing_question(stage: str):
    call = _confirmed(13)
    if stage == "ending":
        decision, _ = resolve_turn(call, "好的", '{"intent":"ack","reply":""}')
        assert decision.speak == RESULT_LINE
        call.commit(False)
    else:
        decision, _ = resolve_turn(call, "为什么", '{"intent":"question","reply":""}')
        assert "商标状态不符合要求" in decision.speak
        assert "还有不清楚的吗" in decision.speak
        call.commit(False)
    return call


@pytest.mark.parametrize("text", _REPORTED)
@pytest.mark.parametrize("intent", ("question", "unclear", "deny"))
@pytest.mark.parametrize("stage", ("why", "ending"))
def test_reported_understanding_closes_despite_model(text, intent, stage):
    call = _after_closing_question(stage)
    decision, _ = resolve_turn(
        call,
        text,
        '{"intent":"%s","reply":"这个情况我帮您记录下来，稍后由审核同事和您进一步确认。"}' % intent,
    )
    assert decision.speak == GOODBYE
    assert decision.closed is True
    assert decision.result == "已知晓"
    assert decision.transfer is False
    assert "？" not in decision.speak
    assert "审核同事" not in decision.speak
    assert "商标状态不符合要求" not in decision.speak


def test_nothing_and_yes_after_the_followup_are_not_the_same():
    call = _after_closing_question("why")
    for text in ("没有", "没了", "没有。", "没了啊"):
        decision, _ = resolve_turn(
            call,
            text,
            '{"intent":"question","reply":"这个情况我帮您记录下来，稍后由审核同事和您进一步确认。"}',
        )
        assert decision.speak == GOODBYE, text
        assert decision.closed is True
        assert "审核同事" not in decision.speak
    for text in ("嗯", "有", "嗯。", "有啊"):
        decision, _ = resolve_turn(
            call,
            text,
            '{"intent":"ack","reply":"感谢您的接听，祝您生活愉快，再见！"}',
        )
        assert decision.closed is False, text
        assert decision.speak == "您具体哪一句不清楚？"
        assert "审核同事" not in decision.speak
        assert "商标状态不符合要求" not in decision.speak


def test_understanding_combinations_only_say_goodbye():
    fillers = ("", "嗯", "好吧", "好", "哦", "行", "那", "对", "嗯好", "嗯好吧")
    words = ("明白了", "我明白了", "清楚了", "知道了", "懂了", "没问题", "没有了")
    marks = ("", "，", "。")
    noises = ("", "超", "啊")
    seen = 0
    for stage in ("why", "ending"):
        call = _after_closing_question(stage)
        for filler, word, mark, noise in (
            (filler, word, mark, noise)
            for filler in fillers
            for word in words
            for mark in marks
            for noise in noises
        ):
            text = f"{filler}{mark}{word}{mark}{noise}"
            for intent in ("question", "unclear", "deny"):
                decision, _ = resolve_turn(
                    call,
                    text,
                    '{"intent":"%s","reply":"这个情况我帮您记录下来，稍后由审核同事和您进一步确认。"}' % intent,
                )
                seen += 1
                assert decision.speak == GOODBYE, (stage, intent, text, decision.speak)
                assert decision.closed is True
                assert decision.result == "已知晓"
                assert decision.transfer is False
                assert "？" not in decision.speak
                assert "审核同事" not in decision.speak
                assert "商标状态不符合要求" not in decision.speak
    assert seen == 10 * 7 * 3 * 3 * 2 * 3
