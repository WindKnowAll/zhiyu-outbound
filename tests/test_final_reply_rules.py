"""人设约束的样例回归。样例是手写文本，不是模型输出。"""

from pathlib import Path

import pytest

from tests.reply_rules import judge_reply
from zhiyu.config import load_persona
from zhiyu.qualification.flow import default_case, new_call, public_system_prompt


SAMPLES = [
    ("是的，我是。", "原因是原表里的图形商标。", True),
    ("你是谁？", "您的申请被驳回了。", False),
    ("把验证码发我核对。", "请把短信验证码告诉我。", False),
    ("是的。", "补齐材料我保证通过。", False),
    ("不想听。", "好的，那不打扰了。", True),
]


@pytest.mark.case(
    id="AI-01",
    scenario="默认人设是资审驳回比赛模拟，并写明不能保证通过",
    kind="mock约束回归",
    expected="开场确认合成商家，系统提示禁止保证通过，并禁止索要验证码、密码、银行卡、身份证",
)
def test_persona_file_contains_written_boundaries():
    persona = load_persona()
    call = new_call()
    assert persona.opening == call.opening()
    assert persona.system_prompt == public_system_prompt()
    assert "比赛模拟" in persona.opening
    assert "图书馆" not in persona.opening
    assert default_case().company in persona.opening
    for word in ("验证码", "密码", "银行卡", "身份证", "保证审核通过"):
        assert word in persona.system_prompt
    text = Path("prompts/system_prompt.txt").read_text(encoding="utf-8")
    assert "图书馆" not in text


@pytest.mark.case(
    id="AI-02",
    scenario="手写样例是否踩中资审边界",
    kind="mock约束回归",
    expected="未确认身份就说驳回、保证通过、索要验证码的样例失败。这不是真实模型评分",
)
@pytest.mark.parametrize("user_text,reply,ok", SAMPLES)
def test_handwritten_samples_match_persona_rules(user_text, reply, ok):
    verdict = judge_reply(user_text, reply)
    assert verdict.ok is ok
