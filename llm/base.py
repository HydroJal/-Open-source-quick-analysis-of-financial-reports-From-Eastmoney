"""统一 LLM 客户端抽象接口。

所有 AI 服务商（OpenAI、DeepSeek、通义千问、Kimi、智谱、Claude、Ollama ...）
都通过 BaseLLMClient 统一接口访问，业务代码只依赖抽象、不依赖具体实现，
从而做到「配置化驱动」——新增服务商只需在 config.json 增加一项配置即可。
"""
from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    """LLM 客户端的统一抽象基类。"""

    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "")
        self.model = config.get("model", "")

    @abstractmethod
    def chat(self, messages, temperature=0.3, max_tokens=None, **kwargs) -> str:
        """发送一组消息并返回助手的文本回复。

        messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]
        """
        raise NotImplementedError

    def complete(self, prompt: str, system: str = None, **kwargs) -> str:
        """便捷方法：给定 system 与 user 文本，返回回复。"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs)
