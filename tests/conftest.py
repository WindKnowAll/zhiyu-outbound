"""把带 case 标记的测试结果写到环境变量指定的文件，供最终报告汇总。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_RESULTS: list[dict] = []


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "case(id, scenario, kind, expected): 验收条目。kind 只说明测试类型，不表示真实模型已评估。",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        marker = item.get_closest_marker("case")
        meta = dict(marker.kwargs) if marker else {}
        longrepr = ""
        if report.longrepr:
            longrepr = str(report.longrepr)
            if len(longrepr) > 2000:
                longrepr = longrepr[:2000] + "…"
        _RESULTS.append(
            {
                "nodeid": item.nodeid,
                "when": report.when,
                "outcome": report.outcome,
                "duration_sec": round(getattr(report, "duration", 0) or 0, 3),
                "id": meta.get("id", ""),
                "scenario": meta.get("scenario", ""),
                "kind": meta.get("kind", ""),
                "expected": meta.get("expected", ""),
                "longrepr": longrepr,
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    target = os.environ.get("ZHIYU_PYTEST_RESULTS")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"exitstatus": int(exitstatus), "results": _RESULTS}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
