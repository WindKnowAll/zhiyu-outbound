"""把大模型的增量文本切成可以马上朗读的句子。

CosyVoice 遇到没写完的句子会先攒着，不出声音。
所以这里一看到句号、问号、感叹号就切一刀，第一句可以先去合成。
逗号只有在已经攒了一定字数时才切，避免把「嗯，」单独念出来。
"""

from __future__ import annotations

_STRONG = set("。！？!?；;\n")
_SOFT = set("，,、：:")


class SentenceSplitter:
    def __init__(self, *, soft_min: int = 12, hard_max: int = 40) -> None:
        self._buf = ""
        self._soft_min = soft_min
        self._hard_max = hard_max

    def push(self, token: str) -> list[str]:
        if not token:
            return []
        self._buf += token
        return self._drain(final=False)

    def flush(self) -> list[str]:
        return self._drain(final=True)

    def _drain(self, *, final: bool) -> list[str]:
        pieces: list[str] = []
        while self._buf:
            cut = self._cut(final=final)
            if cut is None:
                break
            piece = self._buf[:cut].strip()
            self._buf = self._buf[cut:].lstrip()
            if piece:
                pieces.append(piece)
        return pieces

    def _cut(self, *, final: bool) -> int | None:
        for index, char in enumerate(self._buf):
            if char in _STRONG:
                return index + 1
            if char in _SOFT and index + 1 >= self._soft_min:
                return index + 1
        if final and self._buf.strip():
            return len(self._buf)
        if len(self._buf) >= self._hard_max:
            return self._hard_max
        return None
