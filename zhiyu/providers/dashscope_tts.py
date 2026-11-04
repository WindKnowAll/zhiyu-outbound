"""CosyVoice 流式合成。

一次回复开一条连接。文本按句推送，音频从二进制帧里读出来。
CosyVoice 会把没写完的句子先攒着，所以调用方应送已经断好的句子，
第一句才能马上出声。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import websockets
from loguru import logger

from zhiyu.providers.base import ProviderError
from zhiyu.providers.messages import (
    authorization_header,
    dumps,
    event_name,
    finish_task,
    tts_continue_task,
    tts_run_task,
)


class DashScopeSynthesizer:
    def __init__(
        self,
        *,
        api_key: str,
        ws_url: str,
        model: str,
        voice: str,
        sample_rate: int,
    ) -> None:
        self._api_key = api_key
        self._ws_url = ws_url
        self._model = model
        self._voice = voice
        self._sample_rate = sample_rate
        self._ws = None
        self._task_id = ""
        self._audio: asyncio.Queue[bytes | None | Exception] = asyncio.Queue()
        self._reader: asyncio.Task | None = None
        self._started = False

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def start(self) -> None:
        await self.cancel()
        self._audio = asyncio.Queue()
        self._task_id = str(uuid.uuid4())
        try:
            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers=authorization_header(self._api_key),
                open_timeout=10,
                max_size=8 * 1024 * 1024,
                proxy=None,
            )
            await self._ws.send(
                dumps(
                    tts_run_task(
                        task_id=self._task_id,
                        model=self._model,
                        voice=self._voice,
                        sample_rate=self._sample_rate,
                    )
                )
            )
            await self._wait_until("task-started")
        except ProviderError:
            await self.cancel()
            raise
        except Exception as exc:
            await self.cancel()
            raise ProviderError(f"语音合成连接失败：{exc}") from exc
        self._started = True
        self._reader = asyncio.create_task(self._read(), name="dashscope-tts")

    async def push_text(self, text: str) -> None:
        if not self._started or self._ws is None:
            raise ProviderError("语音合成还没开始，不能发送文本。")
        cleaned = text.strip()
        if not cleaned:
            return
        await self._ws.send(dumps(tts_continue_task(task_id=self._task_id, text=cleaned)))

    async def finish(self) -> None:
        if not self._started or self._ws is None:
            return
        await self._ws.send(dumps(finish_task(task_id=self._task_id)))

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._audio.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            if item:
                yield item

    async def cancel(self) -> None:
        self._started = False
        reader = self._reader
        self._reader = None
        if reader is not None and not reader.done():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                logger.debug("关闭语音合成连接时出现异常，已忽略")
        # 让还堵在 audio_chunks 上的消费者退出。
        await self._audio.put(None)

    async def _wait_until(self, expected: str) -> None:
        assert self._ws is not None
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            name = event_name(message)
            if name == expected:
                return
            if name == "task-failed":
                header = message.get("header") or {}
                detail = header.get("error_message") or header.get("error_code") or "合成任务失败"
                raise ProviderError(f"语音合成失败：{detail}")

    async def _read(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    await self._audio.put(raw)
                    continue
                message = json.loads(raw)
                name = event_name(message)
                if name == "task-finished":
                    await self._audio.put(None)
                    return
                if name == "task-failed":
                    header = message.get("header") or {}
                    detail = header.get("error_message") or "合成任务失败"
                    await self._audio.put(ProviderError(f"语音合成失败：{detail}"))
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._audio.put(ProviderError(f"语音合成中断：{exc}"))
