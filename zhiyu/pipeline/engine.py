"""一通电话的对话引擎。

它不做网络，也不碰 WebRTC。外面把三件事送进来：

1. 用户开始说话 / 说完了（来自 Silero VAD）
2. 转写文本（来自识别服务，部分结果或定稿）
3. 三个供应商：大模型、语音合成，以及一个能清空的播放器

打断用一个整数代号 `_generation`。每次用户插话，代号加一，
正在跑的那一轮发现代号变了就立刻丢掉后续的文字和音频。
同时取消那个 asyncio 任务，让还堵在网络读写上的协程退出。
播放器的 clear() 负责把已经送进声卡缓冲、但还没播的声音清掉。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

from loguru import logger

from zhiyu.extensions import AgentHooks, DefaultHooks, TurnRecord
from zhiyu.pipeline.sentences import SentenceSplitter
from zhiyu.pipeline.timing import StageTimings
from zhiyu.providers.base import ProviderError, StreamingSynthesizer


Listener = Callable[[dict], Awaitable[None]]


class AudioSink:
    """播放 PCM，并在打断时丢掉还没播的缓冲。"""

    async def play(self, pcm: bytes) -> None:
        raise NotImplementedError

    async def clear(self) -> None:
        raise NotImplementedError


class ConversationEngine:
    def __init__(
        self,
        *,
        system_prompt: str,
        language_model,
        tts_factory: Callable[[], StreamingSynthesizer],
        sink: AudioSink,
        hooks: AgentHooks | None = None,
        listener: Listener | None = None,
        finalize_timeout: float = 0.35,
    ) -> None:
        self._system_prompt = system_prompt.strip()
        self._llm = language_model
        self._tts_factory = tts_factory
        self._sink = sink
        self._hooks = hooks or DefaultHooks()
        self._listener = listener
        self._finalize_timeout = finalize_timeout

        self._history: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt}
        ]
        self._parts: list[str] = []
        self._partial = ""
        self._user_speaking = False
        self._speech_end_at: float | None = None
        self._endpoint_token = 0
        self._generation = 0
        self._task: asyncio.Task | None = None
        self._finalize_task: asyncio.Task | None = None
        self._history_lock = asyncio.Lock()

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    @property
    def user_speaking(self) -> bool:
        return self._user_speaking

    async def user_started(self) -> None:
        """VAD 确认用户开口。客服正在说就打断；否则只是把尚未提交的句子留住。"""

        self._user_speaking = True
        bot_active = self._task is not None and not self._task.done()
        if bot_active:
            # 新的一句话，丢掉上一句还没提交的转写，避免串到一起。
            self._parts.clear()
            self._partial = ""
            self._speech_end_at = None
            await self.interrupt()
            return
        # 用户只是停顿后又继续。取消「马上交给大模型」的计时，转写先留着。
        self._endpoint_token += 1
        await self._emit({"type": "status", "value": "listening"})

    async def user_stopped(self) -> None:
        """VAD 确认用户说完。稍等识别定稿，再开始生成回复。"""

        self._user_speaking = False
        self._speech_end_at = time.perf_counter()
        self._endpoint_token += 1
        token = self._endpoint_token

        async def wait_and_commit() -> None:
            try:
                await asyncio.sleep(self._finalize_timeout)
            except asyncio.CancelledError:
                return
            await self._commit(token)

        task = asyncio.create_task(wait_and_commit(), name="asr-finalize")
        self._finalize_task = task

    async def on_transcript(self, text: str, is_final: bool) -> None:
        """识别回调。定稿是整句替换，不是增量，所以只在句末追加一次。"""

        cleaned = text.strip()
        if not cleaned:
            return
        if is_final:
            if not self._parts or self._parts[-1] != cleaned:
                self._parts.append(cleaned)
            self._partial = ""
            if not self._user_speaking and self._speech_end_at is not None:
                await self._commit(self._endpoint_token)
            return
        self._partial = cleaned

    async def speak_fixed(self, text: str) -> None:
        """不经过大模型，直接把一句固定话合成出来。开场白用这个。"""

        cleaned = text.strip()
        if not cleaned:
            return
        if self._task is not None and not self._task.done():
            await self.interrupt()
        self._generation += 1
        generation = self._generation
        self._task = asyncio.create_task(
            self._run_fixed(generation, cleaned),
            name="speak-fixed",
        )

    async def interrupt(self) -> None:
        """用户插话：代号加一，清播放缓冲，取消正在写和正在读的任务。"""

        self._generation += 1
        self._endpoint_token += 1
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        # 先清播放缓冲，用户立刻听不到旧声音。再等被取消的任务把历史写完，
        # 否则下一轮可能在上一轮收尾之前就开始，上下文会串。
        await self._sink.clear()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await self._emit({"type": "barge_in"})
        logger.info("用户插话，已取消当前回复并清空播放缓冲")

    async def settle(self) -> None:
        """测试用：等收尾计时和它拉起来的生成任务都结束。"""

        for _ in range(10):
            pending = [
                task
                for task in (self._finalize_task, self._task)
                if task is not None and not task.done()
            ]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    async def close(self) -> None:
        self._endpoint_token += 1
        if self._finalize_task is not None and not self._finalize_task.done():
            self._finalize_task.cancel()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _commit(self, token: int) -> None:
        if token != self._endpoint_token or self._user_speaking:
            return
        text = ("".join(self._parts) + self._partial).strip()
        self._parts.clear()
        self._partial = ""
        # 让另一个还在睡的计时器发现代号变了，不再提交第二次。
        self._endpoint_token += 1
        speech_end_at = self._speech_end_at
        self._speech_end_at = None
        if not text:
            await self._emit({"type": "status", "value": "listening"})
            return
        asr_final_at = time.perf_counter()
        timings = StageTimings()
        if speech_end_at is not None:
            timings.asr_final_ms = (asr_final_at - speech_end_at) * 1000
        await self._emit({"type": "user", "text": text})
        await self._start_reply(
            generation_bump=True,
            user_text=text,
            timings=timings,
            asr_final_at=asr_final_at,
            speech_end_at=speech_end_at,
        )

    async def _start_reply(
        self,
        *,
        generation_bump: bool,
        user_text: str,
        timings: StageTimings,
        asr_final_at: float,
        speech_end_at: float | None,
    ) -> None:
        if generation_bump:
            self._generation += 1
        generation = self._generation
        previous = self._task
        self._task = asyncio.create_task(
            self._run_reply(
                generation,
                user_text,
                timings,
                asr_final_at,
                speech_end_at,
            ),
            name="reply",
        )
        if previous is not None and previous is not self._task and not previous.done():
            previous.cancel()

    async def _run_fixed(self, generation: int, text: str) -> None:
        started = time.perf_counter()
        timings = StageTimings()
        assistant = ""
        interrupted = False
        tts = self._tts_factory()
        try:
            await self._emit({"type": "status", "value": "thinking"})
            await tts.start()
            await tts.push_text(text)
            await tts.finish()
            assistant = text
            await self._emit({"type": "assistant", "text": text, "final": False})
            interrupted = await self._play(
                generation, tts, timings, started, None, None
            )
        except asyncio.CancelledError:
            interrupted = True
        except Exception as exc:
            logger.exception("开场白合成失败")
            await self._emit({"type": "error", "message": _public_error(exc)})
        finally:
            await self._shutdown_tts(tts)
            await self._finish_fixed(generation, assistant, timings, interrupted)

    async def _run_reply(
        self,
        generation: int,
        user_text: str,
        timings: StageTimings,
        asr_final_at: float,
        speech_end_at: float | None,
    ) -> None:
        messages: list[dict[str, str]] = []
        assistant_parts: list[str] = []
        interrupted = False
        # 列表只有一个格子，生产协程写入，播放协程读取。
        # 不能在调用 _play 时把时间戳当参数传进去，那时第一个字还没到。
        llm_first_at: list[float | None] = [None]
        tts = self._tts_factory()
        try:
            messages = await self._hooks.prepare_messages(list(self._history), user_text)
            await self._emit({"type": "status", "value": "thinking"})
            await tts.start()
            if generation != self._generation:
                interrupted = True
                return

            splitter = SentenceSplitter()

            async def produce() -> None:
                async for token in self._llm.stream(messages):
                    if generation != self._generation:
                        return
                    if llm_first_at[0] is None:
                        llm_first_at[0] = time.perf_counter()
                        timings.llm_first_token_ms = (llm_first_at[0] - asr_final_at) * 1000
                    assistant_parts.append(token)
                    for sentence in splitter.push(token):
                        await self._emit(
                            {"type": "assistant", "text": sentence, "final": False}
                        )
                        await tts.push_text(sentence)
                if generation != self._generation:
                    return
                # 缓冲区里的字已经在 assistant_parts 里，这里只负责送去合成。
                for sentence in splitter.flush():
                    await self._emit({"type": "assistant", "text": sentence, "final": False})
                    await tts.push_text(sentence)
                await tts.finish()

            producer = asyncio.create_task(produce(), name="llm-to-tts")
            try:
                interrupted = await self._play(
                    generation,
                    tts,
                    timings,
                    asr_final_at,
                    llm_first_at,
                    speech_end_at,
                )
            finally:
                if not producer.done():
                    producer.cancel()
                outcomes = await asyncio.gather(producer, return_exceptions=True)
                failure = outcomes[0]
                if isinstance(failure, Exception) and not isinstance(
                    failure, asyncio.CancelledError
                ):
                    raise failure
                if generation != self._generation:
                    interrupted = True
        except asyncio.CancelledError:
            interrupted = True
        except Exception as exc:
            logger.exception("生成回复失败")
            await self._emit({"type": "error", "message": _public_error(exc)})
            interrupted = generation != self._generation
        finally:
            await self._shutdown_tts(tts)
            await self._finish_reply(
                generation,
                user_text,
                "".join(assistant_parts).strip(),
                messages,
                timings,
                interrupted or generation != self._generation,
                llm_first_at[0],
                asr_final_at,
            )

    async def _play(
        self,
        generation: int,
        tts: StreamingSynthesizer,
        timings: StageTimings,
        started_at: float,
        llm_first_at: list[float | None] | None,
        speech_end_at: float | None,
    ) -> bool:
        """把合成音频送去播放。返回值表示播完之前代号有没有变。"""

        heard_audio = False
        async for chunk in tts.audio_chunks():
            if generation != self._generation:
                return True
            if not chunk:
                continue
            if not heard_audio:
                heard_audio = True
                now = time.perf_counter()
                first_token = None if llm_first_at is None else llm_first_at[0]
                origin = first_token if first_token is not None else started_at
                timings.tts_first_audio_ms = (now - origin) * 1000
                end_to_end_from = speech_end_at if speech_end_at is not None else started_at
                timings.first_audio_e2e_ms = (now - end_to_end_from) * 1000
                await self._emit({"type": "status", "value": "speaking"})
            # 再查一次：clear() 可能发生在我们准备播放的这一瞬间。
            if generation != self._generation:
                return True
            await self._sink.play(chunk)
        return generation != self._generation

    async def _finish_fixed(
        self,
        generation: int,
        assistant: str,
        timings: StageTimings,
        interrupted: bool,
    ) -> None:
        async with self._history_lock:
            self._remember_assistant(assistant, interrupted)
        await self._emit({"type": "assistant", "text": assistant, "final": True, "interrupted": interrupted})
        await self._report(timings, interrupted, user_text="", assistant_text=assistant)
        if not interrupted:
            await self._emit({"type": "status", "value": "listening"})

    async def _finish_reply(
        self,
        generation: int,
        user_text: str,
        assistant: str,
        messages: list[dict[str, str]],
        timings: StageTimings,
        interrupted: bool,
        llm_first_at: float | None,
        asr_final_at: float,
    ) -> None:
        # 首 token 时间可能在播放协程之外才写完，这里补一次。
        if timings.llm_first_token_ms is None and llm_first_at is not None:
            timings.llm_first_token_ms = (llm_first_at - asr_final_at) * 1000
        async with self._history_lock:
            if user_text:
                self._history.append({"role": "user", "content": user_text})
            self._remember_assistant(assistant, interrupted)
        await self._emit(
            {"type": "assistant", "text": assistant, "final": True, "interrupted": interrupted}
        )
        record = TurnRecord(
            user_text=user_text,
            assistant_text=assistant,
            interrupted=interrupted,
            timings=timings,
            messages=messages,
        )
        try:
            await self._hooks.after_turn(record)
        except Exception:
            logger.exception("after_turn 扩展点失败，本轮通话继续")
        await self._report(
            timings,
            interrupted,
            user_text=user_text,
            assistant_text=assistant,
        )
        if generation == self._generation:
            await self._emit({"type": "status", "value": "listening"})

    async def _report(
        self,
        timings: StageTimings,
        interrupted: bool,
        *,
        user_text: str,
        assistant_text: str,
    ) -> None:
        logger.info(
            "耗时 {} | 打断={} | 用户={} | 客服={}",
            timings.as_log(),
            interrupted,
            _short(user_text),
            _short(assistant_text),
        )
        await self._emit(
            {
                "type": "latency",
                "timings": timings.to_dict(),
                "interrupted": interrupted,
            }
        )

    def _remember_assistant(self, text: str, interrupted: bool) -> None:
        """写进历史，让下一轮知道刚才说了什么。被打断时标明可能没听完。"""

        cleaned = text.strip()
        if not cleaned:
            return
        if interrupted:
            cleaned = f"{cleaned}（用户中途打断，可能没听完）"
        self._history.append({"role": "assistant", "content": cleaned})

    async def _shutdown_tts(self, tts: StreamingSynthesizer) -> None:
        with contextlib.suppress(Exception):
            await tts.cancel()

    async def _emit(self, event: dict) -> None:
        if self._listener is None:
            return
        try:
            await self._listener(dict(event))
        except Exception:
            logger.exception("向外发送通话事件失败")


def _short(text: str, limit: int = 40) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact or "-"
    return compact[: limit - 1] + "…"


def _public_error(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return str(exc)
    return f"生成回复时出错：{exc}"
