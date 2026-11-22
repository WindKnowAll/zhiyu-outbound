"""同机 coturn 的短期凭据。

长期密钥只留在环境变量里。发给浏览器和 aiortc 的是几分钟内有效的用户名和
HMAC，不是那把长期密钥。aiortc 只使用列表里的第一台 STUN 和第一台 TURN，
所以服务器侧只放一条指向本机私网的 UDP TURN。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from pipecat.transports.smallwebrtc.connection import IceServer

RELAY_MIN = 49152
RELAY_MAX = 49251


class TurnConfig:
    def __init__(
        self,
        *,
        secret: str = "",
        public_host: str = "",
        listen_host: str = "",
        port: int = 3478,
        ttl_seconds: int = 600,
        min_port: int = RELAY_MIN,
        max_port: int = RELAY_MAX,
    ) -> None:
        self.secret = secret.strip()
        self.public_host = public_host.strip()
        self.listen_host = listen_host.strip()
        self.port = port
        self.ttl_seconds = min(3600, max(120, ttl_seconds))
        self.min_port = min_port
        self.max_port = max_port

    @property
    def enabled(self) -> bool:
        return len(self.secret) >= 16 and bool(self.public_host) and bool(self.listen_host)

    def mint(self, label: str, now: int | None = None) -> tuple[str, str]:
        """coturn use-auth-secret：用户名是过期时间，密码是 HMAC-SHA1。"""

        if not self.enabled:
            raise RuntimeError("TURN 没有启用。")
        moment = int(time.time()) if now is None else now
        username = f"{moment + self.ttl_seconds}:{label}"
        digest = hmac.new(self.secret.encode(), username.encode(), hashlib.sha1).digest()
        return username, base64.b64encode(digest).decode()

    def browser_servers(self, stun_urls: tuple[str, ...] | list[str], now: int | None = None) -> list[dict]:
        servers: list[dict] = [{"urls": url} for url in stun_urls]
        if not self.enabled:
            return servers
        username, credential = self.mint("browser", now)
        for transport in ("udp", "tcp"):
            servers.append(
                {
                    "urls": f"turn:{self.public_host}:{self.port}?transport={transport}",
                    "username": username,
                    "credential": credential,
                }
            )
        return servers

    def aiortc_servers(self, stun_urls: tuple[str, ...] | list[str], now: int | None = None) -> list[IceServer]:
        """私网地址给本机 aiortc。它不会使用第二条 TURN，也不要让它去访问自己的公网地址。"""

        servers = [IceServer(urls=url) for url in stun_urls]
        if not self.enabled:
            return servers
        username, credential = self.mint("aiortc", now)
        servers.append(
            IceServer(
                urls=f"turn:{self.listen_host}:{self.port}?transport=udp",
                username=username,
                credential=credential,
            )
        )
        return servers


def load_turn(env: dict[str, str]) -> TurnConfig:
    def text(name: str, default: str = "") -> str:
        return (env.get(name) or default).strip()

    def number(name: str, default: int) -> int:
        raw = text(name)
        if not raw:
            return default
        return int(raw)

    return TurnConfig(
        secret=text("ZHIYU_TURN_SECRET"),
        public_host=text("ZHIYU_TURN_PUBLIC_HOST"),
        listen_host=text("ZHIYU_TURN_LISTEN_HOST"),
        port=number("ZHIYU_TURN_PORT", 3478),
        ttl_seconds=number("ZHIYU_TURN_TTL", 600),
        min_port=number("ZHIYU_TURN_MIN_PORT", RELAY_MIN),
        max_port=number("ZHIYU_TURN_MAX_PORT", RELAY_MAX),
    )
