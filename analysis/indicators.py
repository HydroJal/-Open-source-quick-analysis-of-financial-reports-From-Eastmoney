"""财务指标计算模块。

从爬取的三大报表 + 主要指标中计算杜邦三因子、现金流质量、财务健康等
核心指标，并把结果拼装成可供 LLM 分析的结构化文本载荷。
"""
import re

# 字段候选表：内部语义名 -> 东财接口可能的英文字段名
INCOME_FIELDS = {
    "revenue": ("TOTAL_OPERATE_INCOME", "OPERATE_INCOME"),
    "operate_cost": ("OPERATE_COST", "TOTAL_OPERATE_COST"),
    "operate_profit": ("OPERATE_PROFIT",),
    "total_profit": ("TOTAL_PROFIT",),
    "net_profit": ("NETPROFIT",),
    "parent_net_profit": ("PARENT_NETPROFIT",),
    "deduct_parent_net_profit": ("DEDUCT_PARENT_NETPROFIT", "KCFJCXSYJLR"),
}

BALANCE_FIELDS = {
    "total_assets": ("TOTAL_ASSETS",),
    "total_liabilities": ("TOTAL_LIABILITIES",),
    "total_equity": ("TOTAL_EQUITY",),
    "parent_equity": ("TOTAL_PARENT_EQUITY", "PARENT_EQUITY"),
    "monetary_funds": ("MONETARYFUNDS", "MONETARY_FUNDS"),
    "accounts_receivable": ("ACCOUNTS_RECE", "ACCOUNTS_RECEIVABLE", "ACCOUNT_RECEIVABLE"),
    "inventory": ("INVENTORY", "INVENTORIES"),
    "goodwill": ("GOODWILL",),
    "current_assets": ("TOTAL_CURRENT_ASSETS", "CURRENT_ASSETS"),
    "current_liabilities": ("TOTAL_CURRENT_LIAB", "TOTAL_CURRENT_LIABILITIES", "CURRENT_LIABILITIES"),
}

CASHFLOW_FIELDS = {
    "ocf": ("NETCASH_OPERATE", "NETCASH_OPERATING"),
    "icf": ("NETCASH_INVEST", "NETCASH_INVESTING"),
    "fcf": ("NETCASH_FINANCE", "NETCASH_FINANCING"),
}

ZY_FIELDS = {
    "eps": ("EPSJB", "BASIC_EPS"),
    "roe_weighted": ("ROEJQ", "WEIGHTAVG_ROE"),
    "gross_margin": ("XSMLL", "GROSS_PROFIT_RATIO"),
    "net_margin": ("XSJLL", "NET_PROFIT_RATIO"),
    "debt_ratio": ("ZCFZL",),
}


