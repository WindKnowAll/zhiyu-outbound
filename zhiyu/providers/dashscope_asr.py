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


class DashScopeRecognizer:
    def __init__(
        self,
        *,
        api_key: str,
        ws_url: str,
        model: str,
        sample_rate: int = 16000,
    ) -> None:
        self._api_key = api_key
        self._ws_url = ws_url
        self._model = model
        self._sample_rate = sample_rate
        self._transcript_handler: Callable[[Transcript], Awaitable[None]] | None = None
        self._error_handler: Callable[[str], Awaitable[None]] | None = None
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self._run_task: asyncio.Task | None = None
        self._closed = False

    def set_transcript_handler(self, handler) -> None:
        self._transcript_handler = handler

    def set_error_handler(self, handler) -> None:
        self._error_handler = handler

    async def start(self) -> None:
        if self._run_task and not self._run_task.done():
            return
        self._closed = False
        self._run_task = asyncio.create_task(self._run(), name="dashscope-asr")

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed or not pcm:
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

    async def _fail(self, message: str) -> None:
        logger.error(message)
        if self._error_handler is not None:
            await self._error_handler(message)

    async def _run(self) -> None:
        task_id = str(uuid.uuid4())
        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=authorization_header(self._api_key),
                open_timeout=10,
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
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        message = json.loads(raw)
                        name = event_name(message)
                        if name == "task-finished":
                            break
                        transcript = parse_asr_message(message)
                        if transcript is not None and self._transcript_handler is not None:
                            await self._transcript_handler(transcript)
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
        except ProviderError as exc:
            await self._fail(str(exc))
        except Exception as exc:
            await self._fail(f"语音识别连接失败：{exc}")

    async def _wait_until(self, ws, expected: str) -> None:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            name = event_name(message)
            if name == expected:
                return
            # 定稿可能和 task-started 之后才来；等待期间忽略别的事件，失败要立刻抛。
            parse_asr_message(message)

    async def _send_audio(self, ws, task_id: str) -> None:
        while True:
            item = await self._audio.get()
            if item is None:
                await ws.send(dumps(finish_task(task_id=task_id)))
                return
            await ws.send(item)
