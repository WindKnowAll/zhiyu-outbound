"""本地 WebSocket，用来驱动真实的 DashScope 客户端。不访问百炼。"""

from __future__ import annotations

import json
import socket

from websockets.asyncio.server import serve


def closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class LocalWs:
    def __init__(self, handler) -> None:
        self._handler = handler
        self._server = None
        self.port = 0

    async def __aenter__(self) -> "LocalWs":
        self._server = await serve(self._handler, "127.0.0.1", 0)
        sockets = list(self._server.sockets)
        self.port = sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"


def started_event() -> str:
    return json.dumps({"header": {"event": "task-started"}}, ensure_ascii=False)


def failed_event(message: str) -> str:
    return json.dumps(
        {"header": {"event": "task-failed", "error_message": message}},
        ensure_ascii=False,
    )


def asr_final(text: str) -> str:
    return json.dumps(
        {
            "header": {"event": "result-generated"},
            "payload": {"output": {"sentence": {"text": text, "sentence_end": True}}},
        },
        ensure_ascii=False,
    )


def finished_event() -> str:
    return json.dumps({"header": {"event": "task-finished"}}, ensure_ascii=False)
