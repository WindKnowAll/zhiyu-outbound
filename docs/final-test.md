# 最终测试怎么跑

这页只说明命令。某一次的通过、未通过、未测试，以运行后生成的 `reports/latest/report.md` 为准。

默认通话是商家资质审核驳回的比赛模拟。公司和店铺是合成数据，页面会标明不是京东真实业务。话术读 `data/qualification` 里的原表。场景汇总实数是 68 条：电话 54、京麦驳回 14。说明文档写的电话 55、京麦 13，以表为准。第 28 行和第 59 行没有话术，程序不补写。真实麦克风和真实百炼不由离线测试代替。

## 依赖

- 64 位 Python 3.11 或 3.12。Windows 逐步安装见 [windows-quickstart.md](windows-quickstart.md)。
- 离线测试：`python -m pip install -r requirements-dev.txt`。Windows 会多装 `tzdata`（仅 `sys_platform == win32`），否则报告里的 `Asia/Shanghai` 会失败。Linux 不安装这一行。
- 只启动网页：`python -m pip install -r requirements.txt`。这里没有 `tzdata`。
- 国内接口仍是百炼 Paraformer、通义千问、CosyVoice。不要改成别的供应商。

## 预检

```text
python scripts/preflight.py
```

预检不打开 `.env`，所以它不知道密钥对不对。

## 离线测试

Windows 可以双击仓库根目录的 `运行离线测试.bat`。两个 bat 使用 CRLF。已有 `.venv` 时直接用 `.venv\Scripts\python.exe`，不会改用 `py -3`。离线测试失败会停在窗口里，退出码不是 0，也不会先写「通过」。报告按生成它的那台电脑写平台：在 Windows 上跑完，只能说明离线报告命令已执行；麦克风、真实百炼、以及是否双击了 `Windows启动.bat`，各自另计。在 Linux 上生成的报告不能写成 Windows 已测。

跨平台：

```text
python scripts/run_final_check.py --output reports/latest
```

然后看这三份文件：

- `reports/latest/report.md`
- `reports/latest/report.html`
- `reports/latest/report.json`

原始输出在 `reports/latest/pytest.log`。

## 启动网页

Windows 双击 `Windows启动.bat`。

跨平台：

```text
python -m zhiyu.server
```

浏览器打开 http://127.0.0.1:7860 。没有 `.env` 时页面说明缺密钥，通话按钮不会真正接通。服务默认只听 `127.0.0.1`；要给局域网用时，在 `.env` 里把 `HOST` 改成 `0.0.0.0`。打开页面和查看 `/api/status` 不会建立付费的识别、大模型或合成，也不会打开麦克风。点「开始通话」才会申请麦克风并建立会话。若 7860 上已是本项目，`Windows启动.bat` 会提示直接打开该地址，不再启动第二个进程。若被别的程序占用，只显示端口和 PID，不结束那个进程，也不改端口。

## 可选：真实接口

会花钱，而且必须你自己在本机准备 `.env`。测试包和报告脚本都不会自动跑它。

```text
python scripts/smoke_test.py
```

## 待会在你自己电脑上做真实语音

这一步还没有人测过，不能写成已经通过。

1. 用已经装好依赖的目录，覆盖这次的增量文件。不要删 `.venv`，不要改 `.env`。
2. 双击 `Windows启动.bat`。浏览器打开 http://127.0.0.1:7860 。页面标题应是「商家资质审核驳回」，并写着比赛模拟。
3. 只打开页面或看 `/api/status` 时，不会申请麦克风，也不会建立付费会话。
4. 页面上的场景列表来自主表全部 68 条。可以自己选，也可以点「随机开始通话」。随机会抽一条并立刻申请麦克风、接通这通电话。通话中不能改场景。
5. 点「开始通话」或「随机开始通话」并允许麦克风。先听到确认公司和店铺。先回答「是的，我是」。在这之前不要期待听到驳回原因。你说完的字应马上出现，不必等下一句客服。
6. 听完原因后可以问「为什么驳回」。它应重复这一条的原因，而不是说自己查不到。再说「好的」结束。页面下方应出现本地模拟工单。那不是京东官方接口，也不是已经转接真人。
7. 可以说「别打了」「打错了」或一个表里没有的问题。它不能承诺审核通过，也不能把内部说法讲出来。挂断后工单仍应写上。

## 可选：人工麦克风

在真实接口已经成功、浏览器允许麦克风之后，点「开始通话」。这一步没有自动化结果。
