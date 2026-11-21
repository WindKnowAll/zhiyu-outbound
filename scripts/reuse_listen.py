"""启动前看 127.0.0.1 上是不是已经有本项目。

退出码：
0  端口空闲，调用方可以启动
10 已确认是本项目的只读页面和 /api/status，调用方不要再启动
11 端口被占用，但不是本项目；调用方不要结束那个进程，也不要改端口

不读取 .env，不打印响应正文。
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request

PAGE_MARKS = ("智语外呼", "比赛模拟")


def is_this_app(html: str, status_code: int, status_body: str) -> bool:
    """同时核对首页固定标题和 /api/status 的字段形状。缺一不可。"""

    if status_code != 200:
        return False
    if any(mark not in html for mark in PAGE_MARKS):
        return False
    try:
        data = json.loads(status_body)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    return (
        isinstance(data.get("ok"), bool)
        and isinstance(data.get("missing"), list)
        and isinstance(data.get("dashscope_endpoint_source"), str)
        and isinstance(data.get("dashscope_host"), str)
    )


def listening_pids(netstat_text: str, port: int) -> list[str]:
    """从 netstat 文本里取出正在监听该端口的 PID。不匹配更长的端口号。"""

    found: list[str] = []
    wanted = str(port)
    for line in netstat_text.splitlines():
        upper = line.upper()
        if "LISTENING" not in upper and " LISTEN " not in f" {upper} ":
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[1]
        _host, sep, port_text = local.rpartition(":")
        if sep != ":" or port_text != wanted:
            continue
        pid = parts[-1]
        if pid.isdigit() and pid not in found:
            found.append(pid)
    return found


def _read(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(200_000)
            return response.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read(20_000)
        return exc.code, raw.decode("utf-8", errors="replace")


def port_accepts(port: int, timeout: float) -> bool:
    """只看本机是否有人接受连接。连不上视为空闲。"""

    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def classify(port: int, timeout: float = 2.0) -> str:
    """返回 free、ours 或 other。不读取 .env。"""

    if not port_accepts(port, timeout):
        return "free"
    base = f"http://127.0.0.1:{port}"
    try:
        page_code, html = _read(base + "/", timeout)
        status_code, body = _read(base + "/api/status", timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return "other"
    if page_code == 200 and is_this_app(html, status_code, body):
        return "ours"
    return "other"


def windows_listening_pids(port: int) -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return listening_pids(completed.stdout, port)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查本机端口是否已是智语外呼")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    kind = classify(args.port)
    if kind == "free":
        print(f"PORT_FREE {args.port}")
        return 0
    if kind == "ours":
        print(f"ALREADY http://127.0.0.1:{args.port}")
        print("已有本项目页面。请直接打开上面的地址，不要再启动第二个进程。")
        return 10
    pids = windows_listening_pids(args.port)
    pid_text = ",".join(pids) if pids else "未知"
    print(f"OCCUPIED port={args.port} pid={pid_text}")
    print("7860 被别的程序占用。本脚本不会结束它，也不会改用别的端口。")
    return 11


if __name__ == "__main__":
    raise SystemExit(main())
