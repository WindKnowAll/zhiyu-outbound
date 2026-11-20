"""把当前源码和一份已生成的报告打成 zip。不放入 .env、缓存和虚拟环境。"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "reports"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def normalize_bat_bytes(data: bytes) -> bytes:
    """把 bat 收成 UTF-8、无 BOM、每行 CR LF。打包时无论工作区是哪种换行都走这里。"""

    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


def assert_crlf_bat(data: bytes, name: str) -> None:
    if data.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"{name} 带了 UTF-8 BOM")
    if b"\r\n" not in data:
        raise AssertionError(f"{name} 没有 CR LF")
    stripped = data.replace(b"\r\n", b"")
    if b"\n" in stripped or b"\r" in stripped:
        raise AssertionError(f"{name} 存在单独的 LF 或 CR")
    data.decode("utf-8")


def _allowed(path: Path) -> bool:
    if path.name == ".env" or path.name.endswith(".env"):
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix in SKIP_SUFFIXES:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, help="run_final_check.py 写出的目录")
    parser.add_argument("--zip", required=True)
    args = parser.parse_args()
    report = Path(args.report)
    destination = Path(args.zip)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if not _allowed(rel) or not path.is_file():
                continue
            payload = path.read_bytes()
            if path.suffix.lower() == ".bat":
                payload = normalize_bat_bytes(payload)
                assert_crlf_bat(payload, rel.as_posix())
            archive.writestr(rel.as_posix(), payload)
        for path in report.rglob("*"):
            if path.is_file():
                archive.write(path, f"reports/this-run/{path.name}")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
