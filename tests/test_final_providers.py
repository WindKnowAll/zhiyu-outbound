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
        await tts.push_text("收到，我再确认一下。")
        await tts.finish()
        chunks = [chunk async for chunk in tts.audio_chunks()]
        await tts.cancel()
    assert chunks == [b"\x01\x00\x02\x00"]


def _partial(text: str) -> str:
    return json.dumps(
        {
            "header": {"event": "result-generated"},
            "payload": {"output": {"sentence": {"text": text, "sentence_end": False}}},
        },
        ensure_ascii=False,
    )


def _recognizer(url: str, **kwargs) -> DashScopeRecognizer:
    values = {
        "api_key": DUMMY_KEY,
        "ws_url": url,
        "model": "paraformer-realtime-v2",
        "open_timeout": 2,
        "event_timeout": 2,
        "ping_interval": 0.2,
        "ping_timeout": 0.3,
        "close_timeout": 0.2,
    }
    values.update(kwargs)
    return DashScopeRecognizer(**values)


@pytest.mark.case(
    id="FLOW-13",
    scenario="识别回调变慢时结果继续涌入",
    kind="离线心跳",
    expected="读套接字不等待回调，连接不被 keepalive ping timeout 关掉，转写只交付一次",
)
@pytest.mark.asyncio
async def test_slow_transcript_handler_does_not_starve_keepalive():
    async def flood(ws):
        await ws.recv()
        await ws.send(started_event())
        for index in range(30):
            await ws.send(_partial(f"字{index}"))
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.2)

    errors: list[str] = []
    got: list[str] = []

    async def on_error(message: str) -> None:
        errors.append(message)

    async def on_transcript(transcript) -> None:
        got.append(transcript.text)
        if len(got) == 1:
            await asyncio.sleep(0.8)

    async with LocalWs(flood) as server:
        recognizer = _recognizer(server.url)
        recognizer.set_error_handler(on_error)
        recognizer.set_transcript_handler(on_transcript)
        await recognizer.start()
        await asyncio.sleep(1.5)
        await recognizer.stop(timeout=3)
    assert errors == []
    assert got == [f"字{index}" for index in range(30)]
    assert DUMMY_KEY not in "".join(got)


@pytest.mark.case(
    id="FLOW-14",
    scenario="对端不回协议 pong",
    kind="离线心跳",
    expected="仍然报 keepalive ping timeout 一次，不自动重连，不重放旧音频",
)
@pytest.mark.asyncio
async def test_peer_that_never_pongs_is_reported_once_and_not_replayed():
    import base64
    import hashlib
    import struct

    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accepted: list[int] = []
    seen: list[bytes] = []
    writers: list[asyncio.StreamWriter] = []

    def text_frame(text: str) -> bytes:
        payload = text.encode()
        if len(payload) < 126:
            header = bytes([0x81, len(payload)])
        else:
            header = bytes([0x81, 126]) + struct.pack("!H", len(payload))
        return header + payload

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.append(1)
        writers.append(writer)
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = await reader.read(4096)
            if not chunk:
                return
            request += chunk
        key = ""
        for line in request.decode("latin1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1((key + guid).encode()).digest()).decode()
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        writer.write(text_frame(started_event()))
        await writer.drain()
        try:
            while True:
                header = await reader.readexactly(2)
                length = header[1] & 0x7F
                if length == 126:
                    length = struct.unpack("!H", await reader.readexactly(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", await reader.readexactly(8))[0]
                mask = await reader.readexactly(4) if header[1] & 0x80 else b""
                payload = await reader.readexactly(length)
                if mask:
                    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
                if header[0] & 0x0F == 0x2:
                    seen.append(payload)
                # 故意不回 pong。
        except Exception:
            return

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    errors: list[str] = []

    async def on_error(message: str) -> None:
        errors.append(message)

    recognizer = _recognizer(f"ws://127.0.0.1:{port}")
    recognizer.set_error_handler(on_error)
    try:
        await recognizer.start()
        await recognizer.send_audio(b"\x01\x02")
        for _ in range(30):
            if errors:
                break
            await asyncio.sleep(0.1)
        assert len(errors) == 1
        assert "keepalive ping timeout" in errors[0]
        assert "不会自动重连" in errors[0]
        assert DUMMY_KEY not in errors[0]
        stale = b"\x03\x04"
        fresh = b"\x05\x06"
        await recognizer.send_audio(stale)
        connections_before_retry = len(accepted)
        assert await recognizer.retry()
        await recognizer.send_audio(fresh)
        for _ in range(20):
            if fresh in seen:
                break
            await asyncio.sleep(0.05)
        await recognizer.stop(timeout=2)
        assert len(accepted) == connections_before_retry + 1
        assert stale not in seen
        assert fresh in seen
        assert not any(message.count("keepalive ping timeout") > 1 for message in errors)
    finally:
        for writer in writers:
            writer.close()
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), timeout=1)
        except TimeoutError:
            pass
        await recognizer.stop(timeout=1)


@pytest.mark.case(
    id="FLOW-15",
    scenario="大模型用异步等待，识别心跳仍在",
    kind="离线心跳",
    expected="事件循环里的 await 不会造成 keepalive ping timeout",
)
@pytest.mark.asyncio
async def test_async_wait_does_not_drop_the_recognizer():
    async def idle(ws):
        await ws.recv()
        await ws.send(started_event())
        await asyncio.sleep(0.8)
        await ws.send(_partial("还在"))
        await asyncio.sleep(0.2)

    errors: list[str] = []
    got: list[str] = []

    async def on_error(message: str) -> None:
        errors.append(message)

    async def on_transcript(transcript) -> None:
        got.append(transcript.text)

    async with LocalWs(idle) as server:
        recognizer = _recognizer(server.url)
        recognizer.set_error_handler(on_error)
        recognizer.set_transcript_handler(on_transcript)
        await recognizer.start()
        await asyncio.sleep(0.7)
        await asyncio.sleep(0.5)
        await recognizer.stop(timeout=3)
    assert errors == []
    assert got == ["还在"]


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
