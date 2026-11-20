"""把当前源码和一份已生成的报告打成 zip。不放入 .env、缓存和虚拟环境。"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "reports"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


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
            archive.write(path, rel.as_posix())
        for path in report.rglob("*"):
            if path.is_file():
                archive.write(path, f"reports/this-run/{path.name}")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
