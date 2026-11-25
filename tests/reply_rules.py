"""对照资审模拟的书面边界，检查一段事先写好的回复。

这不是大模型，也不调用网络。不能据此说真实语音已经通过。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleVerdict:
    ok: bool
    reasons: tuple[str, ...]


_SENSITIVE = ("验证码", "密码", "银行卡", "身份证")
_PROMISE = ("保证通过", "一定能过", "包过")
_LEAKS = ("原表", "标准回答", "可引用", "没有引用", "查不到")


def judge_reply(user_text: str, reply: str) -> RuleVerdict:
    reasons: list[str] = []
    if any(word in reply for word in _SENSITIVE):
        reasons.append("回复索要或提及密码、验证码、银行卡或身份证")
    if any(word in reply for word in _PROMISE):
        reasons.append("回复保证审核通过")
    if any(word in reply for word in _LEAKS):
        reasons.append("回复暴露内部检索状态")
    confirmed = any(word in user_text for word in ("是的", "我是", "没错"))
    if not confirmed and any(word in reply for word in ("驳回", "图形商标")):
        reasons.append("身份未确认就说出驳回细节")
    return RuleVerdict(ok=not reasons, reasons=tuple(reasons))
