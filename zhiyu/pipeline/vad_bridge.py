"""把 VAD 的四个状态收成两件事：用户开始说、用户说完了。

Silero 的状态是 QUIET → STARTING → SPEAKING → STOPPING → QUIET。
STARTING 还可能是一声咳嗽，要等它变成 SPEAKING 才打断客服。
STOPPING 表示正在确认尾音，要等回到 QUIET 才把这句交给大模型。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class VadTurnBridge:
    def __init__(
        self,
        on_speech_start: Callable[[], Awaitable[None]],
        on_speech_stop: Callable[[], Awaitable[None]],
    ) -> None:
        self._on_speech_start = on_speech_start
        self._on_speech_stop = on_speech_stop
        self._speaking = False

    @property
    def speaking(self) -> bool:
        return self._speaking

    async def update(self, state: str) -> None:
        name = state.lower()
        if name == "speaking" and not self._speaking:
            self._speaking = True
            await self._on_speech_start()
            return
        if name == "quiet" and self._speaking:
            self._speaking = False
            await self._on_speech_stop()
