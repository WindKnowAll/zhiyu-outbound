"""不能由离线 pytest 打成通过的条目。

平台相关的句子按生成报告的那台电脑写。Linux 上不能写成 Windows 已测。
Windows 上只能写「离线报告命令已在本进程执行」，不能写成麦克风或百炼已通过。
"""

from __future__ import annotations


def not_run_cases(sys_platform: str) -> list[dict]:
    on_windows = sys_platform == "win32"
    if on_windows:
        gap03 = {
            "id": "GAP-03",
            "scenario": "本次离线报告命令在什么系统上执行",
            "test_type": "环境",
            "expected": "若进程是 Windows，写明离线报告命令已执行，并且不把双击启动、麦克风、真实百炼算进本条",
            "actual": "本进程平台是 Windows。本次执行的是离线报告命令。",
            "status": "通过",
            "reason": "只说明这条命令在 Windows 上运行。Windows启动.bat 是否双击成功、麦克风、真实百炼都不由本条证明。",
        }
    else:
        gap03 = {
            "id": "GAP-03",
            "scenario": "本次离线报告命令在什么系统上执行",
            "test_type": "环境",
            "expected": "非 Windows 上生成的报告不能写成 Windows 已测",
            "actual": "本进程平台不是 Windows。",
            "status": "未测试",
            "reason": "这次报告不是在 Windows 上生成的，不能写成 Windows 离线命令已测。",
        }
    return [
    {
        "id": "LIVE-01",
        "scenario": "用真实百炼密钥跑千问、CosyVoice、Paraformer",
        "test_type": "真实接口",
        "expected": "smoke_test.py 打印三段耗时且不输出密钥",
        "actual": "本次未执行",
        "status": "未测试",
        "reason": "云端没有密钥。该脚本会调用付费接口，必须由持有密钥的人显式运行 python scripts/smoke_test.py。",
    },
    {
        "id": "LIVE-02",
        "scenario": "浏览器麦克风对真实模型说一句话并听到回复",
        "test_type": "人工语音",
        "expected": "页面接通后开场白播放，用户说话后有回复，插话能停播放",
        "actual": "本次未执行",
        "status": "未测试",
        "reason": "本命令不采集麦克风，也不调用百炼。离线通过不能写成真实语音通过。",
    },
    {
        "id": "LIVE-03",
        "scenario": "真实模型是否遵守不编造、不索要敏感信息",
        "test_type": "真实语义质量",
        "expected": "用无个人信息的样例问真实千问，再按人设标准人工或另一次显式评估",
        "actual": "本次未执行",
        "status": "未测试",
        "reason": "本次没有调用千问。样例规则检查只覆盖写死的回复文本，不能代表模型质量。",
    },
    {
        "id": "GAP-01",
        "scenario": "拨打真实电话",
        "test_type": "验收缺口",
        "expected": "若验收要求电话外呼，应有 SIP 或运营商接入",
        "actual": "代码只有浏览器 WebRTC，没有电话接入",
        "status": "未实现",
        "reason": "README 写明真正的电话外呼还没做。本次不拨号。",
    },
    {
        "id": "GAP-02",
        "scenario": "京东官方工单接口",
        "test_type": "验收缺口",
        "expected": "若验收要求写回京东工单，应调用企业给出的 Mock 或沙箱接口",
        "actual": "通话结束只写本项目本地 Mock 工单",
        "status": "未实现",
        "reason": "资料写明使用 Mock。当前没有官方沙箱地址，不能把本地文件写成京东工单已接通。",
    },
    {
        "id": "ENV-01",
        "scenario": "本次重新构建 Docker 镜像",
        "test_type": "环境",
        "expected": "docker build 成功且不调用百炼",
        "actual": "本次未执行",
        "status": "未测试",
        "reason": "当前环境没有 docker 命令，不能把以前的构建写成这次的结果。",
    },
        gap03,
    ]


def conclusion_text(sys_platform: str, failed: bool) -> str:
    """开头结论只写本进程能证明的事。"""

    separate = "麦克风、真实百炼、京东官方工单和是否双击 Windows启动.bat 都要单独计，不能由离线结果写成通过。"
    if failed:
        return "离线测试有未通过项。" + separate
    if sys_platform == "win32":
        return "本次 Windows 离线报告命令已运行并写出报告。" + separate
    return "本次报告不是在 Windows 上生成的，不能写成 Windows 已测。离线流程测试已通过。" + separate
