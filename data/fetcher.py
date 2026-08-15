"""财务数据抓取模块。

数据获取策略（可配置，见 config.json / 网页设置）：
1. **优先使用网页 API**：东方财富公开 JSON 接口，抓取三大报表与主要指标；
2. **API 失败时降级为爬虫**：解析新浪财经公开的财务报表 HTML 页面。

通用约束：
- 域名白名单校验，防止越界访问；
- 爬虫伪装（随机 User-Agent + Referer）；
- 全局限速（最小请求间隔），减少访问量；
- 失败重试。
"""
import datetime
import random
import re
import time
from urllib.parse import quote, urlparse

import requests

from . import crawler

# 域名白名单（与 config.json 保持一致，作为运行时兜底校验）
ALLOWED_DOMAINS = {
    "searchapi.eastmoney.com",
    "datacenter-web.eastmoney.com",
    "emweb.securities.eastmoney.com",
    "push2.eastmoney.com",
    "suggest3.sinajs.cn",
    "hq.sinajs.cn",
    "qt.gtimg.cn",
    "money.finance.sina.com.cn",
    "www.cninfo.com.cn",
    "static.cninfo.com.cn",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://emweb.securities.eastmoney.com/",
}


class RateLimiter:
    """全局限速器：保证两次请求之间的最小间隔。"""

    def __init__(self):
        self._last = 0.0

    def wait(self, min_interval=0.0):
        if min_interval and min_interval > 0:
            elapsed = time.time() - self._last
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last = time.time()


_limiter = RateLimiter()


def _allowed_domains(config=None):
    domains = set(ALLOWED_DOMAINS)
    if config:
        for d in (config.get("data_sources", {}) or {}).get("allowed_domains", []):
            domains.add(d)
    return domains


def _build_headers(fetch_settings=None):
    """构造请求头；开启伪装时随机挑选 User-Agent。"""
    fs = fetch_settings or {}
    headers = dict(HEADERS)
    if fs.get("spoofing", True):
        headers["User-Agent"] = random.choice(crawler.USER_AGENTS)
    return headers


def safe_request(url, config=None, fetch_settings=None, **kwargs):
    """带白名单校验、限速、伪装与重试的安全 GET。"""
    host = urlparse(url).netloc
    if host not in _allowed_domains(config):
        raise ValueError("目标域名不在白名单内，已阻止访问：" + host)

    fs = fetch_settings or {}
    # 减少访问量：限速
    _limiter.wait(fs.get("min_interval_seconds", 0))

    headers = _build_headers(fs)
    headers.update(kwargs.pop("headers", {}))
    kwargs.setdefault("headers", headers)
    kwargs.setdefault("timeout", fs.get("timeout_seconds", 20))

    max_retries = int(fs.get("max_retries", 2))
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries:
                time.sleep(1 + attempt)
    raise last_err


