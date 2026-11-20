# 最终测试怎么跑

这页只说明命令。某一次的通过、未通过、未测试，以运行后生成的 `reports/latest/report.md` 为准。

人设仍是 `prompts/system_prompt.txt` 里的图书馆取书。这里没有资审关单话术。真实电话外呼也没有实现。

## 依赖

- 64 位 Python 3.11 或 3.12。Windows 逐步安装见 [windows-quickstart.md](windows-quickstart.md)。
- 离线测试：`python -m pip install -r requirements-dev.txt`
- 只启动网页：`python -m pip install -r requirements.txt`
- 国内接口仍是百炼 Paraformer、通义千问、CosyVoice。不要改成别的供应商。

## 预检

```text
python scripts/preflight.py
```

预检不打开 `.env`，所以它不知道密钥对不对。

## 离线测试

Windows 可以双击仓库根目录的 `运行离线测试.bat`。两个 bat 使用 CRLF。云端这次只检查了文件字节，没有在 Windows 上双击。已有 `.venv` 时直接用 `.venv\Scripts\python.exe`，不会改用 `py -3`。离线测试失败会停在窗口里，退出码不是 0，也不会先写「通过」。

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

浏览器打开 http://127.0.0.1:7860 。没有 `.env` 时页面说明缺密钥，通话按钮不会真正接通。

## 可选：真实接口

会花钱，而且必须你自己在本机准备 `.env`。测试包和报告脚本都不会自动跑它。

```text
python scripts/smoke_test.py
```

## 可选：人工麦克风

在真实接口已经成功、浏览器允许麦克风之后，点「开始通话」。这一步没有自动化结果。
