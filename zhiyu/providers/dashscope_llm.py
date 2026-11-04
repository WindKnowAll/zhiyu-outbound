"""通义千问，走 DashScope 的 OpenAI 兼容接口。

选这条接口是因为它和教材里的 chat.completions 流式写法一样，
同学答辩时可以直接对着官方「兼容 OpenAI」文档讲。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from zhiyu.providers.base import ProviderError


class DashScopeChatModel:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._model = model
        # 超时设短一些：语音通话里，10 秒还没首 token 就已经不适合继续等。
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=20.0)

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
                temperature=0.6,
                # 客服回复要求一两句。限制长度也是为了首包之后尽快结束。
                max_tokens=200,
            )
        except Exception as exc:
            raise ProviderError(f"大模型请求失败：{exc}") from exc

        try:
            async for chunk in response:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = choices[0].delta
                text = getattr(delta, "content", None) or ""
                if text:
                    yield text
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"大模型流式输出中断：{exc}") from exc
