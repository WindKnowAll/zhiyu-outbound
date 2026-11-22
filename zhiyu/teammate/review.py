"""本机试听记录的校验、预览和导出。

集中收集默认关闭。启用时也只接受管理员令牌，页面里不放令牌。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

SCHEMA = "zhiyu.teammate_review.v1"
PROVIDER_STATUS = {"success", "empty", "unparsed", "error"}
EVAL_PROMPTS = (
    {
        "id": "stop-why",
        "utterance": "嗯，停停停，等一下，为什么被驳回了",
        "expect": "先停住，再说明原表里已经写明的原因。不把同一句空泛的材料不全再说一遍。",
        "status": "criteria_only",
    },
    {
        "id": "where-feedback",
        "utterance": "在哪里得到反馈，能转人工吗",
        "expect": "只说明这条原表的关单方式。不新编热线，不自称京东官方，不假装已经转接。",
        "status": "criteria_only",
    },
)
_SECRET = re.compile(r"sk-|api[_-]?key|authorization|bearer\s+", re.I)
_PHONE = re.compile(r"\d{7,}")


class ReviewRejected(ValueError):
    pass


class RateGate:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        kept = [item for item in self._hits.get(key, []) if moment - item < self.window]
        if len(kept) >= self.limit:
            self._hits[key] = kept
            return False
        kept.append(moment)
        self._hits[key] = kept
        return True


def collect_config(
    enabled: bool | None = None,
    token: str | None = None,
    submit_token: str | None = None,
) -> tuple[bool, str, str]:
    """默认关闭。管理员令牌和提交令牌必须不同，且都至少 16 位。"""

    if enabled is None:
        enabled = os.environ.get("ZHIYU_COLLECT_ENABLED") == "1"
    if token is None:
        token = os.environ.get("ZHIYU_ADMIN_TOKEN", "")
    if submit_token is None:
        submit_token = os.environ.get("ZHIYU_SUBMIT_TOKEN", "")
    token = token.strip()
    submit_token = submit_token.strip()
    if not enabled or len(token) < 16 or len(submit_token) < 16 or token == submit_token:
        return False, "", ""
    return True, token, submit_token


def eval_prompts() -> list[dict]:
    return [dict(item) for item in EVAL_PROMPTS]


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise ReviewRejected("文本字段必须是字符串。")
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise ReviewRejected("文本超过长度。")
    if _SECRET.search(cleaned):
        raise ReviewRejected("记录里不能带密钥或口令。")
    return cleaned


def _pseudonym(value: object) -> str:
    text = _text(value, 16)
    if not text or "@" in text or _PHONE.search(text):
        raise ReviewRejected("请用短代号，不要写手机号或邮箱。")
    return text


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReviewRejected("耗时必须是数字或空。")
    number = float(value)
    if number < 0 or number > 120_000:
        raise ReviewRejected("耗时不在可记录的范围内。")
    return number


def validate_review(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ReviewRejected("记录必须是一个对象。")
    if payload.get("schema") != SCHEMA:
        raise ReviewRejected("记录版本不受支持。")
    if payload.get("synthetic") is not True:
        raise ReviewRejected("必须标明这是合成商家的比赛模拟。")
    if payload.get("raw_audio") is not False:
        raise ReviewRejected("不接收录音。raw_audio 必须为 false。")
    if payload.get("consent") is not True:
        raise ReviewRejected("需要测试者同意才保存。")
    scenario = payload.get("scenario") or {}
    if not isinstance(scenario, dict):
        raise ReviewRejected("场景必须是对象。")
    row = scenario.get("row")
    if not isinstance(row, int) or isinstance(row, bool) or not 1 <= row <= 200:
        raise ReviewRejected("场景行号不正确。")
    turns_in = payload.get("turns") or []
    traces_in = payload.get("provider_traces") or []
    timings_in = payload.get("stage_timings") or []
    if not isinstance(turns_in, list) or len(turns_in) > 200:
        raise ReviewRejected("对话轮次不正确。")
    if not isinstance(traces_in, list) or not isinstance(timings_in, list):
        raise ReviewRejected("状态或耗时不是列表。")
    turns = []
    for item in turns_in:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            raise ReviewRejected("对话角色不正确。")
        turns.append(
            {
                "role": item["role"],
                "text": _text(item.get("text") or "", 2000),
                "false_barge_in": bool(item.get("false_barge_in")),
            }
        )
    traces = []
    for item in traces_in:
        if not isinstance(item, dict):
            raise ReviewRejected("模型状态不正确。")
        status = item.get("provider_status")
        if status not in PROVIDER_STATUS:
            raise ReviewRejected("provider_status 只能是 success、empty、unparsed 或 error。")
        traces.append(
            {
                "turn_id": item.get("turn_id") if isinstance(item.get("turn_id"), int) else None,
                "provider_called": bool(item.get("provider_called")),
                "provider_status": status,
                "intent": _text(str(item.get("intent") or ""), 40),
                "fallback_reason": _text(str(item.get("fallback_reason") or ""), 80),
                "script_missing": bool(item.get("script_missing")),
                "llm_first_token_ms": _number(item.get("llm_first_token_ms")),
            }
        )
    timings = []
    for item in timings_in:
        if not isinstance(item, dict):
            raise ReviewRejected("分段耗时不正确。")
        timings.append(
            {
                "asr_final_ms": _number(item.get("asr_final_ms")),
                "llm_first_token_ms": _number(item.get("llm_first_token_ms")),
                "tts_first_audio_ms": _number(item.get("tts_first_audio_ms")),
                "first_audio_e2e_ms": _number(item.get("first_audio_e2e_ms")),
            }
        )
    feedback = payload.get("feedback") or {}
    if not isinstance(feedback, dict):
        raise ReviewRejected("反馈必须是对象。")
    audio = payload.get("audio_constraints") or {}
    vad = payload.get("vad") or {}
    record = {
        "schema": SCHEMA,
        "synthetic": True,
        "raw_audio": False,
        "consent": True,
        "pseudonym": _pseudonym(payload.get("pseudonym")),
        "page_version": _text(payload.get("page_version") or "", 40),
        "scenario": {
            "row": row,
            "menu": _text(str(scenario.get("menu") or ""), 40),
            "category": _text(str(scenario.get("category") or ""), 40),
            "reason": _text(str(scenario.get("reason") or ""), 80),
            "close_method": _text(str(scenario.get("close_method") or ""), 20),
            "script_complete": bool(scenario.get("script_complete")),
        },
        "session_id": _text(str(payload.get("session_id") or ""), 80),
        "turns": turns,
        "provider_traces": traces,
        "stage_timings": timings,
        "feedback": {
            "expected": _text(str(feedback.get("expected") or ""), 2000),
            "actual": _text(str(feedback.get("actual") or ""), 2000),
        },
        "audio_constraints": {
            "echoCancellation": bool(audio.get("echoCancellation")),
            "noiseSuppression": bool(audio.get("noiseSuppression")),
        },
        "vad": {
            "confidence": _number(vad.get("confidence")),
            "start_secs": _number(vad.get("start_secs")),
            "min_volume": _number(vad.get("min_volume")),
        },
        "false_barge_in_count": sum(1 for item in turns if item["false_barge_in"]),
        "collection": "local_export_not_rsi",
    }
    return record


def preview_review(payload: object) -> dict:
    record = validate_review(payload)
    return {
        "ok": True,
        "stored": False,
        "warnings": ["这是预览，还没有保存，也不会自动发送。", "录音没有包含在内。"],
        "record": record,
    }


class ReviewStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()

    def save(self, payload: object) -> dict:
        record = validate_review(payload)
        record["id"] = str(uuid.uuid4())
        record["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["imported"] = False
        self._write(record)
        return record

    def import_record(self, payload: object) -> dict:
        record = validate_review(payload)
        record["id"] = str(uuid.uuid4())
        record["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["imported"] = True
        self._write(record)
        return record

    def list_reviews(self, pseudonym: str | None = None) -> list[dict]:
        rows = []
        with self._lock:
            paths = sorted(self.directory.glob("*.json")) if self.directory.is_dir() else []
            for path in paths:
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if pseudonym and item.get("pseudonym") != pseudonym:
                    continue
                rows.append(
                    {
                        "id": item.get("id"),
                        "pseudonym": item.get("pseudonym"),
                        "saved_at": item.get("saved_at"),
                        "page_version": item.get("page_version"),
                        "scenario_row": (item.get("scenario") or {}).get("row"),
                        "turn_count": len(item.get("turns") or []),
                        "imported": bool(item.get("imported")),
                        "raw_audio": False,
                    }
                )
        return rows

    def get(self, review_id: str) -> dict | None:
        path = self._path(review_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, review_id: str) -> bool:
        path = self._path(review_id)
        with self._lock:
            if not path.is_file():
                return False
            path.unlink()
            return True

    def _path(self, review_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{36}", str(review_id)):
            raise ReviewRejected("记录编号不正确。")
        return self.directory / f"{review_id}.json"

    def _write(self, record: dict) -> None:
        path = self._path(record["id"])
        payload = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, path)
