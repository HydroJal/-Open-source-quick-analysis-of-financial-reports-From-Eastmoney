"""优质公司推荐引擎。

从候选池（config.recommend.candidates）出发，通过公开财报接口抓取每家公司的
关键财务数据（营收、净利、毛利率、净利率、ROE、营收增速、资产负债率），
按可配置的门槛过滤，再按可配置权重计算综合评分并排序，最后为每家入选公司
生成一句「优势说明」。

说明：
- 数据获取复用 data.fetcher 的东财 F10 接口，同样受域名白名单与限速约束；
- 每家候选仅抓取「利润表 + 资产负债表（各近 3 个年度）」，共 2 次请求，
  以控制访问量与耗时；
- 单家公司失败不中断整体流程，直接跳过并在结果中剔除。
"""
from data import fetcher

# 东财英文字段 -> 内部语义（与 analysis/indicators.py 保持一致）
_REVENUE = ("TOTAL_OPERATE_INCOME", "OPERATE_INCOME")
_OPERATE_COST = ("OPERATE_COST", "TOTAL_OPERATE_COST")
_NET_PROFIT = ("NETPROFIT",)
_PARENT_NET_PROFIT = ("PARENT_NETPROFIT",)
_TOTAL_ASSETS = ("TOTAL_ASSETS",)
_TOTAL_LIABILITIES = ("TOTAL_LIABILITIES",)
_TOTAL_EQUITY = ("TOTAL_EQUITY", "TOTAL_PARENT_EQUITY", "PARENT_EQUITY")


def _pick(row, *candidates):
    for c in candidates:
        if c in row:
            v = fetcher.to_float(row.get(c))
            if v is not None:
                return v
    return None


def _latest_annual(rows):
    """取 REPORT_DATE 以 12-31 结尾的最新一条年报记录。"""
    best = None
    for r in rows or []:
        rd = str(r.get("REPORT_DATE", "")).split(" ")[0]
        if rd.endswith("12-31"):
            if best is None or rd > str(best.get("REPORT_DATE", "")).split(" ")[0]:
                best = dict(r)
                best["REPORT_DATE"] = rd
    return best


def _second_annual(rows):
    """取倒数第二条年报记录（用于计算同比增速）。"""
    ordered = []
    for r in rows or []:
        rd = str(r.get("REPORT_DATE", "")).split(" ")[0]
        if rd.endswith("12-31"):
            row = dict(r)
            row["REPORT_DATE"] = rd
            ordered.append(row)
    ordered.sort(key=lambda r: r.get("REPORT_DATE", ""), reverse=True)
    return ordered[1] if len(ordered) > 1 else None


def _security_code(code):
    """6 位数字代码 -> 带市场前缀的证券代码（SH/SZ/BJ）。"""
    code = str(code).strip()
    if code.startswith(("6", "9")):
        return "SH" + code
    if code.startswith(("0", "3")):
        return "SZ" + code
    if code.startswith(("4", "8")):
        return "BJ" + code
    return code


def _clamp(v, lo, hi):
    if v is None:
        return None
    return max(lo, min(hi, v))


def _score_one(m, weights):
    """根据指标计算 0~100 的综合评分。"""
    w = weights or {}

    def sub(val, cap):
        return 0.0 if val is None else min(float(val), cap) / cap * 100.0

    roe = sub(m.get("roe"), 0.40)
    net_margin = sub(m.get("net_margin"), 0.30)
    gross_margin = sub(m.get("gross_margin"), 0.60)
    # 营收增速 [-20%, +50%] 映射到 [0, 100]
    yoy = m.get("revenue_yoy")
    yoy_score = 50.0 if yoy is None else (_clamp(yoy, -0.20, 0.50) + 0.20) / 0.70 * 100.0
    debt = m.get("debt_ratio")
    debt_safety = 50.0 if debt is None else (1.0 - _clamp(debt, 0.0, 1.0)) * 100.0

    score = (
        roe * float(w.get("roe", 0.35))
        + net_margin * float(w.get("net_margin", 0.20))
        + gross_margin * float(w.get("gross_margin", 0.15))
        + yoy_score * float(w.get("revenue_yoy", 0.20))
        + debt_safety * float(w.get("debt_safety", 0.10))
    )
    return round(score, 2)


def _advantage(m):
    """根据指标生成一句话优势说明。"""
    reasons = []
    roe = m.get("roe")
    if roe is not None and roe >= 0.15:
        reasons.append("ROE %.1f%%、盈利能力强" % (roe * 100))
    gm = m.get("gross_margin")
    if gm is not None and gm >= 0.40:
        reasons.append("毛利率 %.1f%%、具定价权" % (gm * 100))
    yoy = m.get("revenue_yoy")
    if yoy is not None and yoy >= 0.15:
        reasons.append("营收增速 %.1f%%、成长性佳" % (yoy * 100))
    nm = m.get("net_margin")
    if nm is not None and nm >= 0.15:
        reasons.append("净利率 %.1f%%、盈利质量高" % (nm * 100))
    debt = m.get("debt_ratio")
    if debt is not None and debt <= 0.40:
        reasons.append("资产负债率仅 %.1f%%、财务稳健" % (debt * 100))
    if not reasons:
        if roe is not None:
            reasons.append("ROE %.1f%%" % (roe * 100))
        if yoy is not None:
            reasons.append("营收增速 %.1f%%" % (yoy * 100))
    return "；".join(reasons) if reasons else "财务数据暂不充分"


