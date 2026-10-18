from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from backend.app.chat.mock import DISCLAIMER
from backend.app.chat.prompts import SYSTEM_PROMPT, presentation_prompt


class GroqChatProvider:
    """仅接收已通过 PrivFlow 的结构化文本；不接收原始图片。"""

    name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError("已选择 Groq，但未设置 GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.base_url = base_url or os.getenv(
            "GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions"
        )

    def plan(self, payload: dict[str, Any], system_prompt: str) -> str:
        body: dict[str, Any] = {
            "model": self.model, "stream": False, "temperature": 0.05, "max_tokens": 700,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
            ],
        }
        if self.model.startswith("openai/gpt-oss-"):
            body["reasoning_effort"] = "low"
        response = requests.post(
            self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        try:
            return str(response.json()["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Groq 规划响应无法解析") from exc

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
        default_max_tokens = 1400 if detail_level == "detailed" else 700
        max_tokens = max(256, int(os.getenv("GROQ_MAX_TOKENS", str(default_max_tokens))))
        request_body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "temperature": 0.25,
            "max_tokens": max_tokens,
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
        if self.model.startswith("openai/gpt-oss-"):
            request_body["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "low")
        elif self.model == "qwen/qwen3.8-27b":
            request_body["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "none")

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
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                break
            try:
                delay = float(response.headers.get("Retry-After", attempt + 1))
            except (TypeError, ValueError):
                delay = attempt + 1
            time.sleep(min(max(delay, 0.2), 3.0))
        response.raise_for_status()
        body = response.json()
        try:
            raw_content = body["choices"][0]["message"].get("content")
            text = "" if raw_content is None else str(raw_content).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Groq 返回了无法解析的响应") from exc
        if not text:
            finish_reason = body.get("choices", [{}])[0].get("finish_reason", "unknown")
            raise RuntimeError(f"Groq 返回空正文（finish_reason={finish_reason}）")
        if DISCLAIMER not in text:
            text = f"{text}\n\n{DISCLAIMER}"
        return text
