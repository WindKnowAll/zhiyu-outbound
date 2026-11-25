"""最终检查里的离线流程。调用现有引擎、会话和处理器，供应商用测试替身。"""

from __future__ import annotations

import pytest

from tests.fakes import ListSink, ScriptedLLM, ScriptedTTS
from zhiyu.config import load_persona, load_settings
from zhiyu.pipeline.engine import ConversationEngine
from zhiyu.session import CallSession, SessionHub
from zhiyu.transport.processor import VoiceSessionProcessor


class OrderLLM(ScriptedLLM):
    def __init__(self, log: list[str], text: str) -> None:
        super().__init__(text)
        self.log = log

    async def stream(self, messages):
        self.log.append("llm")
        async for token in super().stream(messages):
            yield token


class OrderTTS(ScriptedTTS):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    async def start(self) -> None:
        self.log.append("tts-start")
        await super().start()

    async def push_text(self, text: str) -> None:
        self.log.append("tts-text")
        await super().push_text(text)


def _engine(llm, factory, sink, **kwargs):
    persona = load_persona()
    return ConversationEngine(
        system_prompt=persona.system_prompt,
        language_model=llm,
        tts_factory=factory,
        sink=sink,
        finalize_timeout=kwargs.pop("finalize_timeout", 0),
        **kwargs,
    )


@pytest.mark.case(
    id="FLOW-01",
    scenario="建立通话会话",
    kind="离线实现",
    expected="同一个 pc_id 得到同一个会话，事件能按游标取出",
)
@pytest.mark.asyncio
async def test_session_open_and_events():
    hub = SessionHub()
    session = hub.open("pc-1")
    again = hub.open("pc-1")
    assert session is again
    session.add({"type": "status", "value": "connected"})
    assert hub.get("pc-1").since(0)[0]["type"] == "status"
    assert hub.get("missing") is None


@pytest.mark.case(
    id="FLOW-02",
    scenario="接通后的开场白",
    kind="离线实现",
    expected="只把 prompts/opening.txt 交给合成，不调用大模型",
)
@pytest.mark.asyncio
async def test_opening_uses_tts_not_llm():
    llm = ScriptedLLM("不应该出现。")
    made: list[ScriptedTTS] = []

    def factory():
        tts = ScriptedTTS()
        made.append(tts)
        return tts

    engine = _engine(llm, factory, ListSink())
    opening = load_persona().opening
    await engine.speak_fixed(opening)
    await engine.settle()
    assert llm.messages == []
    assert made[0].texts == [opening]
    assert engine.history[-1]["content"] == opening


@pytest.mark.case(
    id="FLOW-03",
    scenario="用户说完后的调用顺序",
    kind="离线实现",
    expected="现有引擎先 start 合成连接，再调用大模型，句子切出后再 push_text",
)
@pytest.mark.asyncio
async def test_llm_then_tts_order():
    log: list[str] = []
    llm = OrderLLM(log, "书已经到了。今天方便来取吗？")
    made: list[OrderTTS] = []

    def factory():
        tts = OrderTTS(log)
        made.append(tts)
        return tts

    engine = _engine(llm, factory, ListSink())
    await engine.user_started()
    await engine.on_transcript("在的。", True)
    await engine.user_stopped()
    await engine.settle()
    assert log[:3] == ["tts-start", "llm", "tts-text"]
    assert made[0].texts[0] == "书已经到了。"


@pytest.mark.case(
    id="FLOW-04",
    scenario="回复写入对话历史",
    kind="离线实现",
    expected="历史第一条是真实系统提示词，其后是用户句和客服回复",
)
@pytest.mark.asyncio
async def test_history_keeps_real_persona():
    llm = ScriptedLLM("好的，那今天方便来取吗？")
    engine = _engine(llm, ScriptedTTS, ListSink())
    await engine.user_started()
    await engine.on_transcript("方便。", True)
    await engine.user_stopped()
    await engine.settle()
    persona = load_persona()
    assert engine.history[0] == {"role": "system", "content": persona.system_prompt}
    assert engine.history[1]["content"] == "方便。"
    assert engine.history[2]["role"] == "assistant"
    assert llm.messages[0][0]["content"] == persona.system_prompt


@pytest.mark.case(
    id="FLOW-05",
    scenario="结束时释放引擎里的生成任务",
    kind="离线实现",
    expected="close 之后没有仍在运行的回复任务",
)
@pytest.mark.asyncio
async def test_engine_close_cancels_inflight():
    from tests.fakes import BlockingLLM

    llm = BlockingLLM()
    engine = _engine(llm, ScriptedTTS, ListSink())
    await engine.user_started()
    await engine.on_transcript("喂", True)
    await engine.user_stopped()
    await llm.started.wait()
    await engine.close()
    assert engine._task is None or engine._task.done()


class _FakeRecognizer:
    def __init__(self) -> None:
        self.stopped = 0
        self.handler = None
        self.error_handler = None

    def set_transcript_handler(self, handler) -> None:
        self.handler = handler

    def set_error_handler(self, handler) -> None:
        self.error_handler = handler

    async def start(self) -> None:
        return None

    async def send_audio(self, pcm: bytes) -> None:
        return None

    async def stop(self) -> None:
        self.stopped += 1


@pytest.mark.case(
    id="FLOW-06",
    scenario="处理器关闭时清理识别客户端",
    kind="离线实现",
    expected="shutdown 调用识别客户端的 stop，并且可以重复调用",
)
@pytest.mark.asyncio
async def test_processor_shutdown_stops_recognizer():
    settings = load_settings({"DASHSCOPE_API_KEY": "sk-offline-test"})
    persona = load_persona()
    recognizer = _FakeRecognizer()
    processor = VoiceSessionProcessor(
        settings=settings,
        persona=persona,
        session=CallSession(pc_id="pc-test"),
        recognizer=recognizer,
        language_model=ScriptedLLM(),
        tts_factory=ScriptedTTS,
    )
    await processor.shutdown()
    await processor.shutdown()
    assert recognizer.stopped == 1
