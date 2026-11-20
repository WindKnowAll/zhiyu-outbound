"""检查相对用户安装基线 f0d6e4a 的增量文件是否带齐新测试的 import。"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_BASELINE = "f0d6e4a"


def changed_files(baseline: str = INSTALL_BASELINE, head: str = "HEAD") -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--name-only", f"{baseline}..{head}"],
        cwd=ROOT,
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _show(baseline: str, rel: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{baseline}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def imported_from_scripts(source: str) -> list[tuple[str, str]]:
    tree = ast.parse(source)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("scripts."):
            for alias in node.names:
                found.append((node.module, alias.name))
    return found


def missing_patch_files(baseline: str = INSTALL_BASELINE, head: str = "HEAD") -> list[str]:
    """返回基线里没有、但新测试 import 了，却未列入增量的模块路径。"""

    files = set(changed_files(baseline, head))
    missing: list[str] = []
    for rel in sorted(files):
        if not rel.endswith(".py"):
            continue
        source = (ROOT / rel).read_text(encoding="utf-8")
        for module, name in imported_from_scripts(source):
            mod_path = module.replace(".", "/") + ".py"
            current = (ROOT / mod_path).read_text(encoding="utf-8")
            if f"def {name}" not in current and f"class {name}" not in current:
                missing.append(f"{rel} 需要 {mod_path} 中的 {name}，当前文件没有这个定义")
                continue
            baseline_source = _show(baseline, mod_path)
            baseline_has = baseline_source is not None and (
                f"def {name}" in baseline_source or f"class {name}" in baseline_source
            )
            if not baseline_has and mod_path not in files:
                missing.append(f"{rel} 新增使用 {name}，增量包必须包含 {mod_path}")
    return missing
