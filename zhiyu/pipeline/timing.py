"""一轮对话里四个时间点。单位都是毫秒，没有发生的阶段留空。"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class StageTimings:
    # 用户停说 → 我们认定这句转写可以用了。
    asr_final_ms: float | None = None
    # 转写定稿 → 大模型吐出第一个字。
    llm_first_token_ms: float | None = None
    # 大模型第一个字（开场白则是开始合成）→ 第一包音频。
    tts_first_audio_ms: float | None = None
    # 用户停说（开场白则是开始合成）→ 第一包音频。这是「首包延迟」。
    first_audio_e2e_ms: float | None = None

    def as_log(self) -> str:
        return (
            f"ASR定稿 {_fmt(self.asr_final_ms)} ms | "
            f"LLM首token {_fmt(self.llm_first_token_ms)} ms | "
            f"TTS首包 {_fmt(self.tts_first_audio_ms)} ms | "
            f"端到端首包 {_fmt(self.first_audio_e2e_ms)} ms"
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}"
