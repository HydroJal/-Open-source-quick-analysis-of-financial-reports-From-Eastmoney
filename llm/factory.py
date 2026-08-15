"""根据配置创建 LLM 客户端实例（工厂）。"""
import os

from .base import BaseLLMClient
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient

# 客户端类型注册表：config 中的 type 字段 -> 实现类
CLIENT_TYPES = {
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
}


def resolve_api_key(raw_key: str) -> str:
    """解析 api_key，支持两种写法：
    - 明文 key：直接返回
    - "env:环境变量名"：从系统环境变量读取
    """
    if isinstance(raw_key, str) and raw_key.startswith("env:"):
        return os.environ.get(raw_key[4:], "")
    return raw_key or ""


def create_llm_client(config: dict, provider_name: str, model: str = None,
                      secrets: dict = None) -> BaseLLMClient:
    """按 name 从 config['llm']['providers'] 中查找并实例化客户端。

    secrets：来自 settings_store.load_secrets() 的覆盖配置，
    优先级高于 config.json（用户可在网页里临时配置 API Key）。
    """
    providers = config.get("llm", {}).get("providers", [])
    provider = next((p for p in providers if p.get("name") == provider_name), None)
    if provider is None:
        raise ValueError("未找到 LLM 服务商配置：" + str(provider_name))

    client_type = provider.get("type", "openai")
    cls = CLIENT_TYPES.get(client_type)
    if cls is None:
        raise ValueError("不支持的 LLM 客户端类型：" + str(client_type))

    secrets = secrets or {}
    secret_entry = secrets.get(provider_name) or {}

    cfg = dict(provider)
    cfg["api_key"] = secret_entry.get("api_key") or resolve_api_key(provider.get("api_key", ""))
    cfg["timeout"] = config.get("request_timeout", 120)

    if secret_entry.get("base_url"):
        cfg["base_url"] = secret_entry["base_url"]
    if model:
        cfg["model"] = model
    elif secret_entry.get("model"):
        cfg["model"] = secret_entry["model"]

    return cls(cfg)


def list_providers(config: dict, secrets: dict = None) -> list:
    """返回前端下拉框所需的服务商列表（不暴露 api_key 明文）。"""
    providers = config.get("llm", {}).get("providers", [])
    default = config.get("llm", {}).get("default_provider", "")
    secrets = secrets or {}
    return [
        {
            "name": p.get("name"),
            "display_name": p.get("display_name", p.get("name")),
            "model": p.get("model"),
            "models": p.get("models", [p.get("model")]),
            "has_key": bool(
                (secrets.get(p.get("name")) or {}).get("api_key")
                or resolve_api_key(p.get("api_key", ""))
            ),
            "is_default": p.get("name") == default,
        }
        for p in providers
    ]
