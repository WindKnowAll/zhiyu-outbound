from zhiyu.config import load_persona, load_settings, status_payload


def test_missing_key_is_reported_without_crashing():
    settings = load_settings({})
    assert settings.missing_keys == ["DASHSCOPE_API_KEY"]
    payload = status_payload(settings)
    assert payload["ok"] is False
    assert "DASHSCOPE_API_KEY" in payload["message"]
    assert "DASHSCOPE_API_KEY" in payload["missing"]


def test_blank_key_counts_as_missing():
    settings = load_settings({"DASHSCOPE_API_KEY": "   "})
    assert settings.credentials_ready is False


def test_present_key_is_not_echoed():
    settings = load_settings({"DASHSCOPE_API_KEY": "sk-test-secret"})
    payload = status_payload(settings)
    assert payload["ok"] is True
    assert "sk-test-secret" not in payload["message"]
    assert payload["missing"] == []


def test_defaults_point_at_beijing_dashscope():
    settings = load_settings({"DASHSCOPE_API_KEY": "sk-test"})
    assert "dashscope.aliyuncs.com" in settings.dashscope_base_url
    assert settings.dashscope_ws_url.startswith("wss://")
    assert settings.llm_model == "qwen-plus"
    assert settings.asr_model == "paraformer-realtime-v2"
    assert settings.tts_sample_rate == 24000


def test_persona_files_load():
    persona = load_persona()
    assert "小语" in persona.system_prompt
    assert "验证码" in persona.system_prompt
    assert "图书馆" in persona.opening
