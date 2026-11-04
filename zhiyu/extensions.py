"""留给下一版的扩展点。

v1 只在两个时刻把一轮对话交出来，默认什么都不改：

- prepare_messages：大模型开口之前。以后在这里换系统提示词（状态机）、
  插入检索到的资料（RAG），或者决定要不要带上函数定义。
- after_turn：这一轮结束之后，不管有没有被用户打断。以后在这里把结果写成
  结构化 JSON、出质检报告，或把样本送进自评测循环。

函数调用本身还要改 LanguageModel 的返回值（文本以外还有 tool_call）。
v1 的模型接口只产出文本，所以这里先不接工具执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from zhiyu.pipeline.timing import StageTimings


@dataclass
class TurnRecord:
    """一轮用户发言和客服回复。被打断时 assistant_text 只保留已经生成的部分。"""

    user_text: str
    assistant_text: str
    interrupted: bool
    timings: StageTimings
    messages: list[dict[str, str]] = field(default_factory=list)


class AgentHooks(Protocol):
    async def prepare_messages(
        self, history: list[dict[str, str]], user_text: str
    ) -> list[dict[str, str]]:
        """返回这一轮真正发给大模型的消息。history 不含本轮用户文本。"""

    async def after_turn(self, record: TurnRecord) -> None:
        """一轮结束。实现里出错不应影响通话，引擎会把异常记到日志。"""


class DefaultHooks:
    """v1 的空实现：原样把历史加上用户这句话，结束时不做写回。"""

    async def prepare_messages(
        self, history: list[dict[str, str]], user_text: str
    ) -> list[dict[str, str]]:
        return [*history, {"role": "user", "content": user_text}]

    async def after_turn(self, record: TurnRecord) -> None:
        return None