def _to_num(v):
    """安全转 float，处理逗号、空值、'--'。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "--", "None", "null", "不适用", "N/A"):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _pick(row, *candidates):
    """从一行记录中按候选字段名取第一个存在的数值。"""
    for c in candidates:
        if c in row:
            val = _to_num(row.get(c))
            if val is not None:
                return val
    return None


def _annual(rows):
    """过滤出年报（REPORT_DATE 日期部分以 12-31 结尾）并按日期降序排列。

    东财接口的 REPORT_DATE 可能带时间（如 "2025-12-31 00:00:00"），
    这里统一规范化为 "YYYY-MM-DD"。
    """
    out = []
    for r in rows:
        rd = str(r.get("REPORT_DATE", "")).split(" ")[0]
        if rd.endswith("12-31"):
            row = dict(r)
            row["REPORT_DATE"] = rd
            out.append(row)
    out.sort(key=lambda r: r.get("REPORT_DATE", ""), reverse=True)
    return out


def _ratio(num, den):
    """安全计算比值，分母为 0 或缺失返回 None。"""
    if num is None or den is None or den == 0:
        return None
    return num / den


def _pct_change(cur, prev):
    """同比增速：与上一期比较。"""
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / prev


def compute_indicators(data):
    """计算核心财务指标，返回 {latest, history}。"""
    income = _annual(data.get("income") or [])
    balance = _annual(data.get("balance") or [])
    cashflow = _annual(data.get("cashflow") or [])
    zy = _annual(data.get("indicators") or [])

    def index(rows):
        return {str(r.get("REPORT_DATE", "")): r for r in rows}

    bi = index(balance)
    cf = index(cashflow)
    zi = index(zy)

    years = []
    for row in income:
        d = str(row.get("REPORT_DATE", ""))
        rev = _pick(row, *INCOME_FIELDS["revenue"])
        op_cost = _pick(row, *INCOME_FIELDS["operate_cost"])
        net = _pick(row, *INCOME_FIELDS["net_profit"])
        parent_net = _pick(row, *INCOME_FIELDS["parent_net_profit"])

        b = bi.get(d, {})
        total_assets = _pick(b, *BALANCE_FIELDS["total_assets"])
        total_liab = _pick(b, *BALANCE_FIELDS["total_liabilities"])
        total_equity = _pick(b, *BALANCE_FIELDS["total_equity"])
        parent_equity = _pick(b, *BALANCE_FIELDS["parent_equity"]) or total_equity
        goodwill = _pick(b, *BALANCE_FIELDS["goodwill"])
        current_assets = _pick(b, *BALANCE_FIELDS["current_assets"])
        current_liab = _pick(b, *BALANCE_FIELDS["current_liabilities"])

        c = cf.get(d, {})
        ocf = _pick(c, *CASHFLOW_FIELDS["ocf"])

        z = zi.get(d, {})
        eps = _pick(z, *ZY_FIELDS["eps"])
        roe_weighted = _pick(z, *ZY_FIELDS["roe_weighted"])
        # 主要指标中的比率（百分比数值，回退时需 ÷100 转小数）
        zy_gross_margin = _pick(z, *ZY_FIELDS["gross_margin"])
        zy_net_margin = _pick(z, *ZY_FIELDS["net_margin"])
        zy_debt_ratio = _pick(z, *ZY_FIELDS["debt_ratio"])

        gross_margin = _ratio((rev - op_cost) if rev is not None and op_cost is not None else None, rev)
        if gross_margin is None and zy_gross_margin is not None:
            gross_margin = zy_gross_margin / 100.0
        net_margin = _ratio(net, rev)
        if net_margin is None and zy_net_margin is not None:
            net_margin = zy_net_margin / 100.0
        debt_ratio = _ratio(total_liab, total_assets)
        if debt_ratio is None and zy_debt_ratio is not None:
            debt_ratio = zy_debt_ratio / 100.0

        asset_turnover = _ratio(rev, total_assets)
        equity_multiplier = _ratio(total_assets, total_equity)
        roe = _ratio(parent_net, parent_equity)
        roe_dupont = None
        if net_margin is not None and asset_turnover is not None and equity_multiplier is not None:
            roe_dupont = net_margin * asset_turnover * equity_multiplier

        years.append({
            "report_date": d,
            "year": d[:4],
            "revenue": rev,
            "operate_cost": op_cost,
            "gross_margin": gross_margin,
            "net_profit": net,
            "parent_net_profit": parent_net,
            "net_margin": net_margin,
            "total_assets": total_assets,
            "total_liabilities": total_liab,
            "total_equity": total_equity,
            "debt_ratio": debt_ratio,
            "current_assets": current_assets,
            "current_liabilities": current_liab,
            "current_ratio": _ratio(current_assets, current_liab),
            "goodwill": goodwill,
            "goodwill_ratio": _ratio(goodwill, total_assets),
            "ocf": ocf,
            "ocf_to_net_profit": _ratio(ocf, net),
            "roe": roe,
            "roe_dupont": roe_dupont,
            "roe_weighted": roe_weighted,  # 数据源直接给出的加权ROE（百分比数值）
            "eps": eps,
            "asset_turnover": asset_turnover,
            "equity_multiplier": equity_multiplier,
        })

    # 计算同比增速（相对上一期年报）
    for i, y in enumerate(years):
        prev = years[i + 1] if i + 1 < len(years) else None
        y["revenue_yoy"] = _pct_change(y.get("revenue"), prev.get("revenue") if prev else None)
        y["parent_net_profit_yoy"] = _pct_change(
            y.get("parent_net_profit"), prev.get("parent_net_profit") if prev else None
        )

    return {
        "latest": years[0] if years else {},
        "history": years,
    }


# ── 格式化工具 ──────────────────────────────────────────
def _yi(v):
    """金额 -> 亿元字符串（数据未提供时给出标注）。"""
    if v is None:
        return "数据未提供"
    return "%.2f 亿元" % (v / 1e8)


def _pct(v):
    """比例（0.x）-> 百分比字符串。"""
    if v is None:
        return "数据未提供"
    return "%.2f%%" % (v * 100)


def _pct_raw(v):
    """数据源直接给出的百分比数值 -> 百分比字符串。"""
    if v is None:
        return "数据未提供"
    return "%.2f%%" % v


def _num(v):
    if v is None:
        return "数据未提供"
    return "%.4f" % v


def build_data_payload(data, indicators):
    """把基础信息 + 指标拼装成 LLM 用户消息的结构化文本。"""
    latest = indicators.get("latest") or {}
    history = indicators.get("history") or []
    ci = data.get("company_info") or {}

    lines = []
    lines.append("# 公司基础信息")
    lines.append("- 证券代码：" + str(data.get("security_code", "数据未提供")))
    lines.append("- 公司名称：" + str(data.get("name") or "数据未提供"))
    lines.append("- 所属行业：" + str(ci.get("industry") or "数据未提供"))
    lines.append("- 主营业务：" + str(ci.get("main_business") or "数据未提供"))

    lines.append("")
    lines.append("# 最新一期核心财务指标（报告期 " + str(latest.get("report_date", "未知")) + "）")
    lines.append("- 营业收入：" + _yi(latest.get("revenue")) + "，同比 " + _pct(latest.get("revenue_yoy")))
    lines.append("- 归母净利润：" + _yi(latest.get("parent_net_profit")) + "，同比 " + _pct(latest.get("parent_net_profit_yoy")))
    lines.append("- 净利润：" + _yi(latest.get("net_profit")))
    lines.append("- 毛利率：" + _pct(latest.get("gross_margin")))
    lines.append("- 净利率：" + _pct(latest.get("net_margin")))
    lines.append("- 总资产周转率：" + _num(latest.get("asset_turnover")))
    lines.append("- 权益乘数（杠杆）：" + _num(latest.get("equity_multiplier")))
    lines.append("- ROE（归母）：" + _pct(latest.get("roe")) + "；杜邦拆解乘积 " + _pct(latest.get("roe_dupont")) + "；数据源加权 ROE " + _pct_raw(latest.get("roe_weighted")))
    lines.append("- 资产负债率：" + _pct(latest.get("debt_ratio")))
    lines.append("- 流动比率：" + _num(latest.get("current_ratio")))
    lines.append("- 经营现金流净额：" + _yi(latest.get("ocf")) + "，经营现金流/净利润 " + _num(latest.get("ocf_to_net_profit")))
    lines.append("- 商誉占总资产比例：" + _pct(latest.get("goodwill_ratio")))
    lines.append("- 基本每股收益：" + _num(latest.get("eps")))

    lines.append("")
    lines.append("# 近 " + str(len(history)) + " 年关键科目趋势（年报）")
    lines.append("| 报告期 | 营收(亿元) | 归母净利(亿元) | 毛利率 | 净利率 | ROE | 资产负债率 | 经营现金流(亿元) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for y in history:
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                y.get("year", "?"),
                "%.2f" % (y["revenue"] / 1e8) if y.get("revenue") is not None else "-",
                "%.2f" % (y["parent_net_profit"] / 1e8) if y.get("parent_net_profit") is not None else "-",
                "%.2f%%" % (y["gross_margin"] * 100) if y.get("gross_margin") is not None else "-",
                "%.2f%%" % (y["net_margin"] * 100) if y.get("net_margin") is not None else "-",
                "%.2f%%" % (y["roe"] * 100) if y.get("roe") is not None else "-",
                "%.2f%%" % (y["debt_ratio"] * 100) if y.get("debt_ratio") is not None else "-",
                "%.2f" % (y["ocf"] / 1e8) if y.get("ocf") is not None else "-",
            )
        )

    lines.append("")
    lines.append("# 说明")
    lines.append("- 以上数据均来自公开财报接口，仅包含三大报表关键科目与由此计算出的指标；")
    lines.append("- 未提供的科目（如年报 PDF 原文、行业宏观数据）不在本次输入中，请按“数据未提供”处理；")
    lines.append("- 请严格依据上述真实数字进行分析，并遵守你的输出格式与免责声明要求。")

    return "\n".join(lines)
