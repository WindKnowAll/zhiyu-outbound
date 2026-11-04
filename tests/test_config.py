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


def test_defaults_point_at_legacy_domain_when_host_is_missing():
    settings = load_settings({"DASHSCOPE_API_KEY": "sk-test"})
    assert settings.dashscope_endpoint_source == "legacy"
    assert settings.dashscope_host == "dashscope.aliyuncs.com"
    assert settings.dashscope_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.dashscope_ws_url == "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    assert "维护" in status_payload(settings)["message"]
    assert settings.llm_model == "qwen-plus"
    assert settings.asr_model == "paraformer-realtime-v2"
    assert settings.tts_sample_rate == 24000


def test_host_derives_both_urls():
    settings = load_settings(
        {
            "DASHSCOPE_API_KEY": "sk-test",
            "DASHSCOPE_HOST": "https://ws-xxxxxxxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        }
    )
    assert settings.dashscope_endpoint_source == "host"
    assert settings.dashscope_host == "ws-xxxxxxxx.cn-beijing.maas.aliyuncs.com"
    assert (
        settings.dashscope_base_url
        == "https://ws-xxxxxxxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        settings.dashscope_ws_url
        == "wss://ws-xxxxxxxx.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    )


def test_workspace_id_builds_beijing_host_without_doubling_prefix():
    from_id = load_settings({"DASHSCOPE_WORKSPACE_ID": "abc123"})
    from_prefixed = load_settings({"DASHSCOPE_WORKSPACE_ID": "ws-abc123"})
    assert from_id.dashscope_host == "ws-abc123.cn-beijing.maas.aliyuncs.com"
    assert from_prefixed.dashscope_host == from_id.dashscope_host
    assert from_id.dashscope_ws_url.endswith("/api-ws/v1/inference")
    host_wins = load_settings(
        {
            "DASHSCOPE_HOST": "ws-from-host.cn-beijing.maas.aliyuncs.com",
            "DASHSCOPE_WORKSPACE_ID": "ignored",
        }
    )
    assert host_wins.dashscope_host == "ws-from-host.cn-beijing.maas.aliyuncs.com"


def test_explicit_urls_override_the_host():
    settings = load_settings(
        {
            "DASHSCOPE_HOST": "ws-xxxxxxxx.cn-beijing.maas.aliyuncs.com",
            "DASHSCOPE_BASE_URL": "https://example.invalid/compatible-mode/v1",
            "DASHSCOPE_WS_URL": "",
        }
    )
    assert settings.dashscope_endpoint_source == "override"
    assert settings.dashscope_base_url == "https://example.invalid/compatible-mode/v1"
    assert (
        settings.dashscope_ws_url
        == "wss://ws-xxxxxxxx.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    )


def test_persona_files_load():
    persona = load_persona()
    assert "小语" in persona.system_prompt
    assert "验证码" in persona.system_prompt
    assert "图书馆" in persona.opening
