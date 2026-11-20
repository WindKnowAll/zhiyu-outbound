"""运行离线测试并写出逐项报告。不调用百炼，不读取 .env。"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo  # Windows 需 requirements-dev.txt 里的 tzdata；Linux 用系统时区库

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.not_run_manifest import conclusion_text, not_run_cases


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception as exc:
        return f"未知（{exc.__class__.__name__}）"


def _status_from_outcome(outcome: str) -> str:
    if outcome == "passed":
        return "通过"
    if outcome == "skipped":
        return "未测试"
    return "未通过"


def _merge(pytest_payload: dict) -> list[dict]:
    grouped: dict[str, dict] = {}
    appendix: list[dict] = []
    for item in pytest_payload.get("results", []):
        case_id = item.get("id") or ""
        status = _status_from_outcome(item.get("outcome", ""))
        actual = "pytest " + item.get("outcome", "")
        if item.get("longrepr") and status != "通过":
            actual = item["longrepr"]
        row = {
            "id": case_id,
            "scenario": item.get("scenario") or item.get("nodeid"),
            "test_type": item.get("kind") or "pytest",
            "expected": item.get("expected") or "测试断言成立",
            "actual": actual,
            "status": status,
            "reason": "" if status == "通过" else (item.get("longrepr") or item.get("outcome")),
            "nodeid": item.get("nodeid", ""),
            "duration_sec": item.get("duration_sec", 0),
        }
        if not case_id:
            row["id"] = "PY-" + str(len(appendix) + 1)
            appendix.append(row)
            continue
        previous = grouped.get(case_id)
        if previous is None or status == "未通过" or previous["status"] == "通过":
            if previous and previous["status"] == "未通过":
                continue
            grouped[case_id] = row
    ordered = list(grouped.values())
    ordered.sort(key=lambda row: row["id"])
    return ordered + appendix


def _html(report: dict) -> str:
    rows = []
    for case in report["cases"]:
        rows.append(
            "<tr>"
            f"<td>{_esc(case['id'])}</td>"
            f"<td>{_esc(case['scenario'])}</td>"
            f"<td>{_esc(case['test_type'])}</td>"
            f"<td>{_esc(case['expected'])}</td>"
            f"<td>{_esc(case['actual'])}</td>"
            f"<td>{_esc(case['status'])}</td>"
            f"<td>{_esc(case['reason'])}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>智语外呼最终测试报告</title>
<style>
body {{ font-family: "Segoe UI", "PingFang SC", sans-serif; margin: 24px; color: #1c1915; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #e4d9c8; padding: 8px; vertical-align: top; font-size: 14px; }}
th {{ background: #f6f1e8; text-align: left; }}
.通过 {{ color: #154832; }} .未通过 {{ color: #9a4630; }} .未测试, .未实现 {{ color: #8a5a12; }}
</style>
</head>
<body>
<h1>智语外呼最终测试报告</h1>
<p>{_esc(report['conclusion'])}</p>
<ul>
<li>时间（Asia/Shanghai）：{_esc(report['generated_at'])}</li>
<li>提交：{_esc(report['commit'])}</li>
<li>分支：{_esc(report['branch'])}</li>
<li>环境：{_esc(report['environment'])}</li>
<li>命令：{_esc(report['command'])}</li>
</ul>
<p>通过 {report['summary']['通过']}，未通过 {report['summary']['未通过']}，未测试 {report['summary']['未测试']}，未实现 {report['summary']['未实现']}。</p>
<table>
<thead><tr><th>ID</th><th>场景</th><th>测试类型</th><th>预期</th><th>实测</th><th>结果</th><th>原因</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body>
</html>
"""


def _esc(value: object) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _markdown(report: dict) -> str:
    lines = [
        "# 智语外呼最终测试报告",
        "",
        report["conclusion"],
        "",
        f"- 时间（Asia/Shanghai）：{report['generated_at']}",
        f"- 提交：{report['commit']}",
        f"- 分支：{report['branch']}",
        f"- 环境：{report['environment']}",
        f"- 命令：`{report['command']}`",
        "",
        f"通过 {report['summary']['通过']}，未通过 {report['summary']['未通过']}，未测试 {report['summary']['未测试']}，未实现 {report['summary']['未实现']}。",
        "",
        "| ID | 场景 | 测试类型 | 预期 | 实测 | 结果 | 原因 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        cells = [
            case["id"],
            case["scenario"],
            case["test_type"],
            case["expected"],
            case["actual"],
            case["status"],
            case["reason"],
        ]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    lines.append("")
    lines.append("原始 pytest 输出见同目录 `pytest.log`。")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="离线最终检查")
    parser.add_argument("--output", default="reports/latest")
    args = parser.parse_args()
    out = Path(args.output)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    results_path = out / "pytest-results.json"
    log_path = out / "pytest.log"
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["ZHIYU_PYTEST_RESULTS"] = str(results_path)
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    log_path.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    payload = {"exitstatus": completed.returncode, "results": []}
    if results_path.exists():
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    cases = _merge(payload)
    for item in not_run_cases(sys.platform):
        cases.append(dict(item))
    summary = {"通过": 0, "未通过": 0, "未测试": 0, "未实现": 0}
    for case in cases:
        summary[case["status"]] = summary.get(case["status"], 0) + 1
    failed = summary["未通过"]
    conclusion = conclusion_text(sys.platform, bool(failed))
    report = {
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "commit": _git(["rev-parse", "HEAD"]),
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "environment": f"Python {sys.version.split()[0]} {platform.platform()}",
        "command": "python scripts/run_final_check.py --output " + str(args.output),
        "pytest_exit_code": completed.returncode,
        "summary": summary,
        "conclusion": conclusion,
        "cases": cases,
        "historical_latency_not_used": "以前在别的机器上测到的 1.4 秒 / 2.5 秒 / 0.3 秒不是本次结果。",
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(_markdown(report), encoding="utf-8")
    (out / "report.html").write_text(_html(report), encoding="utf-8")
    print(conclusion)
    print(f"报告目录：{out}")
    return 1 if failed or completed.returncode != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
