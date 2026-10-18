from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.chat.gemini import GeminiChatProvider
from backend.app.chat.mock import DISCLAIMER, chat_model_catalog
from backend.app.chat.schemas import ChatRequest


def test_chat_request_accepts_only_model_whitelist() -> None:
    request = ChatRequest(case_id="case-1", message="你好", model="glm-5.3-flash")
    assert request.model == "glm-5.3-flash"
    assert request.detail_level == "concise"
    assert ChatRequest(case_id="case-1", message="详细解释", detail_level="detailed")
    for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"):
        assert ChatRequest(case_id="case-1", message="你好", model=model).model == model
    with pytest.raises(ValidationError):
        ChatRequest(case_id="case-1", message="你好", model="https://evil.example")
    with pytest.raises(ValidationError):
        ChatRequest(case_id="case-1", message="你好", detail_level="unbounded")


def test_model_catalog_reports_key_availability(monkeypatch) -> None:
    monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    catalog = {item["id"]: item for item in chat_model_catalog()}
    assert catalog["glm-5.3-flash"]["available"] is True
    assert catalog["gemini-flash"]["available"] is False
    assert catalog["openai/gpt-oss-120b"]["available"] is False
    assert catalog["openai/gpt-oss-20b"]["available"] is False
    assert catalog["qwen/qwen3.8-27b"]["available"] is False


class FakeGeminiResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"candidates": [{"content": {"parts": [{"text": "请继续线下评估。"}]}}]}


def test_gemini_provider_uses_text_only_sanitized_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeGeminiResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeGeminiResponse()

    monkeypatch.setattr("backend.app.chat.gemini.requests.post", fake_post)
    provider = GeminiChatProvider(api_key="test-key", model="gemini-test")
    answer = provider.generate(
        "下一步怎么办？",
        "patient",
        {"get_triage_result": {"level": "REFERRAL"}},
        history=[{"role": "user", "message": "之前的问题"}],
    )

    serialized = str(captured["json"])
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["url"].endswith("/gemini-test:generateContent")
    assert "之前的问题" in serialized
    assert "image_bytes" not in serialized
    assert DISCLAIMER in answer
