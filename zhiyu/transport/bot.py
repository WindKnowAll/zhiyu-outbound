"""为一通浏览器连接跑一条很短的 Pipecat 管线。

管线只有三段：WebRTC 输入 → 我们的处理器 → WebRTC 输出。
没有把识别、大模型、合成做成 Pipecat 自带的服务，是为了让打断和耗时
留在 ConversationEngine 里，同学可以不读框架源码就把这条链路讲清楚。
"""

from __future__ import annotations

from loguru import logger
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from zhiyu.config import Persona, Settings
from zhiyu.providers.base import ProviderError
from zhiyu.providers.factory import create_language_model, create_recognizer, create_synthesizer
from zhiyu.session import SessionHub
from zhiyu.transport.processor import VoiceSessionProcessor


async def run_bot(connection, settings: Settings, persona: Persona, hub: SessionHub) -> None:
    session = hub.open(connection.pc_id)
    logger.info("开始通话 {}", connection.pc_id)
    try:
        recognizer = create_recognizer(settings)
        language_model = create_language_model(settings)
    except ProviderError as exc:
        session.add({"type": "error", "message": str(exc)})
        logger.error(str(exc))
        return

    processor = VoiceSessionProcessor(
        settings=settings,
        persona=persona,
        session=session,
        recognizer=recognizer,
        language_model=language_model,
        tts_factory=lambda: create_synthesizer(settings),
    )
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=settings.tts_sample_rate,
            # 两帧 10ms 再送出去，播放更稳一点，代价是大约 20ms 缓冲。
            audio_out_10ms_chunks=2,
        ),
    )

    runner = WorkerRunner(handle_sigint=False)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client):
        logger.info("浏览器媒体已连通 {}", connection.pc_id)
        await processor.on_client_connected()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client):
        logger.info("浏览器媒体已断开 {}", connection.pc_id)
        session.add({"type": "status", "value": "ended"})
        await processor.shutdown()
        await runner.cancel()

    pipeline = Pipeline([transport.input(), processor, transport.output()])
    worker = PipelineWorker(
        pipeline,
        # 自定义处理器不发 Pipecat 内置的「用户正在说」帧。
        # 若打开空闲超时，学生还在听的时候通话可能被掐掉。挂断策略留给下一版。
        idle_timeout_secs=None,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=settings.tts_sample_rate,
        ),
    )
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        await processor.shutdown()
        session.add({"type": "status", "value": "ended"})
        logger.info("通话结束 {}", connection.pc_id)
