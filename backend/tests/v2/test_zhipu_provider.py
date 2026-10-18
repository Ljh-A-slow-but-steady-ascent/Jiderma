from __future__ import annotations

import pytest

from backend.app.chat.mock import DISCLAIMER
from backend.app.chat.zhipu import ZhipuChatProvider


class FakeResponse:
    status_code = 200
    headers = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "请按本地分级结果进行后续评估。"}}]}


def test_zhipu_provider_uses_chat_completions_without_image(monkeypatch):
    captured = {}
    monkeypatch.setenv("ZHIPUAI_MAX_TOKENS", "1400")

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("backend.app.chat.zhipu.requests.post", fake_post)
    provider = ZhipuChatProvider(api_key="test-key", model="glm-test")
    answer = provider.generate(
        "下一步应该怎么办？",
        "patient",
        {"get_care_pathway": {"level": "REFERRAL"}},
        detail_level="detailed",
    )

    serialized = str(captured["json"])
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "glm-test"
    assert captured["json"]["temperature"] == 0.25
    assert captured["json"]["max_tokens"] == 1400
    assert "详细程度应与用户问题匹配" in serialized
    assert "不要无条件套用病例报告" in serialized
    assert "image_bytes" not in serialized
    assert "local_image_path" not in serialized
    assert DISCLAIMER in answer


def test_zhipu_provider_rejects_empty_content(monkeypatch):
    class EmptyResponse(FakeResponse):
        def json(self) -> dict:
            return {
                "choices": [
                    {"message": {"content": ""}, "finish_reason": "length"}
                ]
            }

    monkeypatch.delenv("ZHIPUAI_MAX_TOKENS", raising=False)
    monkeypatch.setattr(
        "backend.app.chat.zhipu.requests.post", lambda *args, **kwargs: EmptyResponse()
    )
    provider = ZhipuChatProvider(api_key="test-key", model="glm-test")
    with pytest.raises(RuntimeError, match="空正文"):
        provider.generate("详细解释", "patient", {}, detail_level="detailed")
