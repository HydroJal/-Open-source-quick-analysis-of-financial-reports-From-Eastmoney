"""本地数据持久化：把抓取到的财报数据保存为 JSON 文件。"""
import datetime
import json
import os


def _storage_dir(config=None):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    name = (config or {}).get("storage_dir", "data_store") or "data_store"
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


def _path_for(code, config=None):
    return os.path.join(_storage_dir(config), code + ".json")


def save_company_data(code, data, config=None):
    """把公司财报数据保存到本地 JSON 文件。"""
    with open(_path_for(code, config), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_company_data(code, config=None):
    """读取本地缓存的财报数据，不存在返回 None。"""
    path = _path_for(code, config)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def is_cache_fresh(data, ttl_hours):
    """根据 fetched_at 判断缓存是否在有效期内。

    ttl_hours <= 0 或为空表示永不过期（仅手动/强制刷新才重新抓取）。
    """
    if ttl_hours is None or ttl_hours <= 0:
        return True
    fetched_at = (data or {}).get("fetched_at")
    if not fetched_at:
        return False
    try:
        dt = datetime.datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    age = datetime.datetime.now() - dt
    return age.total_seconds() < ttl_hours * 3600


def merge_data(old, new):
    """增量合并两次抓取结果：按 REPORT_DATE 去重，保留旧数据的更早报告期。"""
    if not old:
        return new
    for key in ("income", "balance", "cashflow", "indicators"):
        seen = {}
        for row in (old.get(key) or []):
            d = str(row.get("REPORT_DATE", ""))
            if d:
                seen[d] = row
        for row in (new.get(key) or []):
            d = str(row.get("REPORT_DATE", ""))
            if d and d not in seen:
                seen[d] = row
        new[key] = [seen[d] for d in sorted(seen, reverse=True)]
    return new
