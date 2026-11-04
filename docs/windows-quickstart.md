# Windows 11 从零跑通

按这个顺序做，可以在一台新的 Windows 11 电脑上把智语外呼跑起来。命令都在 PowerShell 里执行。每一步做完再做下一步。

更短的架构说明在仓库根目录的 [README.md](../README.md)。

## 先看懂两件事

1. 密钥和域名要成对。新工作空间的 API Key 多半以 `sk-ws-` 开头，只能配控制台里那个专属域名，形如 `ws-<工作空间ID>.cn-beijing.maas.aliyuncs.com`。域名填错时，接口会返回 401。
2. 代码放在纯英文路径里，例如 `C:\zhiyu`。放在「桌面」或带中文的文件夹里时，个别安装步骤会失败。下面有专门一节。

## 1. 安装 64 位 Python 3.12

本仓库在 Python 3.12 上验证过。3.11 也可以。先不要用 3.13：`aiortc`、`av`、`onnxruntime` 这些带原生代码的包，3.13 的 Windows 安装包不一定齐全，pip 就会改去编译，然后报缺编译器。

1. 打开 <https://www.python.org/downloads/windows/>，下载 **Python 3.12.x Windows installer (64-bit)**。
2. 安装时勾选 **Add python.exe to PATH**。
3. 装完后关掉原来的 PowerShell，重新开一个，执行：

```powershell
py -3.12 --version
py -3.12 -c "import struct; print(struct.calcsize('P') * 8)"
```

第一行应显示 `Python 3.12.x`。第二行应显示 `64`。如果显示 `32`，卸掉后改装 64 位。

`py` 不是内部命令时，用开始菜单重新打开「Python 3.12」附带的安装程序，选择 Modify，再勾上 PATH。也可以暂时改用：

```powershell
python --version
```

后面的 `py -3.12` 就换成 `python`。

## 2. 安装 Git

打开 <https://git-scm.com/download/win>，用默认选项安装。新开一个 PowerShell，确认：

```powershell
git --version
```

## 3. 克隆仓库

```powershell
cd C:\
git clone https://github.com/WindKnowAll/zhiyu-outbound.git zhiyu
cd C:\zhiyu
```

把地址换成你自己的仓库也可以。文件夹名用 `zhiyu` 这种英文即可。

## 4. 建虚拟环境

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

行首出现 `(.venv)` 就说明环境已经激活。这个 `Set-ExecutionPolicy` 只对当前窗口有效，关掉窗口就恢复原样。

如果激活脚本报「无法加载，因为在此系统上禁止运行脚本」，就是缺了上面那行 `Set-ExecutionPolicy`。不要用管理员去改整台机器的策略。

每次新开 PowerShell 都要重新：

```powershell
cd C:\zhiyu
.\.venv\Scripts\Activate.ps1
```

## 5. 安装依赖

先升级 pip，再装项目依赖：

```powershell
python -m pip install -U pip
python -m pip install -r requirements.txt
```

只想跑网页和自检，装 `requirements.txt` 就够。还要在这台电脑上跑 `pytest` 时，再执行：

```powershell
python -m pip install -r requirements-dev.txt
```

安装会下载大约几百 MB，包含 Pipecat、aiortc 和 Silero 用的 onnxruntime。看到 `Successfully installed` 再继续。失败了看文末「pip 安装失败」。

## 6. 填写 .env

```powershell
Copy-Item .env.example .env
notepad .env
```

改两处，其它先保持不动：

1. `DASHSCOPE_API_KEY=` 后面贴上百炼控制台的 Key，不要加引号，不要有空格。
2. `DASHSCOPE_HOST=` 后面换成你的专属域名，只留主机名。占位符 `ws-xxxxxxxx.cn-beijing.maas.aliyuncs.com` 里的 `xxxxxxxx` 不是真 ID，必须换掉。

控制台位置：<https://bailian.console.aliyun.com/> 。创建 Key 的说明：<https://help.aliyun.com/zh/model-studio/get-api-key> 。Key 旁边如果写着专属域名，就用那一串。

也可以不填 `DASHSCOPE_HOST`，改填：

```text
DASHSCOPE_WORKSPACE_ID=你的工作空间ID
```

程序会拼成 `ws-<ID>.cn-beijing.maas.aliyuncs.com`。两个都填时，以 `DASHSCOPE_HOST` 为准。

`DASHSCOPE_BASE_URL` 和 `DASHSCOPE_WS_URL` 保持注释。这两行一旦写上，就会盖住 `DASHSCOPE_HOST`。共享域名 `dashscope.aliyuncs.com` 自 2026-09-30 起进入维护，新 Key 不要再写回去。它有时也能通，但千问首 token 可能要十几秒。

保存并关掉记事本。`.env` 已经在 `.gitignore` 里，不要把它提交到 git。

确认三个模型在这个工作空间里能调用：`qwen-plus`、`paraformer-realtime-v2`、`cosyvoice-v2`（音色 `longxiaochun_v2`）。

## 7. 跑连通性自检

```powershell
python scripts\smoke_test.py
```

脚本依次调用项目里的 `DashScopeChatModel`、`DashScopeSynthesizer`、`DashScopeRecognizer`，打印：

