"""供应商接口。

对话引擎只依赖这三个接口。换成本地模型或别的云时，新写一个实现，
再改 factory.py 里的选择即可，引擎和网页都不用动。
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol


class ProviderError(RuntimeError):
    """供应商拒绝了请求，或连接中途失败。message 给页面看，不要带上密钥。"""


class Transcript:
    """识别结果。is_final 为真时，text 是一整句，不是相对上一次的增量。"""

    def __init__(self, text: str, is_final: bool) -> None:
        self.text = text
        self.is_final = is_final


class StreamingRecognizer(Protocol):
    """持续接收 16 kHz 单声道 PCM，回调部分结果和定稿。"""

    def set_transcript_handler(self, handler) -> None:
        """handler 的签名是 async (Transcript) -> None。"""

    def set_error_handler(self, handler) -> None:
        """handler 的签名是 async (str) -> None。"""

    async def start(self) -> None:
        """连上识别服务。失败时抛 ProviderError。"""

    async def send_audio(self, pcm: bytes) -> None:
        """送一帧 PCM。连接还没好时先排队，不要阻塞音频线程。"""

    async def stop(self) -> None:
        """通知服务端音频结束，并关掉连接。可以重复调用。"""


class LanguageModel(Protocol):
    """流式聊天。只产出文本增量，v1 不处理函数调用。"""

    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """逐段产出新增文本。调用方取消外层任务时，迭代要能停下来。"""


class StreamingSynthesizer(Protocol):
    """一次回复一条 WebSocket：先 start，再按句 push_text，最后 finish。

    audio_chunks 和 push_text 同时进行，这样第一句合成时，大模型还在写后面的句子。
    """

    @property
    def sample_rate(self) -> int:
        """产出的 PCM 采样率，要和播放端配置一致。"""

    async def start(self) -> None:
        """建连并等到服务端允许发送文本。"""

    async def push_text(self, text: str) -> None:
        """送一句已经断好的文本。"""

    async def finish(self) -> None:
        """告诉服务端没有更多文本，让它把缓冲区里的半句也读出来。"""

    def audio_chunks(self) -> AsyncIterator[bytes]:
        """产出 PCM 字节。结束时正常返回，不要无限等待。"""

    async def cancel(self) -> None:
        """用户打断时立刻关掉连接。可以重复调用。"""
