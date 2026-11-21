"""把资审状态机接到现有对话引擎的两个扩展点，并在合成前挡住跑偏的句子。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from zhiyu.extensions import TurnRecord
from zhiyu.qualification.flow import (
    QualificationCall,
    TicketStore,
    new_call,
    public_system_prompt,
    review_sentence,
)

Emit = Callable[[dict], None]


class QualificationHooks:
    def __init__(self, call: QualificationCall | None = None, store: TicketStore | None = None, emit: Emit | None = None) -> None:
        self.call = call or new_call()
        self.store = store or TicketStore(Path("var") / "mock_tickets")
        self.emit = emit
        self._blocked = False

    def opening(self) -> str:
        return self.call.opening()

    def note_greeted(self) -> None:
        self.call.greeted = True

    async def prepare_messages(self, history: list[dict[str, str]], user_text: str) -> list[dict[str, str]]:
        decision = self.call.plan(user_text)
        self._blocked = False
        prompt = public_system_prompt() + f"\n【本轮只许说】{decision.speak}【说完为止】"
        prior = [item for item in history if item.get("role") != "system"]
        return [{"role": "system", "content": prompt}, *prior, {"role": "user", "content": user_text}]

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
        self._blocked = blocked
        return spoken

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
