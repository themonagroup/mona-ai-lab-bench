"""Wrapper tối giản cho OpenAI Chat Completions và Anthropic Messages."""

from __future__ import annotations

import os
import time
from typing import Any


class ProviderError(RuntimeError):
    """Lỗi gọi model sau khi đã thử lại."""


class ModelClient:
    """Gọi model qua một trong hai SDK chính thức."""

    def __init__(self, provider: str, timeout: float = 60.0, retries: int = 3):
        self.provider = provider
        self.retries = retries

        if provider == "openai":
            from openai import OpenAI

            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise ProviderError("Thiếu biến môi trường OPENAI_API_KEY")
            self.client = OpenAI(api_key=key, timeout=timeout, max_retries=0)
        elif provider == "anthropic":
            from anthropic import Anthropic

            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise ProviderError("Thiếu biến môi trường ANTHROPIC_API_KEY")
            self.client = Anthropic(api_key=key, timeout=timeout, max_retries=0)
        else:
            raise ValueError(f"Provider không hỗ trợ: {provider}")

    def generate(
        self,
        model: str,
        messages: list[dict[str, str]],
        system: str = "",
        json_mode: bool = False,
    ) -> str:
        """Sinh một câu trả lời, có retry ngắn khi API lỗi."""
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                if self.provider == "openai":
                    return self._openai(model, messages, system, json_mode)
                return self._anthropic(model, messages, system)
            except Exception as exc:  # SDK có nhiều lớp lỗi theo phiên bản
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)

        raise ProviderError(
            f"{self.provider} thất bại sau {self.retries} lần: {last_error}"
        ) from last_error

    def _openai(
        self,
        model: str,
        messages: list[dict[str, str]],
        system: str,
        json_mode: bool,
    ) -> str:
        chat_messages = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs: dict[str, Any] = {"model": model, "messages": chat_messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content
        if not text:
            raise ProviderError("OpenAI trả về nội dung rỗng")
        return text.strip()

    def _anthropic(
        self, model: str, messages: list[dict[str, str]], system: str
    ) -> str:
        response = self.client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=messages,
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        if not text:
            raise ProviderError("Anthropic trả về nội dung rỗng")
        return text.strip()
