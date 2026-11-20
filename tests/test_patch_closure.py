"""增量包必须以用户安装的 f0d6e4a 为底，带齐测试新 import 的文件。"""

from scripts.patch_closure import INSTALL_BASELINE, missing_patch_files


def test_f0d6e4a_patch_includes_assert_crlf_bat_module():
    missing = missing_patch_files(INSTALL_BASELINE, "HEAD")
    assert missing == []
