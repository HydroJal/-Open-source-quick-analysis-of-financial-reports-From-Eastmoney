"""金融财报快捷分析 —— Flask 后端入口。

流程：用户输入公司名称 → 搜索解析证券代码 → 爬取/读取本地财报 →
计算财务指标 → 调用所选 LLM 进行分析 → 返回指标 + 分析报告给网页客户端。
"""
import json
import os

from flask import Flask, jsonify, request, send_file, send_from_directory

import dependencies
import excel_export
import history_store
import settings_store
from analysis import recommend as recommend_engine
from analysis.indicators import build_data_payload, compute_indicators
from data.fetcher import fetch_financial_data, search_company
from data.storage import is_cache_fresh, load_company_data, merge_data, save_company_data
from llm.factory import create_llm_client, list_providers, resolve_api_key

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


config = load_config()

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "web"), static_url_path="")


def load_prompt():
    """读取默认提示词（config.prompt_file，缺省 prompt.txt）。"""
    path = os.path.join(BASE_DIR, config.get("prompt_file", "prompt.txt"))
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def mask_key(key):
    """脱敏展示 API Key。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return key[:4] + "***" + key[-4:]


def api_key_status(provider):
    """判断某 provider 的 API Key 来自哪里：secret/env/config/none。"""
    name = provider.get("name")
    secret_entry = settings_store.get_provider_entry(name)
    if secret_entry.get("api_key"):
        return "secret", secret_entry["api_key"]
    raw = provider.get("api_key", "")
    if isinstance(raw, str) and raw.startswith("env:"):
        val = resolve_api_key(raw)
        return ("env", val) if val else ("none", "")
    return ("config", raw) if raw else ("none", "")


# ── 页面 ──────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/requirements.txt")
def download_requirements():
    """下载 requirements.txt 文件。"""
    return send_from_directory(BASE_DIR, "requirements.txt", as_attachment=True)


# ── 服务商列表 ───────────────────────────────────────
@app.route("/api/providers")
def providers():
    return jsonify({
        "default_provider": config.get("llm", {}).get("default_provider", ""),
        "providers": list_providers(config, settings_store.load_secrets()),
    })


# ── 设置（API Key 等）─────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def get_settings():
    secrets = settings_store.load_secrets()
    out = []
    for p in config.get("llm", {}).get("providers", []):
        src, key = api_key_status(p)
        entry = secrets.get(p.get("name")) or {}
        out.append({
            "name": p.get("name"),
            "display_name": p.get("display_name", p.get("name")),
            "type": p.get("type"),
            "base_url": entry.get("base_url") or p.get("base_url", ""),
            "model": entry.get("model") or p.get("model", ""),
            "models": p.get("models", [p.get("model")]),
            "api_key_configured": bool(key),
            "api_key_source": src,
            "api_key_masked": mask_key(key),
        })
    return jsonify({
        "default_provider": config.get("llm", {}).get("default_provider", ""),
        "providers": out,
        "dependencies": dependencies.check_dependencies(),
    })


@app.route("/api/settings", methods=["POST"])
def save_settings():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("provider") or "").strip()
    if not name:
        return jsonify({"error": "缺少 provider 参数"}), 400

    # 校验 provider 存在
    providers = config.get("llm", {}).get("providers", [])
    if not any(p.get("name") == name for p in providers):
        return jsonify({"error": "未知的服务商：" + name}), 404

    api_key = body.get("api_key")
    entry = settings_store.set_provider_entry(
        name,
        api_key=api_key if api_key is not None else None,
        base_url=body.get("base_url") or None,
        model=body.get("model") or None,
    )
    return jsonify({"ok": True, "provider": name,
                    "api_key_configured": bool(entry.get("api_key"))})


@app.route("/api/settings/<name>", methods=["DELETE"])
def delete_setting(name):
    settings_store.delete_provider_api_key(name)
    return jsonify({"ok": True, "provider": name})


# ── 数据获取设置 ──────────────────────────────────────
@app.route("/api/fetch-settings", methods=["GET"])
def get_fetch_config():
    return jsonify(settings_store.get_fetch_settings(config))


def _coerce_fetch_settings(body):
    """把前端传来的字段做类型转换，仅保留合法字段。"""
    out = {}
    if "mode" in body:
        mode = str(body["mode"])
        out["mode"] = mode if mode in ("auto", "api_only") else "auto"
    for key in ("spoofing", "incremental"):
        if key in body:
            out[key] = bool(body[key])
    for key in ("min_interval_seconds", "max_retries", "timeout_seconds",
                "cache_ttl_hours", "max_years"):
        if key in body:
            try:
                out[key] = int(body[key])
            except (TypeError, ValueError):
                pass
    # 边界约束
    if "min_interval_seconds" in out:
        out["min_interval_seconds"] = max(0, min(60, out["min_interval_seconds"]))
    if "max_retries" in out:
        out["max_retries"] = max(0, min(10, out["max_retries"]))
    if "timeout_seconds" in out:
        out["timeout_seconds"] = max(5, min(120, out["timeout_seconds"]))
    if "cache_ttl_hours" in out:
        out["cache_ttl_hours"] = max(0, out["cache_ttl_hours"])
    if "max_years" in out:
        out["max_years"] = max(1, min(20, out["max_years"]))
    return out


@app.route("/api/fetch-settings", methods=["POST"])
def save_fetch_config():
    body = request.get_json(force=True, silent=True) or {}
    settings_store.set_fetch_settings(_coerce_fetch_settings(body))
    return jsonify({"ok": True, "fetch": settings_store.get_fetch_settings(config)})


# ── 推荐设置（门槛/权重/排序/候选数）──────────────────
def _coerce_recommend_settings(body):
    """把前端传来的推荐设置做类型转换，仅保留合法字段。"""
    out = {}
    if "max_candidates" in body:
        try:
            out["max_candidates"] = max(0, min(100, int(body["max_candidates"])))
        except (TypeError, ValueError):
            pass
    if "sort_by" in body:
        val = str(body["sort_by"])
        allowed = ("score", "roe", "net_margin", "gross_margin", "revenue_yoy", "debt_ratio")
        out["sort_by"] = val if val in allowed else "score"

    def _num_map(raw):
        result = {}
        if not isinstance(raw, dict):
            return result
        for k, v in raw.items():
            try:
                result[k] = float(v)
            except (TypeError, ValueError):
                pass
        return result

    if "thresholds" in body:
        th = _num_map(body["thresholds"])
        if th:
            out["thresholds"] = th
    if "score_weights" in body:
        w = _num_map(body["score_weights"])
        if w:
            out["score_weights"] = w
    return out


@app.route("/api/recommend-settings", methods=["GET"])
def get_recommend_settings():
    return jsonify(recommend_engine.get_recommend_settings(config))


@app.route("/api/recommend-settings", methods=["POST"])
def save_recommend_settings():
    body = request.get_json(force=True, silent=True) or {}
    settings_store.set_recommend_settings(_coerce_recommend_settings(body))
    return jsonify({"ok": True, "recommend": recommend_engine.get_recommend_settings(config)})


# ── 优质公司推荐 ──────────────────────────────────────
@app.route("/api/recommend", methods=["POST"])
def recommend():
    try:
        fs = settings_store.get_fetch_settings(config)
        rows, stats = recommend_engine.fetch_recommendations(config, fs)
        return jsonify({"results": rows, "stats": stats})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "获取推荐失败：" + str(e)}), 500


# ── 历史记录 ──────────────────────────────────────────
@app.route("/api/history", methods=["GET"])
def history_list():
    return jsonify({"entries": history_store.load_history()})


@app.route("/api/history/<record_id>", methods=["DELETE"])
def history_delete(record_id):
    ok = history_store.delete_history(record_id)
    return jsonify({"ok": ok})


@app.route("/api/history", methods=["DELETE"])
def history_clear():
    history_store.clear_history()
    return jsonify({"ok": True})


# ── 依赖 ──────────────────────────────────────────────
@app.route("/api/dependencies")
def get_dependencies():
    return jsonify({"packages": dependencies.check_dependencies()})


@app.route("/api/install", methods=["POST"])
def install_dependencies():
    body = request.get_json(force=True, silent=True) or {}
    packages = body.get("packages") or None
    code, out, err = dependencies.install_packages(packages)
    ok = code == 0
    return jsonify({
        "ok": ok,
        "returncode": code,
        "output": (out or "") + ("\n" + err if err else ""),
    })


# ── 搜索 ──────────────────────────────────────────────
@app.route("/api/search", methods=["POST"])
def search():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("company") or "").strip()
    if not name:
        return jsonify({"error": "请输入公司名称"}), 400
    try:
        results = search_company(name, config, fetch_settings=settings_store.get_fetch_settings(config))
        return jsonify({"results": results})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "搜索失败：" + str(e)}), 500


# ── 公共：解析代码 + 抓取/读缓存 + 计算指标 ────────────
def _prepare_data(company, code, name, refresh):
    """解析证券代码，抓取/读取数据，计算指标。返回 (code, name, data, indicators, from_cache)。"""
    if not code:
        results = search_company(company, config)
        if not results:
            raise ValueError("未找到与「" + company + "」匹配的 A 股上市公司")
        top = results[0]
        code = top["security_code"]
        name = top["name"]

    fs = settings_store.get_fetch_settings(config)
    cached = load_company_data(code, config) if not refresh else None
    from_cache = False
    if cached and is_cache_fresh(cached, fs.get("cache_ttl_hours")):
        data = cached
        from_cache = True
    else:
        data = fetch_financial_data(code, name, config, fs)
        if cached and fs.get("incremental", True):
            data = merge_data(cached, data)
        save_company_data(code, data, config)

    indicators = compute_indicators(data)
    return code, name, data, indicators, from_cache


# ── 导出 Excel（仅抓取数据，不调用 AI）────────────────
@app.route("/api/export-excel", methods=["POST"])
def export_excel():
    body = request.get_json(force=True, silent=True) or {}
    company = (body.get("company") or "").strip()
    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    refresh = bool(body.get("refresh", False))

    if not company and not code:
        return jsonify({"error": "请提供公司名称或证券代码"}), 400

    try:
        code, name, data, indicators, _ = _prepare_data(company, code, name, refresh)
        buf = excel_export.build_excel(data, indicators)
        filename = code + "_" + (name or "财报") + "_财报数据.xlsx"
        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "导出失败：" + str(e)}), 500


# ── 原始财报数据（确认公司后展示，不调用 AI）─────────
@app.route("/api/raw-data", methods=["POST"])
def raw_data():
    body = request.get_json(force=True, silent=True) or {}
    company = (body.get("company") or "").strip()
    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    refresh = bool(body.get("refresh", False))

    if not company and not code:
        return jsonify({"error": "请提供公司名称或证券代码"}), 400

    try:
        code, name, data, indicators, from_cache = _prepare_data(company, code, name, refresh)
        return jsonify({
            "code": code,
            "name": data.get("name") or name,
            "fetched_at": data.get("fetched_at"),
            "source": data.get("source", "api"),
            "from_cache": from_cache,
            "company_info": data.get("company_info") or {},
            "statements": excel_export.format_statements(data),
            "indicators": indicators,
        })
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "加载财报数据失败：" + str(e)}), 500


# ── 分析 ──────────────────────────────────────────────
@app.route("/api/analyze", methods=["POST"])
def analyze():
    body = request.get_json(force=True, silent=True) or {}
    company = (body.get("company") or "").strip()
    code = (body.get("code") or "").strip()          # 如 SH600519
    name = (body.get("name") or "").strip()
    provider = body.get("provider") or config.get("llm", {}).get("default_provider")
    model = body.get("model") or ""
    refresh = bool(body.get("refresh", False))

    if not company and not code:
        return jsonify({"error": "请提供公司名称或证券代码"}), 400

    try:
        code, name, data, indicators, from_cache = _prepare_data(company, code, name, refresh)

        # LLM 分析
        prompt = load_prompt()
        payload_text = build_data_payload(data, indicators)
        client = create_llm_client(config, provider, model, settings_store.load_secrets())
        analysis = client.complete(payload_text, system=prompt, temperature=0.3)

        result = {
            "code": code,
            "name": data.get("name") or name,
            "fetched_at": data.get("fetched_at"),
            "source": data.get("source", "api"),
            "from_cache": from_cache,
            "company_info": data.get("company_info") or {},
            "provider": provider,
            "model": client.model,
            "indicators": indicators,
            "analysis": analysis,
        }

        # 自动保存到历史记录
        try:
            history_store.add_history(result)
        except Exception:  # noqa: BLE001
            pass

        return jsonify(result)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "分析失败：" + str(e)}), 500


if __name__ == "__main__":
    print("=" * 56)
    print("  金融财报快捷分析 已启动")
    print("  请在浏览器打开：http://127.0.0.1:5000")
    print("=" * 56)
    app.run(host="127.0.0.1", port=5000, debug=False)
