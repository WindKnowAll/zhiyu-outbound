"""从环境变量读取配置。

密钥只放在环境变量或 .env 里。这里不提供默认密钥，缺失时调用方要能把
页面和服务都正常开起来，并把缺什么讲清楚。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class Settings:
    """一次进程里用到的全部可调参数。做成不可变对象，避免通话中途被改掉。"""

    dashscope_api_key: str
    dashscope_base_url: str
    dashscope_ws_url: str
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


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """读取配置。测试可以传入字典，避免碰真正的环境变量。"""

    source = os.environ if env is None else env
    ice_raw = _text(
        source,
        "ICE_SERVERS",
        "stun:stun.qq.com:3478,stun:stun.miwifi.com:3478",
    )
    ice = tuple(item.strip() for item in ice_raw.split(",") if item.strip())
    return Settings(
        dashscope_api_key=_text(source, "DASHSCOPE_API_KEY"),
        dashscope_base_url=_text(
            source,
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        dashscope_ws_url=_text(
            source,
            "DASHSCOPE_WS_URL",
            "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        ),
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


def status_payload(settings: Settings) -> dict:
    """给网页和健康检查用。只说明密钥在不在，不去联网验证。"""

    missing = settings.missing_keys
    if missing:
        return {
            "ok": False,
            "missing": missing,
            "message": (
                "还没有配置 DASHSCOPE_API_KEY。"
                "请把 .env.example 复制为 .env，填入阿里云百炼的 API Key，然后重新启动。"
                "获取方式写在 README 的「如何获取 DashScope 密钥」。"
            ),
            "ice_servers": list(settings.ice_servers),
        }
    return {
        "ok": True,
        "missing": [],
        "message": "已读到 DASHSCOPE_API_KEY，可以开始通话。密钥是否有效要等第一次请求才会知道。",
        "ice_servers": list(settings.ice_servers),
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
