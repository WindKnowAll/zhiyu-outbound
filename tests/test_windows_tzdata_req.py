"""Windows 报告依赖必须写在 requirements 里。

本测试不导入时区库。Linux 自带系统时区数据，调用成功也不能证明 Windows 能生成报告。
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
RUNTIME = (ROOT / "requirements.txt").read_text(encoding="utf-8")


def _tzdata_lines() -> list[str]:
    lines = []
    for raw in DEV.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("tzdata"):
            lines.append(line)
    return lines


def _marker_matches(marker: str, platform: str) -> bool:
    """只识别本仓库使用的这一条标记，避免在 Linux 上用系统时区冒充通过。"""

    expected = 'sys_platform == "win32"'
    if marker != expected:
        raise AssertionError(marker)
    return platform == "win32"


@pytest.mark.case(
    id="BAT-02",
    scenario="Windows 新建环境安装 requirements-dev.txt 后能生成 Asia/Shanghai 报告",
    kind="依赖声明",
    expected="tzdata 只在 sys_platform == win32 时安装；requirements.txt 不含它；本测试不导入时区库",
)
def test_windows_tzdata_marker_is_declared_and_not_for_linux():
    lines = _tzdata_lines()
    assert lines == ['tzdata>=2024.1; sys_platform == "win32"']
    name, _, marker = lines[0].partition(";")
    assert name.strip().startswith("tzdata>=")
    marker = marker.strip()
    assert _marker_matches(marker, "win32") is True
    assert _marker_matches(marker, "linux") is False
    assert "tzdata" not in RUNTIME.lower()
