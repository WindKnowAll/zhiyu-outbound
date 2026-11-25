"""文字调试。只调用大模型和资审状态机，不创建识别或合成。"""

from __future__ import annotations

import uuid

from zhiyu.extensions import TurnRecord
from zhiyu.pipeline.timing import StageTimings
from zhiyu.qualification.catalog import Catalog
from zhiyu.qualification.flow import (
    TicketStore,
    case_for_row,
    new_call,
    pick_scenario,
    resolve_scenario_id,
)
from zhiyu.qualification.hooks import QualificationHooks


class TextDebugSession:
    def __init__(self, catalog: Catalog, row: int, store: TicketStore, learning: object | None = None) -> None:
        self.session_id = "text-" + uuid.uuid4().hex
        self.catalog = catalog
        self.row = resolve_scenario_id(row, catalog)
        call = new_call(case_for_row(self.row), catalog)
        call.session_id = self.session_id
        call.learning = learning
        self.hooks = QualificationHooks(call=call, store=store)
        self.history: list[dict[str, str]] = []
        self.model = None

    def opening(self) -> str:
        text = self.hooks.opening()
        self.hooks.note_greeted()
        self.history.append({"role": "assistant", "content": text})
        return text

    async def say(self, user_text: str) -> dict:
        messages = await self.hooks.prepare_messages(list(self.history), user_text)
        chunks: list[str] = []
        async for piece in self.model.stream(messages):
            if piece:
                chunks.append(str(piece))
        spoken = self.hooks.finalize_reply(user_text, "".join(chunks))
        await self.hooks.after_turn(
            TurnRecord(user_text, spoken, False, StageTimings(), messages)
        )
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": spoken})
        trace = dict(self.hooks.last_trace or {})
        return {
            "speak": spoken,
            "source": self.hooks.last_source,
            "provider_status": trace.get("provider_status") or "",
            "stage": self.hooks.call.stage,
            "ticket_written": self.hooks.call.ticket_written,
        }

    def finish(self) -> dict:
        self.hooks.on_hangup()
        return {
            "call_session_id": self.session_id,
            "ticket_written": self.hooks.call.ticket_written,
            "result": self.hooks.call.result,
            "row": self.row,
        }


def choose_row(catalog: Catalog, scenario_id: object, random_pick: bool) -> int:
    rows = [item.row for item in catalog.scenarios]
    if random_pick:
        return pick_scenario(rows, int(uuid.uuid4().int % len(rows)))
    return resolve_scenario_id(scenario_id, catalog)
