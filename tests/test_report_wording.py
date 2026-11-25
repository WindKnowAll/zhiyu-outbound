"""报告里的平台句子必须跟着本进程走，不能写死。"""

from tests.not_run_manifest import conclusion_text, not_run_cases


def _gap(platform: str) -> dict:
    return next(item for item in not_run_cases(platform) if item["id"] == "GAP-03")


def _live_voice(platform: str) -> dict:
    return next(item for item in not_run_cases(platform) if item["id"] == "LIVE-02")


def test_linux_report_does_not_claim_windows_was_tested():
    gap = _gap("linux")
    text = conclusion_text("linux", failed=False)
    assert gap["status"] == "未测试"
    assert "不是在 Windows" in gap["reason"] or "不是 Windows" in gap["actual"]
    assert "离线命令已测" not in gap["actual"]
    assert "不能写成 Windows 已测" in text
    assert "真实语音" not in text or "不能" in text
    assert "已接通" not in text


def test_windows_report_says_offline_command_ran_and_keeps_voice_separate():
    gap = _gap("win32")
    voice = _live_voice("win32")
    text = conclusion_text("win32", failed=True)
    passed = conclusion_text("win32", failed=False)
    assert gap["status"] == "通过"
    assert "Windows" in gap["actual"]
    assert "离线报告命令" in gap["actual"]
    assert "没有在 Windows 上执行" not in gap["reason"]
    assert voice["status"] == "未测试"
    assert "百炼" in voice["reason"]
    assert "不能写成真实语音通过" in voice["reason"]
    assert "离线报告命令已运行" in passed
    assert "不能由离线结果写成通过" in passed
    assert "未通过" in text or "有未通过项" in text
