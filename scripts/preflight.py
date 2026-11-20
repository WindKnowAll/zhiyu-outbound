"""启动前检查。不读取 .env，因此不会打印或核验密钥。"""

from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("fastapi", "uvicorn", "websockets", "openai", "dotenv", "pipecat", "loguru")


def main() -> int:
    print(f"Python {sys.version.split()[0]}  {platform.platform()}")
    if sys.version_info < (3, 11):
        print("未通过：需要 Python 3.11 或 3.12，64 位。")
        return 1
    if sys.maxsize <= 2**32:
        print("未通过：当前是 32 位 Python。请安装 64 位。")
        return 1
    missing = []
    for name in REQUIRED:
        try:
            importlib.import_module(name)
        except Exception as exc:
            missing.append(f"{name} ({exc.__class__.__name__})")
    if missing:
        print("未通过：缺少依赖 " + ", ".join(missing))
        print("在仓库根目录执行：python -m pip install -r requirements-dev.txt")
        return 1
    env_file = ROOT / ".env"
    if env_file.exists():
        print("发现 .env。本预检不打开它，也不判断密钥是否有效。")
    else:
        print("没有 .env。离线测试仍可运行。真实接口和浏览器通话需要你在本机自己创建 .env。")
    print("预检通过：可以跑离线测试。真实百炼和麦克风不在这次预检里。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
