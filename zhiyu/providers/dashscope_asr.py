"""Paraformer 实时识别。

一条 WebSocket 维持整通电话：持续把 16 kHz PCM 推上去，
服务端用 result-generated 回部分结果和句末定稿。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable

import websockets
from loguru import logger

from zhiyu.providers.base import ProviderError, Transcript
from zhiyu.providers.messages import (
    asr_run_task,
    authorization_header,
    dumps,
    event_name,
    finish_task,
    parse_asr_message,
)

# 与 websockets 17.4 的默认值相同：20 秒发一次协议 ping，20 秒内没有 pong 就由客户端发 1011。
# 这里写明是为了让调用处看得见，不把窗口加大。加大会把对端没回 pong 和本机读不到 pong 混在一起。
_PING_INTERVAL = 20.0
_PING_TIMEOUT = 20.0


class DashScopeRecognizer:
    def __init__(
        self,
        *,
        api_key: str,
        ws_url: str,
        model: str,
        sample_rate: int = 16000,
        open_timeout: float = 10,
        event_timeout: float = 10,
        ping_interval: float | None = _PING_INTERVAL,
        ping_timeout: float | None = _PING_TIMEOUT,
        close_timeout: float | None = 10,
    ) -> None:
        # 默认 10 秒与原来写死的值相同。测试传入更短的时间，才能在本地挂起端口上验证超时分支。
        self._api_key = api_key
        self._ws_url = ws_url
        self._model = model
        self._sample_rate = sample_rate
        self._open_timeout = open_timeout
        self._event_timeout = event_timeout
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._close_timeout = close_timeout
        self._transcript_handler: Callable[[Transcript], Awaitable[None]] | None = None
        self._error_handler: Callable[[str], Awaitable[None]] | None = None
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self._inbound: asyncio.Queue[Transcript | None] = asyncio.Queue()
        self._run_task: asyncio.Task | None = None
        self._closed = False
        self._failed = False
        self._reported = False

    def set_transcript_handler(self, handler) -> None:
        self._transcript_handler = handler

    def set_error_handler(self, handler) -> None:
        self._error_handler = handler

    async def start(self) -> None:
        if self._run_task and not self._run_task.done():
            return
        # 新的一条连接不带走上一条里没送出去的音频，避免同一段声音被再识别一次。
        self._drop_audio()
        self._closed = False
        self._failed = False
        self._reported = False
        self._run_task = asyncio.create_task(self._run(), name="dashscope-asr")

    async def retry(self) -> bool:
        """手动再连一次。不自动调用，也不重放已经排队的音频。"""

        if self._run_task and not self._run_task.done():
            return False
        await self.start()
        return True

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed or self._failed or not pcm:
            return
        self._offer(pcm)

    async def stop(self, timeout: float = 8) -> None:
        self._closed = True
        self._offer(None)
        task = self._run_task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()

    def _offer(self, item: bytes | None) -> None:
        try:
            self._audio.put_nowait(item)
        except asyncio.QueueFull:
            # 队列积压说明网络跟不上。丢掉最旧的一帧，保留最新的声音。
            try:
                self._audio.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._audio.put_nowait(item)
            except asyncio.QueueFull:
                pass

    def _drop_audio(self) -> None:
        while True:
            try:
                self._audio.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _drain_inbound(self) -> None:
        while True:
            try:
                self._inbound.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _fail(self, message: str) -> None:
        self._failed = True
        self._drop_audio()
        if self._reported:
            return
        self._reported = True
        logger.error(message)
        if self._error_handler is not None:
            await self._error_handler(message)

    async def _run(self) -> None:
        task_id = str(uuid.uuid4())
        try:
            self._drain_inbound()
            async with websockets.connect(
                self._ws_url,
                additional_headers=authorization_header(self._api_key),
                open_timeout=self._open_timeout,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_timeout,
                close_timeout=self._close_timeout,
                max_size=8 * 1024 * 1024,
                proxy=None,
            ) as ws:
                await ws.send(
                    dumps(
                        asr_run_task(
                            task_id=task_id,
                            model=self._model,
                            sample_rate=self._sample_rate,
                        )
                    )
                )
                await self._wait_until(ws, "task-started")
                sender = asyncio.create_task(self._send_audio(ws, task_id), name="asr-send")
                # 读套接字的循环不能等对话回调。回调一慢，接收队列满了就会暂停读，
                # 协议层的 pong 也进不来，库会按 keepalive ping timeout 发 1011。
                dispatcher = asyncio.create_task(self._dispatch(), name="asr-dispatch")
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        message = json.loads(raw)
                        name = event_name(message)
                        if name == "task-finished":
                            break
                        transcript = parse_asr_message(message)
                        if transcript is not None:
                            self._inbound.put_nowait(transcript)
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
                    await self._inbound.put(None)
                    await dispatcher
        except ProviderError as exc:
            await self._fail(str(exc))
        except Exception as exc:
            await self._fail(
                f"语音识别连接失败：{exc}。识别已停止，不会自动重连，也不会重发已排队的音频。"
            )

    async def _wait_until(self, ws, expected: str) -> None:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=self._event_timeout)
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            name = event_name(message)
            if name == expected:
                return
            # 定稿可能和 task-started 之后才来；等待期间忽略别的事件，失败要立刻抛。
            parse_asr_message(message)

    async def _dispatch(self) -> None:
        while True:
            transcript = await self._inbound.get()
            if transcript is None:
                return
            handler = self._transcript_handler
            if handler is None:
                continue
            try:
                await handler(transcript)
            except Exception:
                # 同一条转写不再送第二次，避免同一轮意图和工单写两遍。
                logger.exception("识别结果没有送进对话")

    async def _send_audio(self, ws, task_id: str) -> None:
        while True:
            item = await self._audio.get()
            if item is None:
                await ws.send(dumps(finish_task(task_id=task_id)))
                return
            await ws.send(item)
