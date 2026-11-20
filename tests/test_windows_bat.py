"""检查两个 bat 的字节。这里没有 cmd.exe，所以不能代替 Windows 上双击验收。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.package_test_bundle import assert_crlf_bat, normalize_bat_bytes

ROOT = Path(__file__).resolve().parents[1]
BATS = ("Windows启动.bat", "运行离线测试.bat")


def _read(name: str) -> bytes:
    return (ROOT / name).read_bytes()


@pytest.mark.case(
    id="BAT-01",
    scenario="两个 Windows 脚本在磁盘上是无 BOM 的 UTF-8，且每个换行都是 CR LF",
    kind="离线字节检查",
    expected="CR 的个数等于 LF 的个数，且没有单独的 LF。这不是在 Windows 上执行脚本。",
)
@pytest.mark.parametrize("name", BATS)
def test_bat_files_on_disk_are_crlf(name: str):
    data = _read(name)
    assert_crlf_bat(data, name)
    assert data.count(b"\r") == data.count(b"\n") == data.count(b"\r\n")


def test_normalize_turns_lf_into_crlf():
    raw = b"@echo off\nif exist x goto end\r\n:end\n"
    data = normalize_bat_bytes(b"\xef\xbb\xbf" + raw)
    assert_crlf_bat(data, "sample")
    assert data.split(b"\r\n")[0] == b"@echo off"


def test_zip_entries_for_bats_are_crlf(tmp_path: Path):
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in BATS:
            payload = normalize_bat_bytes(_read(name))
            assert_crlf_bat(payload, name)
            archive.writestr(name, payload)
    with zipfile.ZipFile(archive_path) as archive:
        for name in BATS:
            assert_crlf_bat(archive.read(name), name)


def test_scripts_prefer_venv_and_keep_failure_visible():
    start = _read("Windows启动.bat").decode("utf-8")
    offline = _read("运行离线测试.bat").decode("utf-8")
    for text in (start, offline):
        assert "py -3.12" in text
        assert "py -3 " not in text
        assert "py -3\n" not in text.replace("\r\n", "\n")
        assert ".venv\\Scripts\\python.exe" in text
        assert "pause" in text
        assert "exit /b" in text
    assert "if errorlevel 1 goto fail" in offline
    assert "OFFLINE CHECK FAILED" in offline
    assert "OFFLINE CHECK PASSED" in offline
    assert "Server stopped. Exit code" in start
    assert "reuse_listen.py" in start
    assert "taskkill" not in start.lower()
    assert "start http" not in start.lower()
    assert "goto already" in start
    assert "exit /b 11" in start
    # 成功提示必须写在检查退出码之后，不能先打印成功再忽略失败。
    offline_lines = offline.replace("\r\n", "\n").split("\n")
    passed_at = next(i for i, line in enumerate(offline_lines) if "OFFLINE CHECK PASSED" in line)
    check_at = next(i for i, line in enumerate(offline_lines) if "run_final_check.py" in line)
    guard_at = next(i for i, line in enumerate(offline_lines) if line.strip() == "if errorlevel 1 goto fail" and i > check_at)
    assert check_at < guard_at < passed_at
