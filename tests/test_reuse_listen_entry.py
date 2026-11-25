"""直接运行 scripts/reuse_listen.py。不设置 PYTHONPATH，也不读取 .env。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zhiyu.build_id import PAGE_VERSION

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reuse_listen.py"
STATUS = {
    "ok": False,
    "missing": ["DASHSCOPE_API_KEY"],
    "dashscope_endpoint_source": "unset",
    "dashscope_host": "example.invalid",
}


def _env() -> dict[str, str]:
    skipped = {"PYTHONPATH"}
    return {
        key: value
        for key, value in os.environ.items()
        if key not in skipped and not key.startswith("DASHSCOPE") and "KEY" not in key and "SECRET" not in key and "TOKEN" not in key
    }


def _run(port: int, cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--port", str(port)],
        cwd=cwd,
        env=_env(),
        capture_output=True,
        timeout=8,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
    )


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Page(ThreadingHTTPServer):
    def __init__(self, html: str) -> None:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/api/status"):
                    body = json.dumps(STATUS).encode("utf-8")
                    content_type = "application/json"
                else:
                    body = parent.html.encode("utf-8")
                    content_type = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args) -> None:
                return

        self.html = html
        super().__init__(("127.0.0.1", 0), Handler)


def _serve(html: str):
    server = _Page(html)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_script_starts_from_another_directory_without_pythonpath(tmp_path: Path):
    completed = _run(_free_port(), tmp_path)
    assert completed.returncode == 0
    assert "PORT_FREE" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr
    assert tmp_path.resolve() != ROOT.resolve()


def test_existing_current_page_is_reused_and_old_page_is_refused(tmp_path: Path):
    current = (
        "<html><title>智语外呼</title><h1>智语外呼</h1>"
        f"<p>比赛模拟 {PAGE_VERSION}</p></html>"
    )
    server, thread = _serve(current)
    try:
        host, port = server.server_address
        assert host == "127.0.0.1"
        completed = _run(port, tmp_path)
        assert completed.returncode == 10
        assert "ALREADY" in completed.stdout
        assert PAGE_VERSION in completed.stdout
        assert "ModuleNotFoundError" not in completed.stderr
    finally:
        server.shutdown()
        thread.join(timeout=3)

    stale, stale_thread = _serve("<html><h1>星河大学图书馆</h1><p>取书</p></html>")
    try:
        refused = _run(stale.server_address[1], tmp_path)
        assert refused.returncode == 12
        assert "STALE" in refused.stdout
        assert "ModuleNotFoundError" not in refused.stderr
    finally:
        stale.shutdown()
        stale_thread.join(timeout=3)
