"""网页和 WebRTC 信令。

没有密钥时进程照常启动。页面打开后会看到缺什么、该怎么补。
真正的媒体连接要等密钥齐全才建立，避免连上之后才在日志里默默失败。
"""

from __future__ import annotations

import argparse
import hashlib
import html
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
from zhiyu.config import (
    Settings,
    legacy_domain_warning,
    load_persona,
    load_settings,
    status_payload,
    uses_legacy_dashscope_domain,
)
from zhiyu.qualification.catalog import load_catalog
from zhiyu.qualification.flow import ScenarioRejected, resolve_scenario_id, scenario_choices
from zhiyu.session import SessionHub
from zhiyu.transport.bot import run_bot

STATIC_DIR = Path(__file__).resolve().parent / "static"
ROOT = STATIC_DIR.parent.parent
PAGE_FILES = (
    "zhiyu/static/index.html",
    "zhiyu/static/app.js",
    "zhiyu/static/call_ui.js",
    "zhiyu/static/style.css",
)


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
    return text.replace("<!--SCENARIOS-->", scenario_options_html())


def create_app(settings: Settings | None = None, *, preload_vad: bool = False) -> FastAPI:
    settings = settings or load_settings()
    persona = load_persona()
    hub = SessionHub()
    ice_servers = [IceServer(urls=url) for url in settings.ice_servers] or None
    webrtc = SmallWebRTCRequestHandler(ice_servers=ice_servers)

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
    async def session_events(pc_id: str, cursor: int = 0) -> dict:
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
        try:
            scenario_row = resolve_scenario_id(scenario_raw, load_catalog())
        except ScenarioRejected as exc:
            return JSONResponse(status_code=400, content={"message": str(exc)})
        if not settings.credentials_ready:
            return JSONResponse(status_code=503, content=status_payload(settings))
        rtc_request = SmallWebRTCRequest.from_dict(payload)

        async def start_bot(connection) -> None:
            background_tasks.add_task(
                run_bot, connection, settings, persona, hub, scenario_row
            )

        answer = await webrtc.handle_web_request(rtc_request, start_bot)
        return answer

    @app.patch("/api/offer")
    async def ice_candidate(request: Request) -> dict:
        payload = await request.json()
        candidates = [
            IceCandidate(
                candidate=item["candidate"],
                sdp_mid=item.get("sdp_mid") or "",
                sdp_mline_index=int(item.get("sdp_mline_index") or 0),
            )
            for item in payload.get("candidates") or []
        ]
        patch = SmallWebRTCPatchRequest(pc_id=payload["pc_id"], candidates=candidates)
        await webrtc.handle_patch_request(patch)
        return {"status": "success"}

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
