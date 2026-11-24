"""网页和 WebRTC 信令。

没有密钥时进程照常启动。页面打开后会看到缺什么、该怎么补。
真正的媒体连接要等密钥齐全才建立，避免连上之后才在日志里默默失败。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pipecat.transports.smallwebrtc.connection import IceServer
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from zhiyu.build_id import PAGE_VERSION
from zhiyu.incidents import IncidentRejected, IncidentStore, clean_session_id, parse_multipart
from zhiyu.config import (
    Settings,
    legacy_domain_warning,
    load_persona,
    load_settings,
    status_payload,
    uses_legacy_dashscope_domain,
)
from zhiyu.qualification.catalog import load_catalog
from zhiyu.providers.base import ProviderError
from zhiyu.qualification.flow import TicketStore
from zhiyu.text_debug import TextDebugSession, choose_row
from zhiyu.qualification.flow import ScenarioRejected, resolve_scenario_id, scenario_choices
from zhiyu.session import SessionHub
from zhiyu.teammate.review import (
    RateGate,
    ReviewRejected,
    ReviewStore,
    collect_config,
    eval_prompts,
    export_view,
    preview_review,
)
from zhiyu.transport.bot import run_bot
from zhiyu.turn_ice import TurnConfig

STATIC_DIR = Path(__file__).resolve().parent / "static"
ROOT = STATIC_DIR.parent.parent
PAGE_FILES = (
    "zhiyu/static/index.html",
    "zhiyu/static/app.js",
    "zhiyu/static/call_ui.js",
    "zhiyu/static/review_ui.js",
    "zhiyu/static/style.css",
    "zhiyu/static/debug.html",
    "zhiyu/static/debug.js",
)


def _form_fields(content_type: str, body: bytes) -> dict[str, tuple[str, bytes]]:
    kind = content_type.lower()
    if "multipart/form-data" in kind:
        return parse_multipart(content_type, body)
    if "application/x-www-form-urlencoded" in kind or not content_type:
        from urllib.parse import parse_qs

        parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        return {key: ("", values[0].encode("utf-8")) for key, values in parsed.items() if values}
    raise IncidentRejected("提交格式不正确。")


def candidate_kind_counts(lines: list[str]) -> dict[str, int]:
    """只数候选类型。不返回地址、端口或整段 SDP。"""

    counts = {"host": 0, "srflx": 0, "prflx": 0, "relay": 0}
    for line in lines:
        for kind in counts:
            if f"typ {kind}" in line:
                counts[kind] += 1
                break
    return counts


def page_build() -> dict:
    """这个进程实际会读的页面文件。用来核对是不是旧目录里的另一份页面。"""

    files = []
    for rel in PAGE_FILES:
        path = ROOT / rel
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": rel, "sha256": digest, "bytes": path.stat().st_size})
    return {
        "page_version": PAGE_VERSION,
        "service_worker": False,
        "scenario_count": len(scenario_choices(load_catalog())),
        "build_hash": hashlib.sha256("".join(item["sha256"] for item in files).encode()).hexdigest()[:12],
        "files": files,
    }


def scenario_options_html() -> str:
    try:
        choices = scenario_choices(load_catalog())
    except Exception as exc:
        return f'<option value="">{html.escape("场景列表没有从主表读出：" + exc.__class__.__name__)}</option>'
    if not choices:
        return '<option value="">场景列表是空的</option>'
    groups: dict[str, list[dict]] = {}
    for item in choices:
        groups.setdefault(str(item["menu"]), []).append(item)
    parts: list[str] = []
    for menu, items in groups.items():
        parts.append(f'<optgroup label="{html.escape(menu)}">')
        for item in items:
            method = "电话" if item["phone_flow"] else "京麦驳回，不编造电话话术"
            gap = "" if item["script_complete"] else "，话术不完整"
            label = f'{item["category"]} / {item["reason"]}（{method}{gap}）'
            parts.append(f'<option value="{html.escape(str(item["row"]))}">{html.escape(label)}</option>')
        parts.append("</optgroup>")
    return "".join(parts)


def render_index() -> str:
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    text = text.replace("<!--SCENARIOS-->", scenario_options_html())
    return text.replace("<!--BUILD-->", page_build()["build_hash"])


def parse_call_vad(raw: object, settings: Settings) -> dict | None:
    """只接受已经接在 Silero 上的三项。不接受把定稿等待调大。"""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("开口检测参数不正确。")

    def pick(name: str, default: float, low: float, high: float) -> float:
        if name not in raw or raw[name] is None:
            return default
        try:
            value = float(raw[name])
        except (TypeError, ValueError) as exc:
            raise ValueError("开口检测参数不正确。") from exc
        if not low <= value <= high:
            raise ValueError(f"{name} 超出这次允许的范围。")
        return value

    return {
        "confidence": pick("confidence", settings.vad_confidence, 0.5, 0.95),
        "start_secs": pick("start_secs", settings.vad_start_secs, 0.1, 0.6),
        "min_volume": pick("min_volume", settings.vad_min_volume, 0.2, 0.95),
    }


def create_app(
    settings: Settings | None = None,
    *,
    preload_vad: bool = False,
    review_dir: Path | None = None,
    incident_dir: Path | None = None,
    ticket_dir: Path | None = None,
    collect_enabled: bool | None = None,
    collect_token: str | None = None,
    collect_submit_token: str | None = None,
    call_token: str | None = None,
    text_model=None,
) -> FastAPI:
    settings = settings or load_settings()
    persona = load_persona()
    hub = SessionHub()
    reviews = ReviewStore(review_dir or (ROOT / "var" / "teammate_reviews"))
    incidents = IncidentStore(incident_dir or (ROOT / "var" / "incidents"))
    tickets = TicketStore(ticket_dir or (ROOT / "var" / "mock_tickets"))
    text_sessions: dict[str, TextDebugSession] = {}
    collect_on, admin_token, submit_token = collect_config(
        collect_enabled, collect_token, collect_submit_token
    )
    if call_token is None:
        call_token = os.environ.get("ZHIYU_CALL_TOKEN", "")
    call_token = call_token.strip()
    if call_token and len(call_token) < 16:
        logger.warning("ZHIYU_CALL_TOKEN 短于 16 位，已忽略，没有启用通话口令。")
        call_token = ""
    local_gate = RateGate(30, 600)
    collect_gate = RateGate(10, 60)
    ice_gate = RateGate(30, 60)
    incident_gate = RateGate(20, 60)
    turn = TurnConfig(
        secret=settings.turn_secret,
        public_host=settings.turn_public_host,
        listen_host=settings.turn_listen_host,
        port=settings.turn_port,
        ttl_seconds=settings.turn_ttl,
        min_port=settings.turn_min_port,
        max_port=settings.turn_max_port,
    )
    if settings.turn_secret and not turn.enabled:
        logger.warning("TURN 密钥或地址不完整，没有启用。没有把密钥写进日志。")
    ice_lock = asyncio.Lock()
    webrtc = SmallWebRTCRequestHandler(ice_servers=turn.aiortc_servers(settings.ice_servers) or None)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if not settings.credentials_ready:
            logger.warning(status_payload(settings)["message"])
        else:
            logger.info(
                "已读到 DASHSCOPE_API_KEY，模型 {} / {} / {}，发往 {}（{}）",
                settings.llm_model,
                settings.asr_model,
                settings.tts_model,
                settings.dashscope_host,
                settings.dashscope_endpoint_source,
            )
            logger.info("千问 {} | 语音 {}", settings.dashscope_base_url, settings.dashscope_ws_url)
            if uses_legacy_dashscope_domain(settings):
                logger.warning(legacy_domain_warning())
        if preload_vad:
            _preload_silero()
        yield
        await webrtc.close()

    app = FastAPI(title="智语外呼", lifespan=lifespan)
    app.state.settings = settings
    app.state.hub = hub

    @app.middleware("http")
    async def do_not_cache_pages(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/status")
    async def status() -> dict:
        return status_payload(settings)

    @app.get("/api/build")
    async def build() -> dict:
        return page_build()

    @app.get("/api/scenarios")
    async def scenarios() -> dict:
        catalog = load_catalog()
        return {
            "simulation": True,
            "notice": "比赛模拟，商家是合成数据，不是京东官方服务。",
            "counts": {
                "场景汇总": catalog.audit["场景汇总"],
                "电话": catalog.audit["电话"],
                "京麦驳回": catalog.audit["京麦驳回"],
            },
            "scenarios": scenario_choices(catalog),
        }

    @app.get("/api/sessions/{pc_id}")
    async def session_events(pc_id: str, request: Request, cursor: int = 0) -> dict:
        if call_token and request.headers.get("x-zhiyu-call-token", "") != call_token:
            raise HTTPException(status_code=401, detail="需要通话口令。")
        session = hub.get(pc_id)
        if session is None:
            raise HTTPException(status_code=404, detail="这通通话还不存在，或已经不在内存里。")
        events = session.since(cursor)
        next_cursor = events[-1]["id"] + 1 if events else cursor
        return {"cursor": cursor, "next": next_cursor, "events": events}

    @app.post("/api/offer")
    async def offer(request: Request, background_tasks: BackgroundTasks):
        payload = await request.json()
        scenario_raw = payload.pop("scenario_id", None)
        vad_raw = payload.pop("vad", None)
        try:
            scenario_row = resolve_scenario_id(scenario_raw, load_catalog())
            vad_override = parse_call_vad(vad_raw, settings)
        except (ScenarioRejected, ValueError) as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if call_token and request.headers.get("x-zhiyu-call-token", "") != call_token:
            return JSONResponse(status_code=401, content={"message": "需要通话口令。没有口令不会连接模型。"})
        if not settings.credentials_ready:
            return JSONResponse(status_code=503, content=status_payload(settings))
        rtc_request = SmallWebRTCRequest.from_dict(payload)

        async def start_bot(connection) -> None:
            background_tasks.add_task(
                run_bot,
                connection,
                settings,
                persona,
                hub,
                scenario_row,
                vad_override,
            )

        async with ice_lock:
            webrtc.update_ice_servers(turn.aiortc_servers(settings.ice_servers) or None)
            answer = await webrtc.handle_web_request(rtc_request, start_bot)
        sdp = answer.get("sdp") if isinstance(answer, dict) else ""
        if isinstance(sdp, str) and sdp:
            counts = candidate_kind_counts(sdp.splitlines())
            logger.info(
                "应答候选 host={} srflx={} prflx={} relay={}",
                counts["host"],
                counts["srflx"],
                counts["prflx"],
                counts["relay"],
            )
        return answer

    @app.patch("/api/offer")
    async def ice_candidate(request: Request) -> dict:
        if call_token and request.headers.get("x-zhiyu-call-token", "") != call_token:
            raise HTTPException(status_code=401, detail="需要通话口令。")
        payload = await request.json()
        raw_candidates = payload.get("candidates") or []
        counts = candidate_kind_counts(
            [str(item.get("candidate") or "") for item in raw_candidates if isinstance(item, dict)]
        )
        logger.info(
            "收到浏览器候选 host={} srflx={} prflx={} relay={}",
            counts["host"],
            counts["srflx"],
            counts["prflx"],
            counts["relay"],
        )
        candidates = [
            IceCandidate(
                candidate=item["candidate"],
                sdp_mid=item.get("sdp_mid") or "",
                sdp_mline_index=int(item.get("sdp_mline_index") or 0),
            )
            for item in raw_candidates
        ]
        patch = SmallWebRTCPatchRequest(pc_id=payload["pc_id"], candidates=candidates)
        await webrtc.handle_patch_request(patch)
        return {"status": "success"}

    def _bearer(request: Request) -> str:
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer "):
            return header.removeprefix("Bearer ").strip()
        return ""

    def _admin(request: Request) -> None:
        if not collect_on:
            raise HTTPException(status_code=404, detail="集中收集没有启用。")
        if _bearer(request) != admin_token:
            raise HTTPException(status_code=401, detail="需要管理员令牌。")

    def _pasted_secret(payload: object) -> bool:
        try:
            blob = json.dumps(payload, ensure_ascii=False)
        except TypeError:
            return False
        return any(token and token in blob for token in (admin_token, submit_token, call_token))

    def _submit(request: Request) -> None:
        if not collect_on:
            raise HTTPException(status_code=404, detail="集中收集没有启用。")
        token = _bearer(request)
        if token not in {admin_token, submit_token}:
            raise HTTPException(status_code=401, detail="需要提交令牌。")

    @app.get("/api/ice")
    async def ice(request: Request) -> JSONResponse:
        if call_token and request.headers.get("x-zhiyu-call-token", "") != call_token:
            return JSONResponse(status_code=401, content={"message": "需要通话口令。没有口令不会分配中继。"})
        who = request.client.host if request.client else "ice"
        if not ice_gate.allow(who):
            return JSONResponse(status_code=429, content={"message": "申请太频繁，请稍后再试。"})
        servers = turn.browser_servers(settings.ice_servers)
        return JSONResponse(
            {
                "ice_servers": servers,
                "ttl_seconds": turn.ttl_seconds if turn.enabled else 0,
                "turn_enabled": turn.enabled,
            }
        )

    def _call_gate(request: Request, message: str) -> JSONResponse | None:
        if call_token and request.headers.get("x-zhiyu-call-token", "") != call_token:
            return JSONResponse(status_code=401, content={"message": message})
        return None

    def _incident_reader(request: Request) -> JSONResponse | None:
        if not collect_on:
            return None
        if _bearer(request) != admin_token:
            return JSONResponse(status_code=401, content={"message": "需要管理员令牌。"})
        return None

    @app.post("/api/incidents")
    async def incident_save(request: Request) -> JSONResponse:
        denied = _call_gate(request, "需要通话口令。没有口令不会提交异常。")
        if denied is not None:
            return denied
        who = request.client.host if request.client else "incident"
        if not incident_gate.allow(who):
            return JSONResponse(status_code=429, content={"message": "提交太频繁，请稍后再试。"})
        raw_body = await request.body()
        if len(raw_body) > 6 * 1024 * 1024:
            return JSONResponse(status_code=400, content={"message": "请求超过 6MB。"})
        try:
            fields = _form_fields(request.headers.get("content-type", ""), raw_body)
        except IncidentRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        text = fields.get("text", ("", b""))[1].decode("utf-8", errors="replace")
        call_session_id = fields.get("call_session_id", ("", b""))[1].decode("utf-8", errors="replace")
        image = fields.get("image", ("", b""))[1]
        if _pasted_secret({"text": text, "call_session_id": call_session_id}):
            return JSONResponse(status_code=400, content={"message": "内容里不能带密钥或口令。"})
        try:
            session_id = clean_session_id(call_session_id)
        except IncidentRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        raw = image
        try:
            saved = incidents.save(
                text=text,
                session_id=session_id,
                image=raw or None,
                ticket_names=[],
            )
            names = tickets.attach_incident(session_id, saved["text"], saved["image"])
            if names:
                saved = incidents.mark_attached(saved["id"], names)
        except IncidentRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        return JSONResponse(
            {
                "ok": True,
                "id": saved["id"],
                "call_session_id": saved["call_session_id"],
                "ticket_attached": saved["ticket_attached"],
                "image": saved["image"],
                "message": "提交成功",
            }
        )

    @app.get("/api/incidents/export")
    async def incident_export(request: Request) -> JSONResponse:
        denied = _incident_reader(request)
        if denied is not None:
            return denied
        return JSONResponse(
            {"incidents": incidents.list_records(), "raw_audio": False},
            headers={"Content-Disposition": 'attachment; filename="zhiyu-incident-notes.json"'},
        )

    @app.get("/api/incidents")
    async def incident_list(request: Request) -> JSONResponse:
        denied = _incident_reader(request)
        if denied is not None:
            return denied
        return JSONResponse({"incidents": incidents.list_records(), "raw_audio": False})

    @app.get("/api/incidents/{incident_id}/image")
    async def incident_image(incident_id: str, request: Request):
        denied = _incident_reader(request)
        if denied is not None:
            return denied
        try:
            found = incidents.get(incident_id)
        except IncidentRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if found is None or not found.get("image"):
            raise HTTPException(status_code=404, detail="没有这张图片。")
        try:
            path = incidents.image_file(str(found["image"]))
        except IncidentRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if not path.is_file():
            raise HTTPException(status_code=404, detail="没有这张图片。")
        return FileResponse(path, filename=path.name)

    @app.get("/api/voices")
    async def voices() -> dict:
        return {
            "model": settings.tts_model,
            "voices": [{"id": settings.tts_voice, "usable": True, "engine": "cosyvoice"}],
            "unsupported": "浏览器自带语音，包括 Microsoft 语音，不会送进 CosyVoice。",
        }

    @app.get("/api/collection")
    async def collection() -> dict:
        return {
            "enabled": collect_on,
            "mode": "central_admin" if collect_on else "local_export",
            "public_ready": False,
            "call_gate": bool(call_token),
            "https_terminated_here": False,
            "raw_audio": False,
            "autosend": False,
            "rsi": "human_review_only",
        }

    @app.get("/api/eval-prompts")
    async def prompts() -> dict:
        return {"status": "criteria_only", "prompts": eval_prompts()}

    @app.post("/api/reviews/preview")
    async def review_preview(request: Request) -> JSONResponse:
        try:
            body = preview_review(await request.json())
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        return JSONResponse(body)

    def _reviews_closed() -> JSONResponse | None:
        if not collect_on:
            return None
        return JSONResponse(
            status_code=403,
            content={"message": "集中收集已开启。写入请使用提交令牌访问 /api/collect。列表仅管理员可看。"},
        )

    @app.post("/api/reviews")
    async def review_save(request: Request) -> JSONResponse:
        closed = _reviews_closed()
        if closed is not None:
            return closed
        payload = await request.json()
        if _pasted_secret(payload):
            return JSONResponse(status_code=400, content={"message": "记录里不能带密钥或口令。"})
        who = str(payload.get("pseudonym") or "")
        if not local_gate.allow(who or request.client.host if request.client else "local"):
            return JSONResponse(status_code=429, content={"message": "保存太频繁，请稍后再试。"})
        try:
            saved = reviews.save(payload)
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        return JSONResponse(saved)

    @app.get("/api/reviews", response_model=None)
    async def review_list(pseudonym: str = ""):
        closed = _reviews_closed()
        if closed is not None:
            return closed
        return {"reviews": reviews.list_reviews(pseudonym or None), "raw_audio": False}

    @app.get("/api/reviews/{review_id}")
    async def review_detail(review_id: str) -> JSONResponse:
        closed = _reviews_closed()
        if closed is not None:
            return closed
        try:
            found = reviews.get(review_id)
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if found is None:
            raise HTTPException(status_code=404, detail="没有这条记录。")
        return JSONResponse(export_view(found))

    @app.get("/api/reviews/{review_id}/export")
    async def review_export(review_id: str) -> JSONResponse:
        closed = _reviews_closed()
        if closed is not None:
            return closed
        try:
            found = reviews.get(review_id)
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if found is None:
            raise HTTPException(status_code=404, detail="没有这条记录。")
        return JSONResponse(
            export_view(found),
            headers={"Content-Disposition": f'attachment; filename="{review_id}.json"'},
        )

    @app.delete("/api/reviews/{review_id}")
    async def review_delete(review_id: str) -> JSONResponse:
        closed = _reviews_closed()
        if closed is not None:
            return closed
        try:
            removed = reviews.delete(review_id)
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if not removed:
            raise HTTPException(status_code=404, detail="没有这条记录。")
        return JSONResponse({"deleted": True})

    @app.post("/api/reviews/import")
    async def review_import(request: Request) -> JSONResponse:
        closed = _reviews_closed()
        if closed is not None:
            return closed
        if not local_gate.allow("import"):
            return JSONResponse(status_code=429, content={"message": "导入太频繁，请稍后再试。"})
        payload = await request.json()
        if _pasted_secret(payload):
            return JSONResponse(status_code=400, content={"message": "记录里不能带密钥或口令。"})
        try:
            saved = reviews.import_record(payload)
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        return JSONResponse(saved)

    @app.post("/api/collect")
    async def collect_save(request: Request) -> JSONResponse:
        if not collect_on:
            raise HTTPException(status_code=404, detail="集中收集没有启用。请改用本机导出。")
        _submit(request)
        payload = await request.json()
        if _pasted_secret(payload):
            return JSONResponse(status_code=400, content={"message": "记录里不能带密钥或口令。"})
        who = str(payload.get("pseudonym") or "")
        if not collect_gate.allow(who or "collect"):
            return JSONResponse(status_code=429, content={"message": "提交太频繁，请稍后再试。"})
        try:
            saved = reviews.save(payload)
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        return JSONResponse(
            {
                "id": saved["id"],
                "pseudonym": saved["pseudonym"],
                "duplicate": bool(saved.get("duplicate")),
                "call_link": saved.get("call_link") or "unspecified",
            }
        )

    @app.get("/api/collect/export")
    async def collect_export(request: Request, only: str = "") -> JSONResponse:
        if not collect_on:
            raise HTTPException(status_code=404, detail="集中收集没有启用。")
        _admin(request)
        if only not in {"", "incident"}:
            return JSONResponse(status_code=400, content={"message": "只能导出全部或异常。"})
        return JSONResponse(
            {
                "schema": "zhiyu.incident_export.v1",
                "raw_audio": False,
                "rsi": "human_review_only",
                "autosend": False,
                "reviews": reviews.export_records(incidents_only=only == "incident"),
            },
            headers={"Content-Disposition": 'attachment; filename="zhiyu-incidents.json"'},
        )

    @app.get("/api/collect/{review_id}")
    async def collect_one(review_id: str, request: Request) -> JSONResponse:
        if not collect_on:
            raise HTTPException(status_code=404, detail="集中收集没有启用。")
        _admin(request)
        try:
            found = reviews.get(review_id)
        except ReviewRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if found is None:
            raise HTTPException(status_code=404, detail="没有这条记录。")
        return JSONResponse(export_view(found))

    @app.get("/api/collect")
    async def collect_list(request: Request, pseudonym: str = "") -> JSONResponse:
        if not collect_on:
            raise HTTPException(status_code=404, detail="集中收集没有启用。")
        _admin(request)
        return JSONResponse({"reviews": reviews.list_reviews(pseudonym or None)})

    def _text_model():
        if text_model is not None:
            return text_model
        from zhiyu.providers.factory import create_language_model

        return create_language_model(settings)

    @app.get("/debug")
    async def debug_page() -> HTMLResponse:
        page = (STATIC_DIR / "debug.html").read_text(encoding="utf-8")
        return HTMLResponse(
            page,
            headers={
                "Cache-Control": "no-store",
                "Permissions-Policy": "microphone=(), camera=(), display-capture=()",
            },
        )

    @app.post("/api/debug/session")
    async def debug_start(request: Request) -> JSONResponse:
        denied = _call_gate(request, "需要通话口令。没有口令不会连接模型。")
        if denied is not None:
            return denied
        if not settings.credentials_ready and text_model is None:
            return JSONResponse(status_code=503, content=status_payload(settings))
        payload = await request.json()
        try:
            row = choose_row(load_catalog(), payload.get("scenario_id"), bool(payload.get("random")))
            session = TextDebugSession(load_catalog(), row, tickets)
            session.model = _text_model()
        except ProviderError as exc:
            return JSONResponse(status_code=503, content={"message": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if len(text_sessions) > 40:
            text_sessions.pop(next(iter(text_sessions)))
        text_sessions[session.session_id] = session
        return JSONResponse(
            {
                "session_id": session.session_id,
                "row": session.row,
                "opening": session.opening(),
                "audio": False,
            }
        )

    @app.post("/api/debug/session/{session_id}/say")
    async def debug_say(session_id: str, request: Request) -> JSONResponse:
        denied = _call_gate(request, "需要通话口令。没有口令不会连接模型。")
        if denied is not None:
            return denied
        session = text_sessions.get(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"message": "这场文字调试已经不在。请重新开始。"})
        payload = await request.json()
        text = str(payload.get("text") or "").strip()
        if not text:
            return JSONResponse(status_code=400, content={"message": "请先打字。"})
        if len(text) > 2000:
            return JSONResponse(status_code=400, content={"message": "这句话太长。"})
        try:
            result = await session.say(text)
        except ProviderError as exc:
            return JSONResponse(status_code=502, content={"message": str(exc)})
        except Exception as exc:
            logger.exception("文字调试失败")
            return JSONResponse(status_code=502, content={"message": "模型没有返回。输入还在，可以再试。"})
        result["audio"] = False
        return JSONResponse(result)

    @app.post("/api/debug/session/{session_id}/end")
    async def debug_end(session_id: str, request: Request) -> JSONResponse:
        denied = _call_gate(request, "需要通话口令。")
        if denied is not None:
            return denied
        session = text_sessions.pop(session_id, None)
        if session is None:
            return JSONResponse(status_code=404, content={"message": "这场文字调试已经不在。"})
        done = session.finish()
        for item in incidents.list_records():
            if item.get("call_session_id") != done["call_session_id"]:
                continue
            names = tickets.attach_incident(
                done["call_session_id"],
                str(item.get("text") or ""),
                str(item.get("image") or ""),
            )
            if names:
                incidents.mark_attached(str(item["id"]), names)
        return JSONResponse(done)

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(render_index(), headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _preload_silero() -> None:
    """启动时加载一次模型，确认镜像里带了 onnx 文件。每通电话仍会自己建一个分析器。"""

    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer

        analyzer = SileroVADAnalyzer(sample_rate=16000)
        analyzer.set_sample_rate(16000)
        logger.info("Silero VAD 模型已加载")
    except Exception:
        logger.exception("Silero VAD 模型没有加载成功，接通后将无法判断用户是否在说话")


def main() -> None:
    load_dotenv(override=False)
    settings = load_settings()
    parser = argparse.ArgumentParser(description="智语外呼")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)

    app = create_app(settings, preload_vad=True)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
