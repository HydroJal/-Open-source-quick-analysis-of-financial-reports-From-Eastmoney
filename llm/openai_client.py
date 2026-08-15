"""OpenAI 兼容客户端。

兼容所有提供 OpenAI 风格 /chat/completions 接口的服务商：
OpenAI、DeepSeek、通义千问（百炼兼容模式）、Kimi、智谱、Ollama 等。
"""
import requests

from .base import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    def chat(self, messages, temperature=0.3, max_tokens=None, **kwargs) -> str:
        base_url = self.config.get("base_url", "").rstrip("/")
        url = base_url + "/chat/completions"

        headers = {"Content-Type": "application/json"}
        api_key = self.config.get("api_key", "")
        if api_key:
            headers["Authorization"] = "Bearer " + api_key

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        timeout = self.config.get("timeout", 120)
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
