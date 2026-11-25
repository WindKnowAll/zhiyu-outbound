import pytest

from zhiyu.pipeline.vad_bridge import VadTurnBridge


@pytest.mark.asyncio
async def test_only_confirmed_speech_starts_and_quiet_stops():
    calls: list[str] = []

    async def start() -> None:
        calls.append("start")

    async def stop() -> None:
        calls.append("stop")

    bridge = VadTurnBridge(start, stop)
    await bridge.update("STARTING")
    assert calls == []
    await bridge.update("SPEAKING")
    await bridge.update("SPEAKING")
    await bridge.update("STOPPING")
    assert calls == ["start"]
    await bridge.update("QUIET")
    assert calls == ["start", "stop"]
    assert bridge.speaking is False


@pytest.mark.asyncio
async def test_stopping_then_speaking_again_is_still_one_turn():
    calls: list[str] = []

    async def start() -> None:
        calls.append("start")

    async def stop() -> None:
        calls.append("stop")

    bridge = VadTurnBridge(start, stop)
    await bridge.update("speaking")
    await bridge.update("stopping")
    await bridge.update("speaking")
    await bridge.update("quiet")
    assert calls == ["start", "stop"]
