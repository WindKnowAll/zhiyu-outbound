"""把资审状态机接到现有对话引擎的两个扩展点，并在合成前挡住跑偏的句子。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from zhiyu.extensions import TurnRecord
from zhiyu.qualification.flow import (
    QualificationCall,
    TicketStore,
    guard_customer_speech,
    intent_system_prompt,
    new_call,
    peek_intent,
    resolve_turn,
    review_sentence,
)

Emit = Callable[[dict], None]


class QualificationHooks:
    def __init__(self, call: QualificationCall | None = None, store: TicketStore | None = None, emit: Emit | None = None) -> None:
        self.call = call or new_call()
        self.store = store or TicketStore(Path("var") / "mock_tickets")
        self.emit = emit
        self._blocked = False
        self.buffers_model_output = True
        self.last_source = ""
        self._spoken_early = False

    def opening(self) -> str:
        return self.call.opening()

    def note_greeted(self) -> None:
        self.call.greeted = True

    async def prepare_messages(self, history: list[dict[str, str]], user_text: str) -> list[dict[str, str]]:
        self._blocked = False
        self._spoken_early = False
        self._user_text = user_text
        prompt = intent_system_prompt(self.call)
        prior = [item for item in history if item.get("role") != "system"]
        return [{"role": "system", "content": prompt}, *prior, {"role": "user", "content": user_text}]

    def partial_reply(self, user_text: str, model_raw: str) -> str | None:
        """意图字段一出现就可以开口。不必等 JSON 里的 reply 写完。"""

        if self._spoken_early or peek_intent(model_raw) is None:
            return None
        decision, source = resolve_turn(
            self.call,
            user_text,
            json.dumps({"intent": peek_intent(model_raw), "reply": ""}, ensure_ascii=False),
        )
        self._spoken_early = True
        self.last_source = source
        self._blocked = False
        return decision.speak

    def finalize_reply(self, user_text: str, model_raw: str) -> str:
        try:
            decision, source = resolve_turn(self.call, user_text, model_raw)
        except Exception:
            decision, source = resolve_turn(self.call, user_text, "")
        self.last_source = source
        self._blocked = False
        if self._spoken_early:
            return ""
        return decision.speak

    def review_speech(self, _user_text: str, sentence: str) -> str:
        decision = self.call.pending
        if decision is None:
            return sentence
        spoken, blocked = review_sentence(
            decision,
            sentence,
            identity_confirmed=self.call.identity_confirmed,
            blocked=self._blocked,
        )
        guarded = guard_customer_speech(spoken)
        if guarded != spoken:
            blocked = True
        self._blocked = blocked
        return guarded

    async def after_turn(self, record: TurnRecord) -> None:
        self.call.commit(record.interrupted)
        if self.call.stage == "closed":
            self._write(record.interrupted)

    def on_hangup(self) -> None:
        if self.call.ticket_written or not self.call.greeted:
            return
        if not self.call.result:
            self.call.result = "未完成"
            self.call.stage = "closed"
        self._write(False)

    def _write(self, interrupted: bool) -> None:
        if self.call.ticket_written:
            return
        ticket = self.store.write(self.call.to_ticket(interrupted=interrupted))
        if ticket.get("write_error"):
            if self.emit is not None:
                self.emit({"type": "mock_ticket", "ticket": ticket})
            return
        self.call.ticket_written = True
        if self.emit is not None:
            self.emit({"type": "mock_ticket", "ticket": ticket})
