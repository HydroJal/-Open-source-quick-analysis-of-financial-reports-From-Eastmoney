"""HTML 爬虫回退模块（当 API 不可用时使用）。

原则：
- 只作为 API 失败后的降级方案；
- 抓取前做爬虫伪装（随机 User-Agent + Referer）；
- 受全局限速器约束，减少访问量；
- 数据源为新浪财经公开的财务报表 HTML 页面（GBK 编码）。

返回的数据结构与 API 抓取尽量同构，便于上游指标计算统一处理。
"""
import re

# 爬虫伪装 User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# 新浪财务指标页中需要提取的中文指标名 -> 内部英文字段
SINA_METRIC_MAP = {
    "基本每股收益": "EPSJB",
    "净资产收益率": "ROEJQ",      # 加权净资产收益率
    "主营业务收入": "TOTAL_OPERATE_INCOME",   # 单位：万元
    "净利润": "NETPROFIT",                     # 单位：万元
    "毛利率": "XSMLL",                          # 百分比数值
    "净利率": "XSJLL",                          # 百分比数值
    "资产负债率": "ZCFZL",                      # 百分比数值
    "主营业务收入增长": "YYZSRGD",              # 百分比数值
    "净利润增长": "PARENTNETPROFITYOY",         # 百分比数值
}

# 金额类字段（新浪单位为万元，需要 ×1e4 转成元）
_AMOUNT_FIELDS = {"TOTAL_OPERATE_INCOME", "NETPROFIT"}
# 其余字段（每股收益、比率等）保持原样：比率类为百分比数值（如 30.26 表示 30.26%），
# 与东财 API 的 ZYZBAjaxNew 字段语义保持一致，便于指标计算统一处理。


def _strip_tags(html):
    """去掉 HTML 标签与空白，返回纯文本。"""
    text = re.sub(r"<[^>]+>", "", html or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return text.strip()


def _to_float(text):
    if text is None:
        return None
    s = str(text).replace(",", "").replace("%", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def parse_sina_metrics_page(html_text):
    """解析新浪财务指标页 HTML，返回 [{report_date, ...字段}, ...]。

    页面结构：第一行是报告期表头（各列形如 YYYY-MM-DD），后续每行是一个指标。
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, flags=re.S | re.I)
    table = []
    for row in rows:
        cells = re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", row, flags=re.S | re.I)
        if not cells:
            continue
        clean = [_strip_tags(c) for c in cells]
        table.append(clean)

    # 找到表头行：第一列之后的所有列都是日期格式
    header = None
    header_idx = -1
    for i, row in enumerate(table):
        if len(row) >= 2 and all(re.search(r"\d{4}-\d{2}-\d{2}", d) for d in row[1:]):
            header = row[1:]
            header_idx = i
            break
    if header is None:
        return []

    # 按报告期组织数据
    result = []
    for col, date in enumerate(header):
        m = re.search(r"\d{4}-\d{2}-\d{2}", date)
        if not m:
            continue
        report_date = m.group()
        entry = {"REPORT_DATE": report_date}
        for row in table[header_idx + 1:]:
            if len(row) <= col + 1:
                continue
            name = row[0]
            raw_val = row[col + 1]
            # 最长中文名优先匹配，避免 "主营业务收入" 误匹配 "主营业务收入增长率"
            matched = None
            for cn, en in SINA_METRIC_MAP.items():
                if name.startswith(cn) and (matched is None or len(cn) > len(matched[0])):
                    matched = (cn, en)
            if matched:
                val = _to_float(raw_val)
                if val is not None:
                    if matched[1] in _AMOUNT_FIELDS:
                        entry[matched[1]] = val * 1e4   # 万元 -> 元
                    else:
                        entry[matched[1]] = val          # 比率等保持百分比数值
        result.append(entry)
    return result


def build_crawler_data(security_code, name, metrics):
    """把爬虫解析出的指标列表构造成与 API 抓取同构的数据 dict。"""
    income = []
    indicators = []
    for m in metrics:
        income.append({
            "REPORT_DATE": m.get("REPORT_DATE"),
            "TOTAL_OPERATE_INCOME": m.get("TOTAL_OPERATE_INCOME"),
            "NETPROFIT": m.get("NETPROFIT"),
        })
        indicators.append({
            "REPORT_DATE": m.get("REPORT_DATE"),
            "EPSJB": m.get("EPSJB"),
            "ROEJQ": m.get("ROEJQ"),
            "XSMLL": m.get("XSMLL"),
            "XSJLL": m.get("XSJLL"),
            "ZCFZL": m.get("ZCFZL"),
            "YYZSRGD": m.get("YYZSRGD"),
            "PARENTNETPROFITYOY": m.get("PARENTNETPROFITYOY"),
        })
    import datetime
    return {
        "security_code": security_code,
        "name": name or "",
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "crawler",
        "company_info": {},
        "income": income,
        "balance": [],
        "cashflow": [],
        "indicators": indicators,
    }
