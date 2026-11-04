"""连通性自检：千问 → CosyVoice → Paraformer，并打印每一段耗时。

在项目根目录、已经激活虚拟环境、并且 .env 里写了密钥和 DASHSCOPE_HOST 之后运行：

    python scripts/smoke_test.py

脚本会读 .env，但不会把 API Key 打出来。合成得到的是 24 kHz PCM，
识别按通话同一条链路使用 16 kHz，所以中间做一次重采样。
"""

from __future__ import annotations

import asyncio
import re
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from zhiyu.config import load_settings, uses_legacy_dashscope_domain, legacy_domain_warning
from zhiyu.providers.factory import create_language_model, create_recognizer, create_synthesizer


def redact(text: str, api_key: str = "") -> str:
    """日志和异常里不留密钥。"""

    cleaned = text
    if api_key:
        cleaned = cleaned.replace(api_key, "sk-***")
    return re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-***", cleaned)


def resample_pcm16(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """16 位小端单声道线性重采样。一句语音的长度用纯 Python 就够。"""

    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("采样率必须是正数")
    if len(pcm) % 2:
        pcm = pcm[:-1]
    count = len(pcm) // 2
    if count == 0 or source_rate == target_rate:
        return pcm
    samples = struct.unpack("<" + "h" * count, pcm)
    out_count = max(1, int(round(count * target_rate / source_rate)))
    out: list[int] = []
    last = count - 1
    for index in range(out_count):
        position = index * source_rate / target_rate
        left = int(position)
        if left >= last:
            out.append(samples[last])
            continue
        frac = position - left
        value = samples[left] * (1 - frac) + samples[left + 1] * frac
        out.append(int(max(-32768, min(32767, round(value)))))
    return struct.pack("<" + "h" * len(out), *out)


def _ms(start: float, end: float | None) -> str:
    if end is None:
        return "-"
    return f"{(end - start) * 1000:.0f} ms"


async def round_trip() -> None:
    load_dotenv(ROOT / ".env")
    settings = load_settings()
    if not settings.credentials_ready:
        raise SystemExit(
            "还没有 DASHSCOPE_API_KEY。复制 .env.example 为 .env 后填上密钥和 DASHSCOPE_HOST。"
        )

    print(f"域名: {settings.dashscope_host}（{settings.dashscope_endpoint_source}）")
    print(f"千问: {settings.dashscope_base_url}")
    print(f"语音: {settings.dashscope_ws_url}")
    print(f"模型: {settings.llm_model} / {settings.tts_model} {settings.tts_voice} / {settings.asr_model}")
    if uses_legacy_dashscope_domain(settings):
        print(legacy_domain_warning())

    prompt = "请只回复这一句，不要加别的字：图书馆的书到了。"
    model = create_language_model(settings)
    llm_started = time.perf_counter()
    first_token_at: float | None = None
    parts: list[str] = []
    try:
        async for token in model.stream(
            [
                {"role": "system", "content": "你只重复用户要求的那一句。"},
                {"role": "user", "content": prompt},
            ]
        ):
            if first_token_at is None:
                first_token_at = time.perf_counter()
            parts.append(token)
    except Exception as exc:
        raise SystemExit("千问失败：" + redact(str(exc), settings.dashscope_api_key)) from exc
    llm_done = time.perf_counter()
    reply = "".join(parts).strip()
    if not reply:
        raise SystemExit("千问没有返回文字。")
    print(f"LLM 首 token: {_ms(llm_started, first_token_at)}")
    print(f"LLM 整句: {_ms(llm_started, llm_done)}")
    print(f"LLM 文本: {reply}")

    spoken = reply if reply[-1:] in "。！？!?" else reply + "。"
    tts = create_synthesizer(settings)
    pcm = bytearray()
    first_audio_at: float | None = None
    tts_started = time.perf_counter()
    try:
        await tts.start()
        ready_at = time.perf_counter()
        await tts.push_text(spoken)
        text_sent_at = time.perf_counter()
        await tts.finish()
        async for chunk in tts.audio_chunks():
            if first_audio_at is None:
                first_audio_at = time.perf_counter()
            pcm.extend(chunk)
    except Exception as exc:
        raise SystemExit("语音合成失败：" + redact(str(exc), settings.dashscope_api_key)) from exc
    finally:
        await tts.cancel()
    if not pcm or first_audio_at is None:
        raise SystemExit("语音合成没有返回音频。")
    print(f"TTS 首包（含建连）: {_ms(tts_started, first_audio_at)}")
    print(f"TTS 建连: {_ms(tts_started, ready_at)}")
    print(f"TTS 首包（送文本之后）: {_ms(text_sent_at, first_audio_at)}")
    print(f"TTS 音频: {len(pcm)} 字节，{tts.sample_rate} Hz")

    audio = resample_pcm16(bytes(pcm), tts.sample_rate, 16000)
    # 尾部静音，让 Paraformer 的 VAD 断句能收口。
    audio += b"\x00\x00" * int(16000 * 0.4)
    recognizer = create_recognizer(settings)
    finals: list[str] = []
    partial = ""
    final_at: float | None = None
    errors: list[str] = []
    send_done = 0.0

    async def on_transcript(transcript) -> None:
        nonlocal partial, final_at
        partial = transcript.text
        if transcript.is_final:
            finals.append(transcript.text)
            final_at = time.perf_counter()

    async def on_error(message: str) -> None:
        errors.append(redact(message, settings.dashscope_api_key))

    recognizer.set_transcript_handler(on_transcript)
    recognizer.set_error_handler(on_error)
    await recognizer.start()
    frame = 3200  # 16 kHz、16 bit、约 100 ms
    for offset in range(0, len(audio), frame):
        await recognizer.send_audio(audio[offset : offset + frame])
    send_done = time.perf_counter()
    await recognizer.stop(timeout=20)

    heard = "".join(finals).strip() or partial.strip()
    print(f"ASR 定稿（音频送完之后）: {_ms(send_done, final_at)}")
    print(f"ASR 文本: {heard or '（空）'}")
    if errors:
        raise SystemExit("语音识别失败：" + "；".join(errors))
    if not heard:
        raise SystemExit("语音识别没有返回文字。密钥和域名通了的话，检查模型是否已开通 paraformer-realtime-v2。")
    print("三条链路都通了。")


def main() -> None:
    try:
        asyncio.run(round_trip())
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc.code if isinstance(exc.code, str) else exc)
            raise SystemExit(1) from exc
        raise
    except Exception as exc:
        load_dotenv(ROOT / ".env")
        key = load_settings().dashscope_api_key
        print("失败：" + redact(str(exc), key))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
