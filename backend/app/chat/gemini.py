from __future__ import annotations

import json
import os
from typing import Any

import requests

from backend.app.chat.mock import DISCLAIMER
from backend.app.chat.prompts import SYSTEM_PROMPT, presentation_prompt


class GeminiChatProvider:
    """Gemini 文本提供方；只接收 PrivFlow 放行后的结构化文本。"""

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("已选择 Gemini Flash，但未设置 GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.base_url = base_url or os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models"
        )

    def plan(self, payload: dict[str, Any], system_prompt: str) -> str:
        response = requests.post(
            f"{self.base_url.rstrip('/')}/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
                "generationConfig": {
                    "temperature": 0.05, "maxOutputTokens": 700,
                    "responseMimeType": "application/json",
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        try:
            return "".join(
                str(part.get("text", ""))
                for part in response.json()["candidates"][0]["content"]["parts"]
            ).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini 规划响应无法解析") from exc

    def generate(
        self,
        message: str,
        mode: str,
        tool_results: dict[str, dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        detail_level: str = "concise",
    ) -> str:
        presentation = presentation_prompt(mode, detail_level)
        contents = [
            {
                "role": "model" if item.get("role") == "assistant" else "user",
                "parts": [{"text": str(item.get("message", ""))[:4000]}],
            }
            for item in (history or [])[-12:]
            if item.get("role") in {"user", "assistant"} and item.get("message")
        ]
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"{presentation}\n用户问题：{message}\n"
                            "已通过隐私检查的本地工具结果："
                            + json.dumps(tool_results, ensure_ascii=False, separators=(",", ":"))
                        )
                    }
                ],
            }
        )
        response = requests.post(
            f"{self.base_url.rstrip('/')}/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.25,
                    "maxOutputTokens": 1400 if detail_level == "detailed" else 700,
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        try:
            parts = body["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text", "")) for part in parts).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini 返回了无法解析的响应") from exc
        if not text:
            raise RuntimeError("Gemini 没有返回文本内容")
        if DISCLAIMER not in text:
            text = f"{text}\n\n{DISCLAIMER}"
        return text
