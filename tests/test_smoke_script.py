from scripts.smoke_test import redact, resample_pcm16


def test_redact_hides_the_real_key_and_other_sk_tokens():
    secret = "sk-ws-this-is-not-a-real-key"
    text = f"401 from server, Authorization bearer {secret}"
    cleaned = redact(text, secret)
    assert secret not in cleaned
    assert "sk-***" in cleaned


def test_resample_24k_to_16k_keeps_roughly_two_thirds():
    pcm = b"\x00\x10" * 240
    out = resample_pcm16(pcm, 24000, 16000)
    assert len(out) % 2 == 0
    assert abs(len(out) // 2 - 160) <= 1
    assert resample_pcm16(pcm, 16000, 16000) == pcm
