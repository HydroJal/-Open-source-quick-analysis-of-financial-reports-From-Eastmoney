# 📊 金融财报快捷分析

HydroJaL 基于 Deepseek制作

根据公司名称爬取 A 股上市公司的财报 / 年报数据，保存到本地，计算核心财务指标，并调用用户可选的多种 AI 大模型生成卖方分析师风格的研究报告。并附带网页客户端。
可以下载Zip文件解压后直接使用，初次使用可能需要在网页端设置内下载必须的库

## 功能

1. **财报爬取**：输入公司名称或股票代码，自动搜索并解析证券代码，从公开财报接口抓取近 5 年三大报表（利润表 / 资产负债表 / 现金流量表）与主要财务指标。
2. **本地存储**：抓取结果以 JSON 形式保存在 `data_store/` 目录下，重复分析同一公司时默认走本地缓存（可勾选“强制重新抓取”）。
3. **指标计算**：营收 / 归母净利同比、毛利率、净利率、ROE 杜邦三因子拆解（净利率 × 周转率 × 杠杆）、资产负债率、流动比率、经营现金流 / 净利润、商誉占比等。
4. **多 AI 接入**：通过统一的 `BaseLLMClient` 抽象接口 + 配置化驱动，一键切换 DeepSeek、通义千问、Kimi、智谱、OpenAI、Claude、Ollama 等模型。
5. **网页客户端**：`web/` 下的单页应用，输入 → 选模型 → 分析 → 展示指标表格与 AI 报告。

## 目录结构

```
金融财报快捷分析/
├── app.py                  # Flask 后端入口（路由 + API）
├── config.json             # 配置（数据源白名单、LLM 服务商、默认提示词）
├── prompt.txt              # 默认分析师提示词
├── requirements.txt        # 依赖
├── llm/                    # LLM 抽象层
│   ├── base.py             #   BaseLLMClient 抽象基类
│   ├── openai_client.py    #   OpenAI 兼容客户端
│   ├── anthropic_client.py #   Claude 客户端
│   └── factory.py          #   工厂 + 配置解析
├── data/                   # 数据层
│   ├── fetcher.py          #   财报爬取（域名白名单校验）
│   └── storage.py          #   本地 JSON 持久化
├── analysis/
│   └── indicators.py       # 财务指标计算 + LLM 载荷拼装
├── web/                    # 网页客户端
│   ├── index.html
│   ├── style.css
│   └── app.js
└── data_store/             # 运行后自动生成，存放抓取结果
```

## 安装与运行

```bash
# 1. 安装依赖（建议 Python 3.9+）
pip install -r requirements.txt

# 2. 配置 API Key（环境变量，按需设置）
#    Windows PowerShell：
$env:DEEPSEEK_API_KEY = "sk-xxxxxxxx"
$env:DASHSCOPE_API_KEY = "sk-xxxxxxxx"
#    或直接编辑 config.json，把 "env:XXX" 替换为明文 key

# 3. 启动
python app.py

# 4. 浏览器打开
http://127.0.0.1:5000
```

## 配置说明（config.json）

- `data_sources.allowed_domains`：允许爬取的域名白名单，请求只允许命中这些域名，防止越界爬取。
- `llm.default_provider`：默认 AI 服务商。
- `llm.providers`：服务商列表。字段：
  - `name`：唯一标识（前端下拉值）
  - `display_name`：显示名称
  - `type`：客户端类型，支持 `openai`（OpenAI 兼容）与 `anthropic`
  - `base_url`：接口地址
  - `api_key`：支持两种写法——明文 key，或 `env:环境变量名`（推荐）
  - `model` / `models`：默认模型 / 可选模型列表
- `prompt_file`：默认提示词文件名（默认 `prompt.txt`）。
- `storage_dir`：本地数据保存目录。

### 如何新增一个 AI 服务商

只要它在 `config.json` 的 `providers` 里加一项即可，无需改代码（前提是它提供 OpenAI 兼容接口，`type` 设为 `openai` 并填对 `base_url`）。

## 使用流程

1. 输入公司名称或代码（如 `贵州茅台` / `600519`），点「搜索」。
2. 在候选列表里选择目标公司。
3. 选择 AI 服务商与模型。
4. 点「抓取财报并分析」，等待生成报告。

## 数据来源说明

- 数据来自东方财富网（eastmoney）公开的 F10 财务分析接口，仅用于研究学习。
- 年报 PDF 原文、行业宏观数据等当前版本未接入，分析时会按提示词要求标注“数据未提供”。

## 免责声明

本工具由 AI 模型基于公开财务数据自动生成分析，仅供研究学习使用，不构成任何投资建议。投资有风险，决策需谨慎。