def to_float(value):
    """把接口返回的字符串/数字安全转成 float，处理逗号、空值、'--'。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(",", "").strip()
    if s in ("", "-", "--", "None", "null", "不适用", "N/A"):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _f10(statement, security_code, dates, config=None, fetch_settings=None):
    """调用东财 F10 财务分析接口，返回 data 列表。"""
    url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/" + statement
        + "?companyType=4&reportDateType=0&reportType=1&dates=" + dates
        + "&code=" + security_code
    )
    resp = safe_request(url, config, fetch_settings)
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return []  # 接口返回非 JSON（如“无F10资料”HTML 页），容错返回空
    data = payload.get("data")
    if isinstance(data, dict):
        data = data.get("data") or []
    return data or []


def _annual_dates(years=7):
    """生成最近 N 个年度的报告期末日期（YYYY-12-31）。"""
    this_year = datetime.date.today().year
    return ",".join("%d-12-31" % y for y in range(this_year, this_year - years, -1))


def _pure_code(security_code):
    """从 SH600519 / SZ000001 提取纯 6 位代码。"""
    return re.sub(r"\D", "", security_code)[-6:]


def search_company(name, config=None, limit=10, fetch_settings=None):
    """根据公司名称 / 代码搜索 A 股（新浪 suggest 接口，GBK 编码）。

    返回形如：var suggestvalue="贵州茅台,11,600519,sh600519,贵州茅台,,...";
    用 ^ 分隔多个候选，逗号分隔字段，第 4 个字段带市场前缀（sh/sz/bj）。
    """
    url = (
        "https://suggest3.sinajs.cn/suggest/"
        "type=11,12,13,14,15,21,22,23,24,31,32,33,34,41,42,43,44&key=" + quote(str(name))
    )
    resp = safe_request(url, config, fetch_settings,
                        headers={"Referer": "https://finance.sina.com.cn"})
    text = resp.content.decode("gbk", errors="ignore")

    m = re.search(r'"([^"]*)"', text)
    if not m or not m.group(1):
        return []

    results = []
    for item in m.group(1).split("^"):
        parts = item.split(",")
        if len(parts) < 4:
            continue
        raw_name, sec_type, code, market_code = parts[0], parts[1], parts[2], parts[3]
        market = market_code[:2].upper()
        # 仅保留 A 股（沪/深/北交所，6 位数字代码）
        if market not in ("SH", "SZ", "BJ"):
            continue
        if not re.fullmatch(r"\d{6}", code):
            continue
        results.append({
            "code": code,
            "name": raw_name,
            "market": market,
            "security_code": market_code.upper(),
            "quote_id": market_code.upper(),
            "security_type": sec_type,
        })
    return results[:limit]


def fetch_company_info(security_code, config=None, fetch_settings=None):
    """尽力获取公司基本信息（所属行业 / 主营业务等），失败返回空 dict。"""
    info = {}
    try:
        url = (
            "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
            "?code=" + security_code
        )
        payload = safe_request(url, config, fetch_settings).json()
        jbzl = payload.get("jbzl") or []
        for item in jbzl:
            key = str(item.get("itemName") or item.get("name") or "")
            val = item.get("itemValue") or item.get("value") or ""
            if "行业" in key:
                info["industry"] = val
            elif "主营" in key or "经营" in key:
                info["main_business"] = val
            elif "公司名称" in key:
                info["company_name"] = val
            elif "上市" in key or "发行" in key:
                info["listing_date"] = val
    except Exception:  # noqa: BLE001
        pass
    return info


def _api_fetch(security_code, name, dates, config, fetch_settings):
    """优先方案：通过公开 API 抓取三大报表与主要指标。"""
    return {
        "security_code": security_code,
        "name": name or "",
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "api",
        "company_info": fetch_company_info(security_code, config, fetch_settings),
        "income": _f10("lrbAjaxNew", security_code, dates, config, fetch_settings),
        "balance": _f10("zcfzbAjaxNew", security_code, dates, config, fetch_settings),
        "cashflow": _f10("xjllbAjaxNew", security_code, dates, config, fetch_settings),
        # 主要指标接口已废弃（返回“无F10资料”），置空，EPS/加权ROE 由三表计算或标注缺失
        "indicators": [],
    }


def _crawler_fetch(security_code, name, max_years, config, fetch_settings):
    """降级方案：爬取新浪财经财务报表 HTML 页面（受限速约束）。"""
    code = _pure_code(security_code)
    this_year = datetime.date.today().year
    # 爬虫仅抓取最近 5 年，进一步减少访问量
    span = min(int(max_years or 5), 5)
    metrics = []
    for y in range(this_year, this_year - span, -1):
        url = (
            "https://money.finance.sina.com.cn/corp/go.php/vFD_FinancialGuideLine/"
            "stockid/" + code + "/ctrl/" + str(y) + "/displaytype/4.phtml"
        )
        resp = safe_request(url, config, fetch_settings)
        html = resp.content.decode("gbk", errors="ignore")
        metrics.extend(crawler.parse_sina_metrics_page(html))

    if not metrics:
        raise RuntimeError("爬虫未能解析到财务数据")

    # 去重并按报告期降序
    seen = {}
    for m in metrics:
        if m.get("REPORT_DATE"):
            seen[m["REPORT_DATE"]] = m
    ordered = [seen[d] for d in sorted(seen, reverse=True)]
    return crawler.build_crawler_data(security_code, name, ordered)


def fetch_financial_data(security_code, name=None, config=None, fetch_settings=None):
    """按策略抓取公司财务数据：优先 API，失败后按设置降级为爬虫。"""
    fs = fetch_settings or {}
    mode = fs.get("mode", "auto")
    max_years = int(fs.get("max_years", 7))
    dates = _annual_dates(max_years)

    # 1. 优先 API
    api_err = None
    if mode in ("auto", "api_only"):
        try:
            return _api_fetch(security_code, name, dates, config, fetch_settings)
        except Exception as e:  # noqa: BLE001
            api_err = e
            if mode == "api_only":
                raise RuntimeError("API 获取失败（当前为“仅 API”模式）：" + str(e))

    # 2. 降级为爬虫
    if mode == "auto":
        try:
            return _crawler_fetch(security_code, name, max_years, config, fetch_settings)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "API 与爬虫均获取失败。API 错误：" + str(api_err) + "；爬虫错误：" + str(e)
            )

    raise RuntimeError("未知的数据获取模式：" + str(mode))
