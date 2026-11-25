"""子进程输出不能按 Windows GBK 解码。失败也要留下本轮日志。"""

import sys

import pytest

from scripts.run_final_check import capture_command, decode_process_output


def test_gbk_illegal_bytes_do_not_drop_the_output():
    raw = "结果".encode("utf-8") + bytes([0x82])
    with pytest.raises(UnicodeDecodeError):
        raw.decode("gbk")
    text = decode_process_output(raw)
    assert "结果" in text
    assert decode_process_output(None) == ""


def test_capture_command_reads_bytes_that_are_not_gbk():
    code, stdout, stderr = capture_command(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write('结果'.encode()+bytes([0x82]))"],
        cwd=".",
        env={},
    )
    assert code == 0
    assert "结果" in stdout
    assert stderr == "" or isinstance(stderr, str)