def _fetch_one(candidate, config, fs):
    """抓取单家候选公司的最新关键指标，返回 dict；失败返回 None。"""
    code = str(candidate.get("code", ""))
    name = candidate.get("name", "")
    security_code = candidate.get("security_code") or _security_code(code)
    if not code:
        return None

    # 近 3 个年度的报告期末日期（含当前年度，接口会自动忽略尚未披露的年份）
    dates = fetcher._annual_dates(3)  # noqa: SLF001
    income = fetcher._f10("lrbAjaxNew", security_code, dates, config, fs)  # noqa: SLF001
    balance = fetcher._f10("zcfzbAjaxNew", security_code, dates, config, fs)  # noqa: SLF001

    cur = _latest_annual(income)
    if not cur:
        return None
    prev = _second_annual(income)
    bal = _latest_annual(balance) or {}

    revenue = _pick(cur, *_REVENUE)
    operate_cost = _pick(cur, *_OPERATE_COST)
    net_profit = _pick(cur, *_NET_PROFIT)
    parent_net = _pick(cur, *_PARENT_NET_PROFIT)

    total_assets = _pick(bal, *_TOTAL_ASSETS)
    total_liab = _pick(bal, *_TOTAL_LIABILITIES)
    total_equity = _pick(bal, *_TOTAL_EQUITY)

    prev_revenue = _pick(prev, *_REVENUE) if prev else None

    def ratio(num, den):
        return None if num is None or den in (None, 0) else num / den

    gross_margin = ratio((revenue - operate_cost) if revenue is not None and operate_cost is not None else None, revenue)
    net_margin = ratio(net_profit, revenue)
    roe = ratio(parent_net, total_equity)
    debt_ratio = ratio(total_liab, total_assets)
    revenue_yoy = None
    if revenue is not None and prev_revenue not in (None, 0):
        revenue_yoy = (revenue - prev_revenue) / prev_revenue

    return {
        "code": code,
        "security_code": security_code,
        "name": name,
        "report_date": cur.get("REPORT_DATE"),
        "revenue": revenue,
        "net_profit": net_profit,
        "parent_net_profit": parent_net,
        "gross_margin": gross_margin,
        "net_margin": net_margin,
        "roe": roe,
        "debt_ratio": debt_ratio,
        "revenue_yoy": revenue_yoy,
    }


def get_recommend_settings(config):
    """返回合并后的推荐设置（config.recommend 为默认，settings.json 覆盖）。"""
    base = (config or {}).get("recommend", {}) or {}
    runtime = {}
    try:
        from settings_store import load_runtime_settings
        runtime = (load_runtime_settings() or {}).get("recommend", {}) or {}
    except Exception:  # noqa: BLE001
        runtime = {}

    merged = {
        "max_candidates": base.get("max_candidates", 15),
        "thresholds": dict(base.get("thresholds", {}) or {}),
        "score_weights": dict(base.get("score_weights", {}) or {}),
        "sort_by": base.get("sort_by", "score"),
    }
    if "max_candidates" in runtime:
        merged["max_candidates"] = runtime["max_candidates"]
    if "thresholds" in runtime:
        merged["thresholds"].update(runtime["thresholds"] or {})
    if "score_weights" in runtime:
        merged["score_weights"].update(runtime["score_weights"] or {})
    if "sort_by" in runtime:
        merged["sort_by"] = runtime["sort_by"]
    return merged


def fetch_recommendations(config, fetch_settings=None):
    """批量获取并筛选优质公司，返回（结果列表, 统计信息）。"""
    recommend = (config or {}).get("recommend", {}) or {}
    candidates = recommend.get("candidates", []) or []
    settings = get_recommend_settings(config)
    fs = fetch_settings or {}

    max_candidates = int(settings.get("max_candidates", 15))
    candidates = candidates[:max_candidates] if max_candidates > 0 else candidates
    th = settings.get("thresholds", {}) or {}
    weights = settings.get("score_weights", {}) or {}

    rows = []
    failed = 0
    for cand in candidates:
        try:
            m = _fetch_one(cand, config, fs)
        except Exception:  # noqa: BLE001
            m = None
        if m is None:
            failed += 1
            continue

        # 门槛过滤（None 视为不满足；用户可把门槛设为 0/负值以放宽）
        def ok(val, minimum):
            if val is None:
                return False
            return val >= float(minimum)

        def ok_max(val, maximum):
            if val is None:
                return True  # 缺失资产负债率时不据此淘汰
            return val <= float(maximum)

        if not ok(m.get("roe"), th.get("min_roe", 0)):
            continue
        if not ok(m.get("net_margin"), th.get("min_net_margin", 0)):
            continue
        if not ok(m.get("gross_margin"), th.get("min_gross_margin", 0)):
            continue
        if not ok(m.get("revenue_yoy"), th.get("min_revenue_yoy", -2)):
            continue
        if not ok_max(m.get("debt_ratio"), th.get("max_debt_ratio", 2)):
            continue

        m["score"] = _score_one(m, weights)
        m["advantage"] = _advantage(m)
        rows.append(m)

    rows.sort(key=lambda r: r.get("score", 0), reverse=True)
    return rows, {"total_candidates": len(candidates), "matched": len(rows), "failed": failed}
