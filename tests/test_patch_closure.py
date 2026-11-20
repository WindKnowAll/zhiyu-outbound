"""增量包必须以用户安装的 f0d6e4a 为底，带齐测试新 import 的文件。

解压后的安装目录没有 git 仓库。那种环境下只检查函数是否真的能导入，
不能因为缺少 git 历史而把整份离线测试打成失败。
"""

import subprocess

import pytest

from scripts.package_test_bundle import assert_crlf_bat
from scripts.patch_closure import INSTALL_BASELINE, missing_patch_files


def test_assert_crlf_bat_can_be_imported():
    assert callable(assert_crlf_bat)


def test_f0d6e4a_patch_includes_assert_crlf_bat_module():
    try:
        missing = missing_patch_files(INSTALL_BASELINE, "HEAD")
    except subprocess.CalledProcessError:
        pytest.skip("当前目录不是 git 仓库，安装包只要求 assert_crlf_bat 能导入")
    assert missing == []
