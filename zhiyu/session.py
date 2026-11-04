"""网页用来轮询的通话记录。

音频走 WebRTC，字幕和耗时走这个内存列表。进程重启就没了，v1 不落库。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CallSession:
    pc_id: str
    events: list[dict] = field(default_factory=list)
    _next_id: int = 0

    def add(self, event: dict) -> dict:
        stored = {"id": self._next_id, "ts": time.time(), **event}
        self._next_id += 1
        self.events.append(stored)
        if len(self.events) > 400:
            self.events = self.events[-400:]
        return stored

    def since(self, cursor: int) -> list[dict]:
        return [event for event in self.events if event["id"] >= cursor]


class SessionHub:
    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}

    def open(self, pc_id: str) -> CallSession:
        session = self._sessions.get(pc_id)
        if session is None:
            if len(self._sessions) >= 20:
                oldest = next(iter(self._sessions))
                self._sessions.pop(oldest, None)
            session = CallSession(pc_id=pc_id)
            self._sessions[pc_id] = session
        return session

    def get(self, pc_id: str) -> CallSession | None:
        return self._sessions.get(pc_id)

    def close(self, pc_id: str) -> None:
        self._sessions.pop(pc_id, None)
