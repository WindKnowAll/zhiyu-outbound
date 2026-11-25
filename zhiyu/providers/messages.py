"""DashScope WebSocket 报文。

这里只拼 JSON、只解析 JSON，不打开网络。单测覆盖这些函数，
避免把协议细节散落到收发循环里。字段对照的是百炼文档：

- Paraformer 实时识别：run-task 之后发二进制 PCM，结果在 result-generated。
- CosyVoice 实时合成：run-task、continue-task、finish-task 共用一个 task_id，
  音频走 WebSocket 的二进制帧。

鉴权头用文档示例里的小写 bearer，不是 OpenAI 那条 HTTP 接口的 Bearer。
"""

from __future__ import annotations

import json
from typing import Any

from zhiyu.providers.base import ProviderError, Transcript


def authorization_header(api_key: str) -> dict[str, str]:
    return {"Authorization": f"bearer {api_key}"}


def asr_run_task(
    *,
    task_id: str,
    model: str,
    sample_rate: int,
    language_hints: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": model,
            "parameters": {
                "format": "pcm",
                "sample_rate": sample_rate,
                # 交互场景用 VAD 断句，延迟比语义断句低。
                "semantic_punctuation_enabled": False,
                "max_sentence_silence": 800,
                "language_hints": language_hints or ["zh"],
                # 用户沉默时也保持连接，否则只送静音会超时断开。
                "heartbeat": True,
            },
            "input": {},
        },
    }


def tts_run_task(
    *,
    task_id: str,
    model: str,
    voice: str,
    sample_rate: int,
) -> dict[str, Any]:
    return {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "tts",
            "function": "SpeechSynthesizer",
            "model": model,
            "parameters": {
                "text_type": "PlainText",
                "voice": voice,
                "format": "pcm",
                "sample_rate": sample_rate,
                "volume": 50,
                "rate": 1,
                "pitch": 1,
            },
            "input": {},
        },
    }


def tts_continue_task(*, task_id: str, text: str) -> dict[str, Any]:
    return {
        "header": {
            "action": "continue-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {"input": {"text": text}},
    }


def finish_task(*, task_id: str) -> dict[str, Any]:
    return {
        "header": {
            "action": "finish-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {"input": {}},
    }


def dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False)


def event_name(message: dict[str, Any]) -> str:
    header = message.get("header") or {}
    return str(header.get("event") or "")


def parse_asr_message(message: dict[str, Any]) -> Transcript | None:
    """从一帧服务端事件里取出转写。心跳、空文本和别的事件返回 None。

    task-failed 直接抛错，让上层把原因显示到页面上。
    """

    name = event_name(message)
    if name == "task-failed":
        header = message.get("header") or {}
        detail = header.get("error_message") or header.get("error_code") or "识别任务失败"
        raise ProviderError(f"语音识别失败：{detail}")
    if name != "result-generated":
        return None
    sentence = ((message.get("payload") or {}).get("output") or {}).get("sentence") or {}
    if sentence.get("heartbeat"):
        return None
    text = str(sentence.get("text") or "").strip()
    if not text:
        return None
    return Transcript(text=text, is_final=bool(sentence.get("sentence_end")))
