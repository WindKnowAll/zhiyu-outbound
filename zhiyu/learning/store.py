"""场景话术记忆。只在审核通过后对同一场景、同一意图生效。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_BANNED = ("保证通过", "忽略", "指令", "提示词", "系统提示", "密钥", "转接真人", "稍后由审核同事", "【")
_DIGITS = re.compile(r"\d{5,}")
_INJECTION = re.compile(r"(忽略|指令|提示词|系统提示|密钥).{0,40}")


class LearningRejected(ValueError):
    pass


def desensitize(text: str) -> str:
    cleaned = _DIGITS.sub("[数字]", text or "")
    cleaned = _INJECTION.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:60]


def speak_is_allowed(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned or len(cleaned) > 180:
        raise LearningRejected("审核话术为空或太长。")
    if any(word in cleaned for word in _BANNED):
        raise LearningRejected("审核话术含有不能启用的内容。")
    return cleaned


class LearningStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "items.json"
        self._thread = threading.Lock()

    def active_speak(self, source_row: int, intent: str) -> str:
        with self._lock():
            data = self._read()
            for item in data["items"]:
                if item.get("source_row") != source_row or item.get("intent") != intent:
                    continue
                if item.get("status") == "approved" and item.get("enabled") and item.get("speak"):
                    try:
                        return speak_is_allowed(str(item["speak"]))
                    except LearningRejected:
                        return ""
            return ""

    def propose(self, *, source_row: int, intent: str, note: str, incident_id: str = "") -> dict:
        safe = desensitize(note)
        digest = hashlib.sha256(f"{source_row}|{intent}|{safe}".encode()).hexdigest()[:16]
        with self._lock():
            data = self._read()
            for item in data["items"]:
                if item.get("dedup") == digest and item.get("status") == "pending":
                    return item
            now = _now()
            item = {
                "id": uuid.uuid4().hex,
                "source_row": int(source_row),
                "intent": intent,
                "status": "pending",
                "enabled": False,
                "speak": "",
                "note": safe,
                "incident_id": incident_id,
                "dedup": digest,
                "version": 0,
                "created_at": now,
                "history": [{"at": now, "action": "propose", "speak": ""}],
            }
            data["items"].append(item)
            self._write(data)
            return item

    def approve(self, item_id: str, speak: str) -> dict:
        cleaned = speak_is_allowed(speak)
        return self._mutate(item_id, "approve", speak=cleaned, status="approved", enabled=True)

    def reject(self, item_id: str) -> dict:
        return self._mutate(item_id, "reject", status="rejected", enabled=False)

    def disable(self, item_id: str) -> dict:
        return self._mutate(item_id, "disable", status="disabled", enabled=False)

    def rollback(self, item_id: str) -> dict:
        with self._lock():
            data = self._read()
            item = self._find(data, item_id)
            previous = [step for step in item["history"] if step.get("action") == "approve"]
            if len(previous) >= 2:
                prior = previous[-2]
                item["speak"] = prior.get("speak") or ""
                item["status"] = "approved"
                item["enabled"] = True
                item["version"] = max(1, int(item.get("version") or 1) - 1)
                action = "rollback"
            else:
                item["status"] = "disabled"
                item["enabled"] = False
                action = "rollback-clear"
            item["history"].append({"at": _now(), "action": action, "speak": item.get("speak") or ""})
            self._write(data)
            return item

    def list_items(self) -> list[dict]:
        with self._lock():
            return list(self._read()["items"])

    def record_unresolved(self, *, source_row: int, session_id: str, note: str) -> bool:
        """本地待审跟进。不是已批准话术，也不会外呼派单。"""

        safe = desensitize(note) or "未解疑问"
        try:
            with self._lock():
                data = self._read()
                now = _now()
                data["items"].append(
                    {
                        "id": uuid.uuid4().hex,
                        "source_row": int(source_row),
                        "intent": "unresolved",
                        "status": "followup",
                        "enabled": False,
                        "speak": "",
                        "note": safe,
                        "session_id": session_id,
                        "dedup": "",
                        "version": 0,
                        "created_at": now,
                        "dispatch": "local_only",
                        "history": [{"at": now, "action": "followup", "speak": ""}],
                    }
                )
                self._write(data)
            return True
        except OSError:
            return False

    def _mutate(self, item_id: str, action: str, **fields: object) -> dict:
        with self._lock():
            data = self._read()
            item = self._find(data, item_id)
            if action == "approve":
                item["version"] = int(item.get("version") or 0) + 1
            item.update(fields)
            item["history"].append({"at": _now(), "action": action, "speak": item.get("speak") or ""})
            self._write(data)
            return item

    def _find(self, data: dict, item_id: str) -> dict:
        for item in data["items"]:
            if item.get("id") == item_id:
                return item
        raise LearningRejected("没有这条候选。")

    def _read(self) -> dict:
        if not self.path.is_file():
            return {"items": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"items": []}
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return {"items": []}
        return data

    def _write(self, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / f".items.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def _lock(self):
        return _FileLock(self)


class _FileLock:
    def __init__(self, store: LearningStore) -> None:
        self.store = store
        self._file = None

    def __enter__(self):
        self.store._thread.acquire()
        self.store.directory.mkdir(parents=True, exist_ok=True)
        self._file = open(self.store.directory / ".lock", "a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *_args):
        if self._file is not None:
            try:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass
            self._file.close()
        self.store._thread.release()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
