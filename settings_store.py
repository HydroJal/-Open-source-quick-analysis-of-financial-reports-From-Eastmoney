"""API Key 等敏感配置的本地持久化。

用户通过网页设置的 API Key 保存在本目录的 secrets.json 中，
运行时优先级高于 config.json 里的 env:xxx / 明文配置。
secrets.json 不会被提交到版本库（建议加入 .gitignore）。
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_PATH = os.path.join(BASE_DIR, "secrets.json")


def load_secrets():
    """读取 secrets.json，返回 dict（不存在或损坏时返回空 dict）。"""
    if not os.path.exists(SECRETS_PATH):
        return {}
    try:
        with open(SECRETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_secrets(secrets):
    """写入 secrets.json。"""
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump(secrets, f, ensure_ascii=False, indent=2)


def get_provider_entry(provider_name):
    """返回某个 provider 在 secrets 中的配置项（dict）。"""
    return load_secrets().get(provider_name) or {}


def set_provider_entry(provider_name, api_key=None, base_url=None, model=None):
    """保存/更新某个 provider 的 api_key（及可选 base_url/model）。"""
    secrets = load_secrets()
    entry = secrets.get(provider_name) or {}
    if api_key is not None:
        entry["api_key"] = api_key
    if base_url is not None:
        entry["base_url"] = base_url
    if model is not None:
        entry["model"] = model
    secrets[provider_name] = entry
    save_secrets(secrets)
    return entry


def delete_provider_api_key(provider_name):
    """删除某个 provider 已保存的 api_key。"""
    secrets = load_secrets()
    entry = secrets.get(provider_name) or {}
    entry.pop("api_key", None)
    if entry:
        secrets[provider_name] = entry
    else:
        secrets.pop(provider_name, None)
    save_secrets(secrets)


# ── 非敏感运行时设置（数据获取策略等，存 settings.json）──
RUNTIME_PATH = os.path.join(BASE_DIR, "settings.json")


def load_runtime_settings():
    """读取非敏感运行时设置，返回 dict（不存在/损坏时返回空）。"""
    if not os.path.exists(RUNTIME_PATH):
        return {}
    try:
        with open(RUNTIME_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_runtime_settings(settings):
    """写入非敏感运行时设置。"""
    with open(RUNTIME_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_fetch_settings(config):
    """返回合并后的数据获取设置：config.fetch 为默认，settings.json 覆盖。"""
    base = (config or {}).get("fetch", {}) or {}
    runtime = (load_runtime_settings() or {}).get("fetch", {}) or {}
    merged = dict(base)
    for k, v in runtime.items():
        if v is not None:
            merged[k] = v
    return merged


def set_fetch_settings(fetch_settings):
    """保存数据获取设置（仅覆盖提供的字段）。"""
    settings = load_runtime_settings()
    current = settings.get("fetch", {}) or {}
    for k, v in (fetch_settings or {}).items():
        if v is not None:
            current[k] = v
    settings["fetch"] = current
    save_runtime_settings(settings)
    return current


def set_recommend_settings(recommend_settings):
    """保存推荐设置（门槛/权重/排序/候选数），仅覆盖提供的字段。"""
    settings = load_runtime_settings()
    current = settings.get("recommend", {}) or {}
    for k, v in (recommend_settings or {}).items():
        if v is not None:
            current[k] = v
    settings["recommend"] = current
    save_runtime_settings(settings)
    return current
