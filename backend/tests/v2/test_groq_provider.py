from __future__ import annotations

from backend.app.chat.groq import GroqChatProvider
from backend.app.chat.mock import DISCLAIMER


class FakeResponse:
    status_code = 200
    headers = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "请按本地分级结果进行后续评估。"}}]}


def test_groq_provider_sends_only_supplied_sanitized_context(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("backend.app.chat.groq.requests.post", fake_post)
    provider = GroqChatProvider(api_key="test-key", model="test-model")
    answer = provider.generate(
        "为什么建议转诊？",
        "patient",
        {"get_triage_result": {"level": "REFERRAL"}},
    )

    serialized = str(captured["json"])
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "test-model"
    assert "REFERRAL" in serialized
    assert "image_bytes" not in serialized
    assert "local_image_path" not in serialized
    assert DISCLAIMER in answer


def test_groq_current_models_include_supported_reasoning(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("backend.app.chat.groq.requests.post", fake_post)
    provider = GroqChatProvider(api_key="test-key", model="openai/gpt-oss-120b")
    provider.generate("请详细解释", "patient", {}, detail_level="detailed")
    assert captured["json"]["reasoning_effort"] == "low"
    assert captured["json"]["max_tokens"] == 1400


def test_groq_retries_rate_limit(monkeypatch):
    calls = []

    class LimitedResponse(FakeResponse):
        status_code = 429
        headers = {"Retry-After": "0"}

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return LimitedResponse() if len(calls) == 1 else FakeResponse()

    monkeypatch.setattr("backend.app.chat.groq.requests.post", fake_post)
    monkeypatch.setattr("backend.app.chat.groq.time.sleep", lambda _: None)
    answer = GroqChatProvider(api_key="test-key").generate("请解释", "patient", {})
    assert len(calls) == 2
    assert DISCLAIMER in answer
