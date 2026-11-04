"""对话引擎的假供应商。不连网络。"""

from __future__ import annotations

import asyncio


class ListSink:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.clears = 0

    async def play(self, pcm: bytes) -> None:
        self.chunks.append(pcm)

    async def clear(self) -> None:
        self.clears += 1


class ScriptedLLM:
    def __init__(self, text: str = "书已经到了。今天方便来取吗？") -> None:
        self.text = text
        self.messages: list[list[dict]] = []

    async def stream(self, messages):
        self.messages.append(messages)
        yield self.text


class BlockingLLM:
    """第一次调用停住，直到任务被取消。之后的调用正常出字。"""

    def __init__(self, text: str = "好的，我帮您记下。") -> None:
        self.text = text
        self.calls = 0
        self.started = asyncio.Event()
        self.messages: list[list[dict]] = []

    async def stream(self, messages):
        self.calls += 1
        self.messages.append(messages)
        if self.calls == 1:
            self.started.set()
            await asyncio.Future()
        yield self.text


class ScriptedTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.sample_rate = 24000
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def start(self) -> None:
        return None

    async def push_text(self, text: str) -> None:
        self.texts.append(text)
        await self._queue.put(b"\x01\x00" * 8)

    async def finish(self) -> None:
        await self._queue.put(None)

    async def audio_chunks(self):
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def cancel(self) -> None:
        await self._queue.put(None)


class TwoChunkTTS:
    """文本推进来之后先给一块音频，然后停住。用来观察打断会不会放第二块。"""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.sample_rate = 24000
        self.entered = asyncio.Event()
        self.hold = asyncio.Event()
        self._audio: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self) -> None:
        return None

    async def push_text(self, text: str) -> None:
        self.texts.append(text)
        await self._audio.put(b"\x01\x01")

    async def finish(self) -> None:
        return None

    async def audio_chunks(self):
        first = await self._audio.get()
        yield first
        # 第一块已经被播放协程取走之后再开门，测试才能断言缓冲里已经有声音。
        self.entered.set()
        await self.hold.wait()
        yield b"\x02\x02"

    async def cancel(self) -> None:
        # 不在这里放行 hold。任务取消时，等在 hold 上的生成器会收到 CancelledError。
        return None
