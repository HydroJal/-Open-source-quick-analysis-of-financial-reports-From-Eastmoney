"""分析结果历史记录的本地持久化。

每次成功分析后，把（公司、指标、AI 分析报告、模型）保存到 history.json，
供网页客户端的「历史记录」面板查看、回看与删除。
"""
import json
import os
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")
_MAX_ENTRIES = 200


def load_history():
    """读取历史记录列表（按时间倒序）。不存在/损坏时返回空列表。"""
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data["entries"]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def add_history(entry):
    """追加一条历史记录，返回记录 id。自动裁剪到 _MAX_ENTRIES 条。"""
    entries = load_history()
    record = dict(entry or {})
    record["id"] = uuid.uuid4().hex[:12]
    record.setdefault("saved_at", _now())
    entries.insert(0, record)
    _save(entries[:_MAX_ENTRIES])
    return record["id"]


def delete_history(record_id):
    """删除指定 id 的记录，返回是否成功。"""
    entries = load_history()
    keep = [e for e in entries if e.get("id") != record_id]
    changed = len(keep) != len(entries)
    if changed:
        _save(keep)
    return changed


def clear_history():
    """清空全部历史记录。"""
    _save([])


def _now():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