- 实际使用的域名（确认不是占位符，也不是旧的共享域名）
- 千问首 token 和整句耗时
- CosyVoice 首包耗时（含建连，以及送文本之后）
- Paraformer 在音频送完之后多久给出定稿

在专属域名上，一次实测大约是：千问首 token 1.4 秒，合成首包 2.5 秒，识别定稿在音频结束后约 0.3 秒。你的网络和账号会有差别，数字只用来确认「通了，并且没有慢到共享域名那种十几秒」。

最后一行是「三条链路都通了。」就说明 Key、域名和三个模型都可用。输出里不应出现完整的 `sk-` 密钥。

自检失败就先不要开网页，看文末的 401 和 pip 两节。

## 8. 启动网页并说话

```powershell
python -m zhiyu.server
```

看到 `Uvicorn running on http://0.0.0.0:7860` 后，用 Chrome 或 Edge 打开：

<http://127.0.0.1:7860>

页面上如果是红字，就还缺 Key，回到第 6 步。状态变成「可以开始」后：

1. 点「开始通话」。
2. 浏览器询问麦克风时选允许。若没有弹窗，点地址栏左侧的锁，把麦克风改成允许，再刷新。
3. 小语会先说一句开场白。等她说完，或者在她说话时直接开口。开口后她的声音应马上停，你说完后她再答。
4. 页面下方「本轮耗时」和 PowerShell 里的 `耗时 ASR定稿 ...` 是同一次通话的数字。

挂断后再在 PowerShell 里按 `Ctrl+C` 停掉服务。

## 常见问题

### 401，或提示密钥无效、工作空间不对

Key 和域名不是同一个工作空间。对照这几条：

- `.env` 里的 Key 是不是这个工作空间新建的（`sk-ws-` 开头的要用它自己的域名）。
- `DASHSCOPE_HOST` 是不是控制台上那串 `ws-` 开头的主机名，有没有还留着 `xxxxxxxx`。
- `DASHSCOPE_BASE_URL`、`DASHSCOPE_WS_URL` 是不是被取消了注释。有的话先注释掉，只留 `DASHSCOPE_HOST`。
- Key 前后有没有空格或引号。`DASHSCOPE_API_KEY=sk-ws-...` 等号两边都不要空格。
- 模型没有在这个工作空间开通，有时也会表现为鉴权或权限错误。回到控制台确认 `qwen-plus`、`paraformer-realtime-v2`、`cosyvoice-v2`。

改完 `.env` 要重新运行 `python scripts\smoke_test.py`。已经开着的 `python -m zhiyu.server` 不会重新读 `.env`，先 `Ctrl+C` 再启动。

### 麦克风没声音，或浏览器不申请权限

Windows 自己还有一层开关：

1. 设置 → 隐私和安全性 → 麦克风。
2. 打开「麦克风访问」。
3. 打开「让桌面应用访问麦克风」。用 Chrome / Edge 时，还要允许这些浏览器。

然后在浏览器地址栏的锁里把 `127.0.0.1` 的麦克风设为允许，刷新页面。通话要在点过「开始通话」之后才开始，直接对着电脑说不会有请求。

外放很大时，电脑可能把自己的声音再收进去。可以先戴耳机。

### 端口 7860 已被占用

```powershell
netstat -ano | findstr :7860
```

最后一列是进程号。确认那个程序可以关之后：

```powershell
Stop-Process -Id 进程号
```

或者改 `.env` 里的 `PORT=7861`，重新启动，浏览器改开 <http://127.0.0.1:7861>。

### pip 安装失败、要装 Visual C++ 或报错 wheel

按这个顺序试：

1. 确认是 64 位 Python 3.12，不是 32 位，也不是 3.13。`py -0p` 能列出电脑上的全部 Python。
2. 重新执行 `python -m pip install -U pip`，再装一次 `requirements.txt`。
3. 报错里出现 `Microsoft Visual C++ 14.0 or greater is required`，说明这个包没有现成的 Windows 安装包，pip 在尝试本地编译。优先换回 3.12 64 位再装，不要先去装一整套生成工具。
4. 校园网或公司代理下 SSL 失败时，先在这个窗口里告诉 pip 代理，再安装：

```powershell
$env:HTTPS_PROXY = "http://代理地址:端口"
python -m pip install -r requirements.txt
```

### 中文路径、桌面、OneDrive

路径里有中文、空格特别多，或仓库放在 OneDrive「桌面」同步目录下时，可能出现：

- `Activate.ps1` 找不到
- pip 解压一半失败
- 启动后提示找不到 `prompts\system_prompt.txt`

处理办法是把仓库放回 `C:\zhiyu` 这种短的英文路径，重新做第 3 步以后的命令。不要只把 `.venv` 拷来拷去，虚拟环境里写死了旧路径，换地方之后要删掉 `.venv` 再创建一次。

### PowerShell 里 python 打开了微软商店

这是 Windows 的应用执行别名。设置 → 应用 → 高级应用设置 → 应用执行别名，关掉 `python.exe` 和 `python3.exe` 两个开关。然后用 `py -3.12` 调用第 1 步装上的 Python。
