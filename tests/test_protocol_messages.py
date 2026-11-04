import pytest

from zhiyu.providers.base import ProviderError
from zhiyu.providers.messages import (
    asr_run_task,
    authorization_header,
    event_name,
    finish_task,
    parse_asr_message,
    tts_continue_task,
    tts_run_task,
)


def test_authorization_uses_lowercase_bearer():
    assert authorization_header("sk-demo") == {"Authorization": "bearer sk-demo"}


def test_asr_run_task_matches_paraformer_shape():
    message = asr_run_task(task_id="abc", model="paraformer-realtime-v2", sample_rate=16000)
    assert message["header"]["action"] == "run-task"
    assert message["header"]["streaming"] == "duplex"
    assert message["payload"]["task"] == "asr"
    assert message["payload"]["model"] == "paraformer-realtime-v2"
    assert message["payload"]["parameters"]["format"] == "pcm"
    assert message["payload"]["parameters"]["sample_rate"] == 16000
    assert message["payload"]["parameters"]["language_hints"] == ["zh"]


def test_tts_messages_share_task_id():
    run = tts_run_task(
        task_id="task-1",
        model="cosyvoice-v2",
        voice="longxiaochun_v2",
        sample_rate=24000,
    )
    follow = tts_continue_task(task_id="task-1", text="您好。")
    done = finish_task(task_id="task-1")
    assert run["payload"]["function"] == "SpeechSynthesizer"
    assert run["payload"]["parameters"]["voice"] == "longxiaochun_v2"
    assert run["payload"]["parameters"]["sample_rate"] == 24000
    assert follow["header"]["task_id"] == done["header"]["task_id"] == "task-1"
    assert follow["payload"]["input"]["text"] == "您好。"


def test_parse_partial_and_final_transcript():
    partial = parse_asr_message(
        {
            "header": {"event": "result-generated"},
            "payload": {"output": {"sentence": {"text": "你好", "sentence_end": False}}},
        }
    )
    final = parse_asr_message(
        {
            "header": {"event": "result-generated"},
            "payload": {"output": {"sentence": {"text": "你好。", "sentence_end": True}}},
        }
    )
    assert partial is not None and partial.text == "你好" and partial.is_final is False
    assert final is not None and final.is_final is True


def test_parse_ignores_heartbeat_and_empty_text():
    assert (
        parse_asr_message(
            {
                "header": {"event": "result-generated"},
                "payload": {"output": {"sentence": {"text": "", "heartbeat": True}}},
            }
        )
        is None
    )
    assert event_name({"header": {"event": "task-started"}}) == "task-started"
    assert parse_asr_message({"header": {"event": "task-started"}}) is None


def test_task_failed_raises_without_including_unrelated_fields():
    with pytest.raises(ProviderError, match="识别失败"):
        parse_asr_message(
            {"header": {"event": "task-failed", "error_message": "识别失败：配额不足"}}
        )
