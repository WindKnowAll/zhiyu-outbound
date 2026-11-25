"""异常说明和一张可选图片。文件名由服务端生成，不采用浏览器传来的路径。"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Pipecat 1.15 的 pc_id 是 SmallWebRTCConnection#N-加 32 位十六进制。# 必须留下。
_SESSION = re.compile(r"[A-Za-z0-9_.:#-]{0,120}")
_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp|heic)")


class IncidentRejected(ValueError):
    pass


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heif"}:
            return "heic"
    return None


def parse_multipart(content_type: str, body: bytes) -> dict[str, tuple[str, bytes]]:
    """只取 text、call_session_id 和可选的 image。不使用浏览器传来的路径。"""

    marker = ""
    for piece in content_type.split(";"):
        item = piece.strip()
        if item.lower().startswith("boundary="):
            marker = item.split("=", 1)[1].strip().strip('"')
    if not marker:
        raise IncidentRejected("提交格式不正确。")
    delimiter = b"--" + marker.encode("utf-8", errors="ignore")
    fields: dict[str, tuple[str, bytes]] = {}
    for part in body.split(delimiter):
        if not part or part in (b"--", b"--\r\n") or part.startswith(b"--"):
            continue
        chunk = part
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if chunk.endswith(b"--"):
            chunk = chunk[:-2]
            if chunk.endswith(b"\r\n"):
                chunk = chunk[:-2]
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        header = head.decode("utf-8", errors="replace")
        name = ""
        filename = ""
        for line in header.split("\r\n"):
            if "name=" not in line.lower():
                continue
            bits = line.split(";")
            for bit in bits:
                item = bit.strip()
                lower = item.lower()
                if lower.startswith("name="):
                    name = item.split("=", 1)[1].strip().strip('"')
                elif lower.startswith("filename="):
                    filename = item.split("=", 1)[1].strip().strip('"')
        if name in {"text", "call_session_id", "image"}:
            fields[name] = (filename, data)
    return fields


def clean_session_id(value: str) -> str:
    text = (value or "").strip()
    if ".." in text or not _SESSION.fullmatch(text):
        raise IncidentRejected("通话编号格式不正确。")
    return text


class IncidentStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.image_dir = directory / "images"
        self._lock = threading.Lock()

    def save(self, *, text: str, session_id: str, image: bytes | None, ticket_names: list[str]) -> dict:
        cleaned = text.strip()
        if not cleaned:
            raise IncidentRejected("请先写一段具体情况。")
        if len(cleaned) > 2000:
            raise IncidentRejected("文字超过 2000 字。")
        image_name = ""
        if image:
            if len(image) > MAX_IMAGE_BYTES:
                raise IncidentRejected("图片超过 5MB。")
            kind = sniff_image(image)
            if kind is None:
                raise IncidentRejected("图片格式不支持。请用 jpg、png、webp 或 heic。")
            image_name = f"{uuid.uuid4().hex}.{kind}"
            if not _NAME.fullmatch(image_name):
                raise IncidentRejected("图片没有保存。")
        record = {
            "id": uuid.uuid4().hex,
            "call_session_id": session_id,
            "text": cleaned,
            "image": image_name,
            "ticket_files": list(ticket_names),
            "ticket_attached": bool(ticket_names),
            "raw_audio": False,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            if image and image_name:
                self.image_dir.mkdir(parents=True, exist_ok=True)
                target = self._image_file(image_name)
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(image)
                temporary.replace(target)
            path = self.directory / f"{record['id']}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def mark_attached(self, incident_id: str, ticket_names: list[str]) -> dict:
        found = self.get(incident_id)
        if found is None:
            raise IncidentRejected("记录没有保存。")
        found["ticket_files"] = list(ticket_names)
        found["ticket_attached"] = bool(ticket_names)
        path = self.directory / f"{incident_id}.json"
        path.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
        return found

    def list_records(self) -> list[dict]:
        rows = []
        if not self.directory.is_dir():
            return rows
        for path in sorted(self.directory.glob("*.json")):
            if path.parent.resolve() != self.directory.resolve():
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(item, dict) and item.get("id"):
                rows.append(item)
        return rows

    def get(self, incident_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{32}", incident_id):
            raise IncidentRejected("记录编号不正确。")
        path = self.directory / f"{incident_id}.json"
        if path.parent.resolve() != self.directory.resolve() or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def image_file(self, name: str) -> Path:
        return self._image_file(name)

    def _image_file(self, name: str) -> Path:
        if not _NAME.fullmatch(name) or "/" in name or "\\" in name or ".." in name:
            raise IncidentRejected("图片路径不正确。")
        path = (self.image_dir / name).resolve()
        if path.parent != self.image_dir.resolve():
            raise IncidentRejected("图片路径不正确。")
        return path
