"""Pipecat 里的一个处理器：麦克风进来，回复的声音出去。

WebRTC 的收发、重采样、播放缓冲都交给 Pipecat。
这个类只做三件自己的事：

- 把 16 kHz PCM 送给 Silero，判断用户有没有开口
- 把同一路 PCM 送给识别服务
- 对话引擎要出声时，推一帧 OutputAudioRawFrame；要打断时，推一帧 InterruptionFrame

输入的原始音频不再往下传。传到输出端的话，用户会听到自己的回声。
"""

from __future__ import annotations

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from zhiyu.config import Persona, Settings
from zhiyu.pipeline.engine import AudioSink, ConversationEngine
from zhiyu.pipeline.vad_bridge import VadTurnBridge
from zhiyu.session import CallSession


class _WebRtcSink(AudioSink):
    def __init__(self, processor: FrameProcessor, sample_rate: int) -> None:
        self._processor = processor
        self._sample_rate = sample_rate

    async def play(self, pcm: bytes) -> None:
        if not pcm:
            return
        # 16 位采样必须是偶数字节，否则后面的重采样会把最后一个字节错位。
        if len(pcm) % 2:
            pcm = pcm[:-1]
        if not pcm:
            return
        await self._processor.push_frame(
            OutputAudioRawFrame(
                audio=pcm,
                sample_rate=self._sample_rate,
                num_channels=1,
            )
        )

    async def clear(self) -> None:
        # 输出端收到这一帧后，会丢掉还排在缓冲里的音频。
        await self._processor.push_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)


class VoiceSessionProcessor(FrameProcessor):
    def __init__(
        self,
        *,
        settings: Settings,
        persona: Persona,
        session: CallSession,
        recognizer,
        language_model,
        tts_factory,
    ) -> None:
        super().__init__(name="zhiyu-voice")
        self._settings = settings
        self._opening = persona.opening
        self._session = session
        self._recognizer = recognizer
        self._vad = SileroVADAnalyzer(
            sample_rate=16000,
            params=VADParams(
                confidence=settings.vad_confidence,
                start_secs=settings.vad_start_secs,
                stop_secs=settings.vad_stop_secs,
                min_volume=settings.vad_min_volume,
            ),
        )
        self._vad.set_sample_rate(16000)
        self._engine = ConversationEngine(
            system_prompt=persona.system_prompt,
            language_model=language_model,
            tts_factory=tts_factory,
            sink=_WebRtcSink(self, settings.tts_sample_rate),
            listener=self._on_event,
            finalize_timeout=settings.asr_finalize_timeout,
        )
        self._bridge = VadTurnBridge(self._engine.user_started, self._engine.user_stopped)
        self._recognizer.set_transcript_handler(self._on_transcript)
        self._recognizer.set_error_handler(self._on_asr_error)
        self._pipeline_ready = False
        self._client_connected = False
        self._greeted = False
        self._asr_started = False
        self._closed = False

    async def _on_event(self, event: dict) -> None:
        self._session.add(event)

    async def _on_transcript(self, transcript) -> None:
        await self._engine.on_transcript(transcript.text, transcript.is_final)

    async def _on_asr_error(self, message: str) -> None:
        self._session.add({"type": "error", "message": message})

    async def setup(self, setup) -> None:
        await super().setup(setup)
        if setup.audio_in_sample_rate != 16000:
            logger.warning(
                "输入采样率是 {}，Silero 和 Paraformer 按 16000 配置。",
                setup.audio_in_sample_rate,
            )
        self._vad.set_sample_rate(16000)

    async def process_frame(self, frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            # 先把开始信号传下去，输出端才知道采样率。然后再去连识别服务。
            await self.push_frame(frame, direction)
            await self._on_pipeline_started()
            return

        if isinstance(frame, InputAudioRawFrame):
            await self._on_audio(frame)
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            await self.shutdown()
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

    async def on_client_connected(self) -> None:
        self._client_connected = True
        self._session.add({"type": "status", "value": "connected"})
        await self._maybe_greet()

    async def _on_pipeline_started(self) -> None:
        self._pipeline_ready = True
        if not self._asr_started:
            self._asr_started = True
            try:
                await self._recognizer.start()
            except Exception as exc:
                await self._on_asr_error(f"语音识别没有启动：{exc}")
        await self._maybe_greet()

    async def _maybe_greet(self) -> None:
        if self._greeted or not self._client_connected or not self._pipeline_ready:
            return
        self._greeted = True
        logger.info("播放开场白")
        await self._engine.speak_fixed(self._opening)

    async def _on_audio(self, frame: InputAudioRawFrame) -> None:
        try:
            state = await self._vad.analyze_audio(frame.audio)
        except Exception:
            logger.exception("VAD 处理失败")
            state = None
        try:
            await self._recognizer.send_audio(frame.audio)
        except Exception:
            logger.exception("送入识别音频失败")
        if state is not None:
            await self._bridge.update(state.name)

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._engine.close()
        try:
            await self._recognizer.stop()
        except Exception:
            logger.exception("关闭识别连接失败")
        try:
            await self._vad.cleanup()
        except Exception:
            logger.exception("关闭 VAD 失败")
