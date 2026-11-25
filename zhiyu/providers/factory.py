"""按配置创建三个供应商。

v1 只有 DashScope 一套实现。要换供应商时，在这里加分支，
返回满足 base.py 里三个接口的对象即可。
"""

from __future__ import annotations

from zhiyu.config import Settings
from zhiyu.providers.base import ProviderError
from zhiyu.providers.dashscope_asr import DashScopeRecognizer
from zhiyu.providers.dashscope_llm import DashScopeChatModel
from zhiyu.providers.dashscope_tts import DashScopeSynthesizer


def create_recognizer(settings: Settings) -> DashScopeRecognizer:
    _require_key(settings)
    return DashScopeRecognizer(
        api_key=settings.dashscope_api_key,
        ws_url=settings.dashscope_ws_url,
        model=settings.asr_model,
        sample_rate=16000,
    )


def create_language_model(settings: Settings) -> DashScopeChatModel:
    _require_key(settings)
    return DashScopeChatModel(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        model=settings.llm_model,
    )


def create_synthesizer(settings: Settings) -> DashScopeSynthesizer:
    """每次回复新建一个对象，因为一条 CosyVoice 连接对应一段合成。"""

    _require_key(settings)
    return DashScopeSynthesizer(
        api_key=settings.dashscope_api_key,
        ws_url=settings.dashscope_ws_url,
        model=settings.tts_model,
        voice=settings.tts_voice,
        sample_rate=settings.tts_sample_rate,
    )


def _require_key(settings: Settings) -> None:
    if settings.missing_keys:
        names = "、".join(settings.missing_keys)
        raise ProviderError(
            f"缺少 {names}。服务可以打开页面，但通话需要先在环境变量里配上密钥。"
        )
