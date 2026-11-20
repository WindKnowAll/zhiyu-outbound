"""用本地端口驱动现有 DashScope 客户端。不访问百炼，不使用真实密钥。"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from tests.local_ws import (
    LocalWs,
    asr_final,
    closed_port,
    failed_event,
    finished_event,
    started_event,
)
from zhiyu.providers.base import ProviderError
from zhiyu.providers.dashscope_asr import DashScopeRecognizer
from zhiyu.providers.dashscope_llm import DashScopeChatModel
from zhiyu.providers.dashscope_tts import DashScopeSynthesizer

DUMMY_KEY = "sk-offline-test"


@pytest.mark.case(
    id="FLOW-07",
    scenario="识别服务端口拒绝连接",
    kind="离线网络失败",
    expected="现有 DashScopeRecognizer 把连接失败交给错误回调，且回调文本不含密钥",
)
@pytest.mark.asyncio
async def test_recognizer_connection_refused():
    errors: list[str] = []
    recognizer = DashScopeRecognizer(
        api_key=DUMMY_KEY,
        ws_url=f"ws://127.0.0.1:{closed_port()}",
        model="paraformer-realtime-v2",
        open_timeout=1,
        event_timeout=1,
    )

    async def on_error(message: str) -> None:
        errors.append(message)

    recognizer.set_error_handler(on_error)
    await recognizer.start()
    await recognizer.stop(timeout=3)
    assert errors
    assert "语音识别连接失败" in errors[0]
    assert DUMMY_KEY not in errors[0]


@pytest.mark.case(
    id="FLOW-08",
    scenario="识别等待 task-started 超时",
    kind="离线超时",
    expected="本地服务一直不回包时，现有客户端在给定超时内结束并上报失败",
)
@pytest.mark.asyncio
async def test_recognizer_times_out_waiting_for_start():
    async def hang(ws):
        try:
            await ws.recv()
            await ws.recv()
        except Exception:
            return

    errors: list[str] = []
    started = time.perf_counter()
    async with LocalWs(hang) as server:
        recognizer = DashScopeRecognizer(
            api_key=DUMMY_KEY,
            ws_url=server.url,
            model="paraformer-realtime-v2",
            open_timeout=1,
            event_timeout=0.4,
        )

        async def on_error(message: str) -> None:
            errors.append(message)

        recognizer.set_error_handler(on_error)
        await recognizer.start()
        await recognizer.stop(timeout=3)
        elapsed = time.perf_counter() - started
    assert errors
    assert DUMMY_KEY not in errors[0]
    assert elapsed < 5


@pytest.mark.case(
    id="FLOW-09",
    scenario="识别返回一句定稿",
    kind="离线协议",
    expected="现有客户端解析 result-generated，并把定稿交给回调",
)
@pytest.mark.asyncio
async def test_recognizer_receives_final_from_local_server():
    async def asr(ws):
        await ws.recv()
        await ws.send(started_event())
        while True:
            raw = await ws.recv()
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            if message["header"]["action"] == "finish-task":
                await ws.send(asr_final("在的。"))
                await ws.send(finished_event())
                return

    found: list[str] = []

    async def on_transcript(transcript) -> None:
        if transcript.is_final:
            found.append(transcript.text)

    async with LocalWs(asr) as server:
        recognizer = DashScopeRecognizer(
            api_key=DUMMY_KEY,
            ws_url=server.url,
            model="paraformer-realtime-v2",
            open_timeout=2,
            event_timeout=2,
        )
        recognizer.set_transcript_handler(on_transcript)
        await recognizer.start()
        await asyncio.sleep(0.2)
        await recognizer.send_audio(b"\x00\x00" * 160)
        await recognizer.stop(timeout=3)
    assert found == ["在的。"]


@pytest.mark.case(
    id="FLOW-10",
    scenario="合成服务返回 task-failed",
    kind="离线网络失败",
    expected="现有 DashScopeSynthesizer.start 抛出 ProviderError，且不含密钥",
)
@pytest.mark.asyncio
async def test_synthesizer_task_failed():
    async def fail(ws):
        await ws.recv()
        await ws.send(failed_event("配额不足"))

    async with LocalWs(fail) as server:
        tts = DashScopeSynthesizer(
            api_key=DUMMY_KEY,
            ws_url=server.url,
            model="cosyvoice-v2",
            voice="longxiaochun_v2",
            sample_rate=24000,
            open_timeout=2,
            event_timeout=2,
        )
        with pytest.raises(ProviderError) as raised:
            await tts.start()
    assert "配额不足" in str(raised.value)
    assert DUMMY_KEY not in str(raised.value)


@pytest.mark.case(
    id="FLOW-11",
    scenario="合成在本地按协议回一包音频",
    kind="离线协议",
    expected="现有客户端先等 task-started，再把二进制帧交给 audio_chunks",
)
@pytest.mark.asyncio
async def test_synthesizer_returns_audio_from_local_server():
    async def tts_server(ws):
        await ws.recv()
        await ws.send(started_event())
        while True:
            raw = await ws.recv()
            message = json.loads(raw)
            action = message["header"]["action"]
            if action == "continue-task":
                await ws.send(b"\x01\x00\x02\x00")
            if action == "finish-task":
                await ws.send(finished_event())
                return

    async with LocalWs(tts_server) as server:
        tts = DashScopeSynthesizer(
            api_key=DUMMY_KEY,
            ws_url=server.url,
            model="cosyvoice-v2",
            voice="longxiaochun_v2",
            sample_rate=24000,
            open_timeout=2,
            event_timeout=2,
        )
        await tts.start()
        await tts.push_text("图书馆的书到了。")
        await tts.finish()
        chunks = [chunk async for chunk in tts.audio_chunks()]
        await tts.cancel()
    assert chunks == [b"\x01\x00\x02\x00"]


@pytest.mark.case(
    id="FLOW-12",
    scenario="千问接口拒绝连接",
    kind="离线网络失败",
    expected="现有 DashScopeChatModel.stream 抛出 ProviderError，且不含密钥",
)
@pytest.mark.asyncio
async def test_llm_connection_refused():
    model = DashScopeChatModel(
        api_key=DUMMY_KEY,
        base_url=f"http://127.0.0.1:{closed_port()}/v1",
        model="qwen-plus",
        timeout=1,
    )
    with pytest.raises(ProviderError) as raised:
        async for _token in model.stream([{"role": "user", "content": "在吗"}]):
            pass
    assert "大模型请求失败" in str(raised.value)
    assert DUMMY_KEY not in str(raised.value)
