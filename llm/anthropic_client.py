"""Anthropic Claude 客户端。"""
import requests

from .base import BaseLLMClient


class AnthropicClient(BaseLLMClient):
    def chat(self, messages, temperature=0.3, max_tokens=None, **kwargs) -> str:
        base_url = self.config.get("base_url", "").rstrip("/")
        url = base_url + "/v1/messages"

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.get("api_key", ""),
            "anthropic-version": "2023-06-01",
        }

        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        system = "\n\n".join(system_parts) if system_parts else None
        chat_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") != "system"
        ]

        payload = {
            "model": self.model,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            payload["system"] = system

        timeout = self.config.get("timeout", 120)
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]
