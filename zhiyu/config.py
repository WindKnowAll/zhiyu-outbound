"""从环境变量读取配置。

密钥只放在环境变量或 .env 里。这里不提供默认密钥，缺失时调用方要能把
页面和服务都正常开起来，并把缺什么讲清楚。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# 百炼共享域名。控制台说明它自 2026-09-30 起进入维护，新工作空间密钥应改用专属域名。
LEGACY_DASHSCOPE_HOST = "dashscope.aliyuncs.com"
BEIJING_WORKSPACE_SUFFIX = ".cn-beijing.maas.aliyuncs.com"


@dataclass(frozen=True)
class Settings:
    """一次进程里用到的全部可调参数。做成不可变对象，避免通话中途被改掉。"""

    dashscope_api_key: str
    dashscope_host: str
    dashscope_base_url: str
    dashscope_ws_url: str
    # host / workspace_id / explicit / override / legacy。只给日志看，不参与请求。
    dashscope_endpoint_source: str
    llm_model: str
    asr_model: str
    tts_model: str
    tts_voice: str
    tts_sample_rate: int
    ice_servers: tuple[str, ...]
    vad_confidence: float
    vad_start_secs: float
    vad_stop_secs: float
    vad_min_volume: float
    asr_finalize_timeout: float
    host: str
    port: int
    log_level: str

    @property
    def missing_keys(self) -> list[str]:
        if not self.dashscope_api_key:
            return ["DASHSCOPE_API_KEY"]
        return []

    @property
    def credentials_ready(self) -> bool:
        return not self.missing_keys


def _text(env: dict[str, str], name: str, default: str = "") -> str:
    return (env.get(name) or default).strip()


def _float(env: dict[str, str], name: str, default: float) -> float:
    raw = _text(env, name)
    if not raw:
        return default
    return float(raw)


def _int(env: dict[str, str], name: str, default: int) -> int:
    raw = _text(env, name)
    if not raw:
        return default
    return int(raw)


def normalize_dashscope_host(value: str) -> str:
    """把控制台复制出来的地址收成主机名。

    接受 `ws-xxx.cn-beijing.maas.aliyuncs.com`，也接受带 https:// 和路径的整段 URL。
    """

    text = value.strip()
    lowered = text.lower()
    for prefix in ("https://", "http://", "wss://", "ws://"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.split("/", 1)[0].strip()
    if text.endswith(":443"):
        text = text[: -len(":443")]
    return text


def workspace_id_to_host(workspace_id: str) -> str:
    """`工作空间 ID` → `ws-<id>.cn-beijing.maas.aliyuncs.com`。

    已经带 `ws-` 或已经是完整主机名时不再加一层。
    """

    ident = normalize_dashscope_host(workspace_id)
    if not ident:
        return ""
    if "." in ident:
        return ident
    if ident.lower().startswith("ws-"):
        ident = ident[3:]
    return f"ws-{ident}{BEIJING_WORKSPACE_SUFFIX}"


def resolve_dashscope_endpoint(env: dict[str, str]) -> tuple[str, str, str, str]:
    """从一个主机名推出千问和语音两条地址。

    优先级：显式的 `DASHSCOPE_BASE_URL` / `DASHSCOPE_WS_URL` 各自覆盖对应那一条。
    主机名来自 `DASHSCOPE_HOST`，否则来自 `DASHSCOPE_WORKSPACE_ID`。
    两个都空、显式地址也空时，退回维护中的共享域名。
    """

    explicit_base = _text(env, "DASHSCOPE_BASE_URL")
    explicit_ws = _text(env, "DASHSCOPE_WS_URL")
    host_raw = _text(env, "DASHSCOPE_HOST")
    workspace_id = _text(env, "DASHSCOPE_WORKSPACE_ID")

    host = ""
    source = "legacy"
    if host_raw:
        host = normalize_dashscope_host(host_raw)
        source = "host"
    elif workspace_id:
        host = workspace_id_to_host(workspace_id)
        source = "workspace_id"

    if host:
        derived_base = f"https://{host}/compatible-mode/v1"
        derived_ws = f"wss://{host}/api-ws/v1/inference"
    else:
        host = LEGACY_DASHSCOPE_HOST
        derived_base = f"https://{LEGACY_DASHSCOPE_HOST}/compatible-mode/v1"
        derived_ws = f"wss://{LEGACY_DASHSCOPE_HOST}/api-ws/v1/inference"

    base_url = explicit_base or derived_base
    ws_url = explicit_ws or derived_ws
    if explicit_base or explicit_ws:
        source = "override" if source in {"host", "workspace_id"} else "explicit"
        if not host_raw and not workspace_id:
            host = normalize_dashscope_host(explicit_base or explicit_ws) or host
    return host, base_url, ws_url, source


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """读取配置。测试可以传入字典，避免碰真正的环境变量。"""

    source = os.environ if env is None else env
    ice_raw = _text(
        source,
        "ICE_SERVERS",
        "stun:stun.qq.com:3478,stun:stun.miwifi.com:3478",
    )
    ice = tuple(item.strip() for item in ice_raw.split(",") if item.strip())
    dash_host, dash_base, dash_ws, dash_source = resolve_dashscope_endpoint(source)
    return Settings(
        dashscope_api_key=_text(source, "DASHSCOPE_API_KEY"),
        dashscope_host=dash_host,
        dashscope_base_url=dash_base,
        dashscope_ws_url=dash_ws,
        dashscope_endpoint_source=dash_source,
        llm_model=_text(source, "DASHSCOPE_LLM_MODEL", "qwen-plus"),
        asr_model=_text(source, "DASHSCOPE_ASR_MODEL", "paraformer-realtime-v2"),
        tts_model=_text(source, "DASHSCOPE_TTS_MODEL", "cosyvoice-v2"),
        tts_voice=_text(source, "DASHSCOPE_TTS_VOICE", "longxiaochun_v2"),
        tts_sample_rate=_int(source, "DASHSCOPE_TTS_SAMPLE_RATE", 24000),
        ice_servers=ice,
        vad_confidence=_float(source, "VAD_CONFIDENCE", 0.7),
        vad_start_secs=_float(source, "VAD_START_SECS", 0.2),
        vad_stop_secs=_float(source, "VAD_STOP_SECS", 0.2),
        vad_min_volume=_float(source, "VAD_MIN_VOLUME", 0.6),
        asr_finalize_timeout=_float(source, "ASR_FINALIZE_TIMEOUT", 0.35),
        host=_text(source, "HOST", "0.0.0.0"),
        port=_int(source, "PORT", 7860),
        log_level=_text(source, "LOG_LEVEL", "INFO"),
    )


def uses_legacy_dashscope_domain(settings: Settings) -> bool:
    return LEGACY_DASHSCOPE_HOST in settings.dashscope_base_url or (
        LEGACY_DASHSCOPE_HOST in settings.dashscope_ws_url
    )


def legacy_domain_warning() -> str:
    return (
        "当前百炼地址是 dashscope.aliyuncs.com。"
        "控制台说明该域名自 2026-09-30 起进入维护，新的工作空间密钥（sk-ws- 开头）"
        "应改填 DASHSCOPE_HOST，形如 ws-<工作空间ID>.cn-beijing.maas.aliyuncs.com。"
        "填了主机名之后，不要再留着旧的 DASHSCOPE_BASE_URL / DASHSCOPE_WS_URL，否则会盖住它。"
    )


def status_payload(settings: Settings) -> dict:
    """给网页和健康检查用。只说明密钥在不在，不去联网验证。"""

    endpoint = {
        "dashscope_host": settings.dashscope_host,
        "dashscope_base_url": settings.dashscope_base_url,
        "dashscope_ws_url": settings.dashscope_ws_url,
        "dashscope_endpoint_source": settings.dashscope_endpoint_source,
        "ice_servers": list(settings.ice_servers),
    }
    missing = settings.missing_keys
    if missing:
        return {
            "ok": False,
            "missing": missing,
            "message": (
                "还没有配置 DASHSCOPE_API_KEY。"
                "请把 .env.example 复制为 .env，填入阿里云百炼的 API Key 和 DASHSCOPE_HOST，然后重新启动。"
                "Windows 步骤见 docs/windows-quickstart.md。"
            ),
            **endpoint,
        }
    message = (
        f"已读到 DASHSCOPE_API_KEY，请求将发往 {settings.dashscope_host}。"
        "密钥是否被这个域名接受，要等第一次请求才会知道。"
    )
    if uses_legacy_dashscope_domain(settings):
        message = f"{message} {legacy_domain_warning()}"
    return {
        "ok": True,
        "missing": [],
        "message": message,
        **endpoint,
    }


@dataclass(frozen=True)
class Persona:
    system_prompt: str
    opening: str


def load_persona(prompts_dir: Path | None = None) -> Persona:
    """系统提示词和开场白分开放，后面换状态机或知识库时不用改代码。"""

    directory = prompts_dir or PROMPTS_DIR
    system_path = directory / "system_prompt.txt"
    opening_path = directory / "opening.txt"
    if not system_path.is_file() or not opening_path.is_file():
        raise FileNotFoundError(
            f"找不到人设文件。期望 {system_path} 和 {opening_path} 都存在。"
        )
    system_prompt = system_path.read_text(encoding="utf-8").strip()
    opening = opening_path.read_text(encoding="utf-8").strip()
    if not system_prompt or not opening:
        raise ValueError("系统提示词和开场白都不能是空文件。")
    return Persona(system_prompt=system_prompt, opening=opening)
