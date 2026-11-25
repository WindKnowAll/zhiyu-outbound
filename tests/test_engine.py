import asyncio

import pytest

from zhiyu.extensions import DefaultHooks
from zhiyu.pipeline.engine import ConversationEngine
from tests.fakes import BlockingLLM, ListSink, ScriptedLLM, ScriptedTTS, TwoChunkTTS


def _engine(llm, factory, sink, **kwargs):
    return ConversationEngine(
        system_prompt="你是小语。",
        language_model=llm,
        tts_factory=factory,
        sink=sink,
        finalize_timeout=kwargs.pop("finalize_timeout", 0),
        **kwargs,
    )


async def _say(engine: ConversationEngine, text: str, final: bool = True) -> None:
    await engine.user_started()
    await engine.on_transcript(text, final)
    await engine.user_stopped()
    await engine.settle()


@pytest.mark.asyncio
async def test_reply_streams_sentences_and_records_timings():
    llm = ScriptedLLM("书已经到了。今天方便来取吗？")
    made: list[ScriptedTTS] = []

    def factory():
        tts = ScriptedTTS()
        made.append(tts)
        return tts

    sink = ListSink()
    events: list[dict] = []

    async def listener(event: dict) -> None:
        events.append(event)

    engine = _engine(llm, factory, sink, listener=listener)
    await _say(engine, "在的。")

    assert [message["role"] for message in llm.messages[0]] == ["system", "user"]
    assert llm.messages[0][-1]["content"] == "在的。"
    assert made[0].texts == ["书已经到了。", "今天方便来取吗？"]
    assert len(sink.chunks) == 2
    latency = next(event for event in events if event["type"] == "latency")
    timings = latency["timings"]
    assert timings["asr_final_ms"] is not None
    assert timings["llm_first_token_ms"] is not None
    assert timings["tts_first_audio_ms"] is not None
    assert timings["first_audio_e2e_ms"] is not None
    assert latency["interrupted"] is False
    assert engine.history[-1]["role"] == "assistant"
    assert "今天方便来取吗？" in engine.history[-1]["content"]


@pytest.mark.asyncio
async def test_empty_utterance_does_not_call_the_model():
    llm = ScriptedLLM()
    engine = _engine(llm, ScriptedTTS, ListSink())
    await engine.user_started()
    await engine.user_stopped()
    await engine.settle()
    assert llm.messages == []


@pytest.mark.asyncio
async def test_final_transcript_replaces_partial_instead_of_appending():
    llm = ScriptedLLM("好的。")
    engine = _engine(llm, ScriptedTTS, ListSink())
    await engine.user_started()
    await engine.on_transcript("你好", False)
    await engine.on_transcript("你好。", True)
    await engine.user_stopped()
    await engine.settle()
    assert llm.messages[0][-1]["content"] == "你好。"


@pytest.mark.asyncio
async def test_short_pause_keeps_the_same_utterance():
    llm = ScriptedLLM("好的。")
    engine = _engine(llm, ScriptedTTS, ListSink(), finalize_timeout=0.3)
    await engine.user_started()
    await engine.on_transcript("你好", False)
    await engine.user_stopped()
    await engine.user_started()
    await engine.on_transcript("你好世界", False)
    await engine.user_stopped()
    await engine.settle()
    assert len(llm.messages) == 1
    assert llm.messages[0][-1]["content"] == "你好世界"


@pytest.mark.asyncio
async def test_barge_in_cancels_the_model_before_it_speaks():
    llm = BlockingLLM()
    made: list[ScriptedTTS] = []

    def factory():
        tts = ScriptedTTS()
        made.append(tts)
        return tts

    sink = ListSink()
    engine = _engine(llm, factory, sink)
    await engine.user_started()
    await engine.on_transcript("喂", True)
    await engine.user_stopped()
    await llm.started.wait()
    await engine.user_started()
    await engine.settle()
    assert sink.chunks == []
    assert made[0].texts == []
    assert sink.clears >= 1

    await engine.on_transcript("我在", True)
    await engine.user_stopped()
    await engine.settle()
    assert sink.chunks
    assert "好的，我帮您记下。" in made[-1].texts[0]


@pytest.mark.asyncio
async def test_barge_in_drops_audio_still_inside_tts():
    llm = ScriptedLLM("先说这一句。")
    made: list[TwoChunkTTS] = []

    def factory():
        tts = TwoChunkTTS()
        made.append(tts)
        return tts

    sink = ListSink()
    records = []

    class Hooks(DefaultHooks):
        async def after_turn(self, record) -> None:
            records.append(record)

    engine = _engine(llm, factory, sink, hooks=Hooks())
    await engine.user_started()
    await engine.on_transcript("在", True)
    await engine.user_stopped()
    for _ in range(50):
        if made:
            break
        await asyncio.sleep(0)
    await made[0].entered.wait()
    assert sink.chunks == [b"\x01\x01"]
    await engine.user_started()
    await engine.settle()
    assert sink.chunks == [b"\x01\x01"]
    assert records[-1].interrupted is True
    assert "可能没听完" in engine.history[-1]["content"]


@pytest.mark.asyncio
async def test_opening_line_can_be_interrupted():
    made: list[TwoChunkTTS] = []

    def factory():
        tts = TwoChunkTTS()
        made.append(tts)
        return tts

    sink = ListSink()
    engine = _engine(ScriptedLLM(), factory, sink)
    await engine.speak_fixed("您好，现在方便吗？")
    for _ in range(50):
        if made:
            break
        await asyncio.sleep(0)
    await made[0].entered.wait()
    await engine.user_started()
    await engine.settle()
    assert sink.chunks == [b"\x01\x01"]
    assert sink.clears >= 1


@pytest.mark.asyncio
async def test_prepare_messages_hook_can_change_the_prompt():
    llm = ScriptedLLM("好。")
    seen = {}

    class Hooks(DefaultHooks):
        async def prepare_messages(self, history, user_text):
            seen["user"] = user_text
            messages = await super().prepare_messages(history, user_text)
            messages[0] = {
                "role": "system",
                "content": history[0]["content"] + "只确认取书。",
            }
            return messages

        async def after_turn(self, record) -> None:
            seen["record"] = record

    engine = _engine(llm, ScriptedTTS, ListSink(), hooks=Hooks())
    await _say(engine, "方便")
    assert seen["user"] == "方便"
    assert "只确认取书" in llm.messages[0][0]["content"]
    assert seen["record"].interrupted is False
    assert seen["record"].user_text == "方便"


@pytest.mark.asyncio
async def test_listener_failure_does_not_stop_the_reply():
    async def broken(_event):
        raise RuntimeError("页面订阅挂了")

    sink = ListSink()
    engine = _engine(ScriptedLLM("好的。"), ScriptedTTS, sink, listener=broken)
    await _say(engine, "在")
    assert sink.chunks
