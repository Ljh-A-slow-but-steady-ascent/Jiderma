from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from backend.app.chat.mock import DISCLAIMER
from backend.app.chat.prompts import SYSTEM_PROMPT, presentation_prompt


class ZhipuChatProvider:
    """智谱 GLM 对话提供方；只接收通过 PrivFlow 的结构化文本。"""

    name = "zhipu_glm"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ZHIPUAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("已选择智谱 GLM，但未设置 ZHIPUAI_API_KEY")
        self.model = model or os.getenv("ZHIPUAI_MODEL", "glm-4.7-flash")
        self.base_url = base_url or os.getenv(
            "ZHIPUAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        )

    def plan(self, payload: dict[str, Any], system_prompt: str) -> str:
        response = requests.post(
            self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model, "stream": False, "temperature": 0.05,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        try:
            return str(response.json()["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("智谱规划响应无法解析") from exc

    def generate(
        self,
        message: str,
        mode: str,
        tool_results: dict[str, dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        detail_level: str = "concise",
    ) -> str:
        presentation = presentation_prompt(mode, detail_level)
        context = json.dumps(tool_results, ensure_ascii=False, separators=(",", ":"))
        history_messages = [
            {
                "role": "assistant" if item.get("role") == "assistant" else "user",
                "content": str(item.get("message", ""))[:4000],
            }
            for item in (history or [])[-12:]
            if item.get("role") in {"user", "assistant"} and item.get("message")
        ]
        request_body = {
            "model": self.model,
            "stream": False,
            "temperature": 0.25,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *history_messages,
                {
                    "role": "user",
                    "content": (
                        f"{presentation}\n用户问题：{message}\n"
                        f"已通过隐私检查的本地工具结果：{context}"
                    ),
                },
            ],
        }
        configured_max_tokens = os.getenv("ZHIPUAI_MAX_TOKENS", "").strip()
        if configured_max_tokens:
            request_body["max_tokens"] = max(256, int(configured_max_tokens))
        for attempt in range(3):
            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=60,
            )
            if response.status_code != 429 or attempt == 2:
                break
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else attempt + 1
            time.sleep(min(delay, 3))
        response.raise_for_status()
        body = response.json()
        try:
            raw_content = body["choices"][0]["message"].get("content")
            text = "" if raw_content is None else str(raw_content).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("智谱 GLM 返回了无法解析的响应") from exc
        if not text:
            finish_reason = body.get("choices", [{}])[0].get("finish_reason", "unknown")
            raise RuntimeError(f"智谱 GLM 返回空正文（finish_reason={finish_reason}）")
        if DISCLAIMER not in text:
            text = f"{text}\n\n{DISCLAIMER}"
        return text
