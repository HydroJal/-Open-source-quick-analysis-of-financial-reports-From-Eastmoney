// ── 全局状态 ──────────────────────────────
const state = {
  providers: [],
  defaultProvider: '',
  currentProvider: '',
  selected: null,       // 搜索后高亮的候选 {code, name, security_code, ...}
  confirmed: null,      // 点击「确认」后锁定的公司 {code, name, security_code, ...}
  searchResults: [],    // 最近一次搜索的候选列表
  rawStatements: null,  // 确认后加载的三大报表（已格式化）
  curStmt: 'income',    // 当前展示的报表 tab
  recResults: [],       // 推荐榜结果
};

// ── DOM 引用 ──────────────────────────────
const $ = (id) => document.getElementById(id);
const companyInput = $('companyInput');
const btnSearch = $('btnSearch');
const searchResults = $('searchResults');
const btnConfirm = $('btnConfirm');
const providerSelect = $('providerSelect');
const modelSelect = $('modelSelect');
const keyHint = $('keyHint');
const btnAnalyze = $('btnAnalyze');
const btnDownload = $('btnDownload');
const refreshCheck = $('refreshCheck');
const status = $('status');
const empty = $('empty');
const resultsWrap = $('resultsWrap');
const resultTitle = $('resultTitle');
const resultMeta = $('resultMeta');
const overviewTable = $('overviewTable');
const trendTable = $('trendTable');
const analysisContent = $('analysisContent');
// 原始财报
const rawDataWrap = $('rawDataWrap');
const rawTitle = $('rawTitle');
const rawMeta = $('rawMeta');
const stmtTabs = $('stmtTabs');
const stmtTable = $('stmtTable');

// ── 工具 ──────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function fmtYi(v) {
  if (v === null || v === undefined) return '—';
  return (v / 1e8).toFixed(2) + ' 亿';
}
function fmtPct(v) {
  if (v === null || v === undefined) return '—';
  return (v * 100).toFixed(2) + '%';
}
function fmtNum(v, digits) {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(digits == null ? 2 : digits);
}

// ── 初始化：加载服务商列表 ────────────────
async function loadProviders() {
  try {
    const res = await fetch('/api/providers');
    const data = await res.json();
    state.providers = data.providers || [];
    state.defaultProvider = data.default_provider || '';

    providerSelect.innerHTML = '';
    state.providers.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.name;
      opt.textContent = p.display_name + (p.has_key ? '' : '（未配置 Key）');
      providerSelect.appendChild(opt);
    });

    if (state.providers.length) {
      const def = state.providers.find((p) => p.name === state.defaultProvider) || state.providers[0];
      providerSelect.value = def.name;
      onProviderChange();
    }
  } catch (e) {
    status.innerHTML = '<span class="error">加载模型列表失败：' + esc(e.message) + '</span>';
  }
}

function onProviderChange() {
  const name = providerSelect.value;
  state.currentProvider = name;
  const p = state.providers.find((x) => x.name === name);
  modelSelect.innerHTML = '';
  if (!p) return;
  (p.models && p.models.length ? p.models : [p.model]).forEach((m) => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m;
    modelSelect.appendChild(opt);
  });
  keyHint.textContent = p.has_key
    ? '当前服务商已配置 API Key，可直接使用。'
    : '⚠️ 该服务商尚未配置 API Key（环境变量），请先设置后再分析。';
}

// ── 搜索公司 ──────────────────────────────
async function doSearch() {
  const name = companyInput.value.trim();
  if (!name) { setStatus('请输入公司名称或代码', 'error'); return; }

  setStatus('<span class="spinner"></span>正在搜索…', 'loading');
  searchResults.innerHTML = '';
  state.selected = null;
  state.confirmed = null;
  btnConfirm.disabled = true;

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company: name }),
    });
    const data = await res.json();
    if (!res.ok) { setStatus(data.error || '搜索失败', 'error'); return; }

    const results = data.results || [];
    if (!results.length) { setStatus('未找到匹配的 A 股上市公司', 'error'); return; }

    state.searchResults = results;
    selectResult(results[0]);
    setStatus('找到 ' + results.length + ' 个候选，请点选后点击「确认此公司并加载财报」', '');
  } catch (e) {
    setStatus('搜索失败：' + e.message, 'error');
  }
}

function renderSearchResults() {
  searchResults.innerHTML = '';
  state.searchResults.forEach((r) => {
    const div = document.createElement('div');
    div.className = 'search-item' + (state.selected && state.selected.security_code === r.security_code ? ' selected' : '');
    div.innerHTML =
      '<span class="s-name">' + esc(r.name) + '</span>' +
      '<span class="s-code">' + esc(r.security_code) + '</span>';
    div.addEventListener('click', () => selectResult(r));
    searchResults.appendChild(div);
  });
}

function selectResult(r) {
  state.selected = r;
  state.confirmed = null;   // 更换候选后需重新点击「确认」
  renderSearchResults();
  btnConfirm.disabled = !r;
}

// ── 确认公司并加载原始财报 ──────────────────────
async function doConfirm() {
  if (!state.selected) { setStatus('请先搜索并选择一家公司', 'error'); return; }

  const consented = await ensureLegalConsent();
  if (!consented) return;

  state.confirmed = state.selected;
  btnConfirm.disabled = true;
  const old = btnConfirm.textContent;
  btnConfirm.textContent = '⏳ 加载中…';
  setStatus('<span class="spinner"></span>正在抓取财报原始数据…', 'loading');

  try {
    const res = await fetch('/api/raw-data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company: state.confirmed.name,
        code: state.confirmed.security_code,
        name: state.confirmed.name,
        refresh: refreshCheck.checked,
      }),
    });
    const data = await res.json();
    if (!res.ok) { setStatus(data.error || '加载失败', 'error'); return; }

    state.rawStatements = data.statements || {};
    state.curStmt = 'income';
    renderRawData(data);
    setStatus('✅ 已加载「' + data.name + '」财报原始数据，可下载 Excel 或抓取分析', '');
  } catch (e) {
    setStatus('加载财报数据失败：' + e.message, 'error');
  } finally {
    btnConfirm.disabled = false;
    btnConfirm.textContent = old;
  }
}

function renderRawData(data) {
  empty.classList.add('hidden');
  rawDataWrap.classList.remove('hidden');

  rawTitle.textContent = data.name + '（' + data.code + '）';
  const ci = data.company_info || {};
  rawMeta.innerHTML =
    '行业：' + esc(ci.industry || '—') +
    ' ｜ 主营业务：' + esc(ci.main_business || '—') +
    ' ｜ 数据抓取时间：' + esc(data.fetched_at || '—') +
    ' ｜ 来源：' + esc(data.from_cache ? '本地缓存' : (data.source || 'api'));

  // 重置 tab 高亮
  stmtTabs.querySelectorAll('.stmt-tab').forEach((b) => {
    b.classList.toggle('active', b.dataset.stmt === state.curStmt);
  });
  renderStmtTable(state.curStmt);
  rawDataWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderStmtTable(key) {
  const t = state.rawStatements && state.rawStatements[key];
  if (!t || !t.dates || !t.dates.length || !t.fields || !t.fields.length) {
    stmtTable.innerHTML = '<tr><td>无数据</td></tr>';
    return;
  }
  const head = ['科目'].concat(t.dates);
  const body = t.fields.map((f) => {
    const cells = f.values.map((v) => {
      if (v === null || v === undefined) return '<td>—</td>';
      if (typeof v === 'number') return '<td>' + fmtNum(v, 2) + '</td>';
      return '<td>' + esc(v) + '</td>';
    });
    return '<tr><td>' + esc(f.label) + '</td>' + cells.join('') + '</tr>';
  }).join('');
  stmtTable.innerHTML =
    '<tr>' + head.map((h) => '<th>' + esc(h) + '</th>').join('') + '</tr>' + body;
}

// ── 下载数据（仅抓取 + 生成 Excel，不调用 AI）─────
async function downloadExcel() {
  if (!state.confirmed) { setStatus('请先搜索并点击「确认此公司」', 'error'); return; }

  const consented = await ensureLegalConsent();
  if (!consented) return;

  btnDownload.disabled = true;
  const old = btnDownload.textContent;
  btnDownload.textContent = '⏳ 生成中…';
  setStatus('<span class="spinner"></span>正在抓取数据并生成 Excel…', 'loading');

  try {
    const res = await fetch('/api/export-excel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company: state.confirmed.name,
        code: state.confirmed.security_code,
        name: state.confirmed.name,
        refresh: refreshCheck.checked,
      }),
    });
    if (!res.ok) {
      let msg = '导出失败';
      try { const d = await res.json(); msg = d.error || msg; } catch (_) {}
      setStatus(msg, 'error');
      return;
    }
    const blob = await res.blob();
    let filename = '财报数据.xlsx';
    const cd = res.headers.get('Content-Disposition') || '';
    const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = cd.match(/filename="?([^";]+)"?/i);
    if (star) { try { filename = decodeURIComponent(star[1]); } catch (_) { filename = star[1]; } }
    else if (plain) { filename = plain[1]; }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus('✅ 已导出：' + filename, '');
  } catch (e) {
    setStatus('导出失败：' + e.message, 'error');
  } finally {
    btnDownload.disabled = false;
    btnDownload.textContent = old;
  }
}

// ── 分析 ──────────────────────────────────
async function doAnalyze() {
  if (!state.confirmed) { setStatus('请先搜索并点击「确认此公司」', 'error'); return; }

  // 法律与合规确认（首次分析前必须勾选同意）
  const consented = await ensureLegalConsent();
  if (!consented) return;

  btnAnalyze.disabled = true;
  btnAnalyze.textContent = '⏳ 分析中…';
  setStatus('<span class="spinner"></span>正在抓取财报数据、计算指标并调用 AI 分析（可能需要一段时间）…', 'loading');

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company: state.confirmed.name,
        code: state.confirmed.security_code,
        name: state.confirmed.name,
        provider: providerSelect.value,
        model: modelSelect.value,
        refresh: refreshCheck.checked,
      }),
    });
    const data = await res.json();
    if (!res.ok) { setStatus(data.error || '分析失败', 'error'); return; }

    renderResults(data);
    setStatus('✅ 分析完成', '');
  } catch (e) {
    setStatus('分析失败：' + e.message, 'error');
  } finally {
    btnAnalyze.disabled = false;
    btnAnalyze.textContent = '🚀 抓取财报并分析';
  }
}

function setStatus(msg, cls) {
  status.className = 'status' + (cls ? ' ' + cls : '');
  status.innerHTML = msg;
}

// ── 渲染结果 ──────────────────────────────
function renderResults(data) {
  empty.classList.add('hidden');
  resultsWrap.classList.remove('hidden');

  resultTitle.textContent = data.name + '（' + data.code + '）';
  const ci = data.company_info || {};
  resultMeta.innerHTML =
    '行业：' + esc(ci.industry || '—') +
    ' ｜ 主营业务：' + esc(ci.main_business || '—') +
    ' ｜ 数据抓取时间：' + esc(data.fetched_at || '—') +
    '<br>分析模型：' + esc(data.provider + ' / ' + data.model);

  renderOverview(data.indicators && data.indicators.latest);
  renderTrend(data.indicators && data.indicators.history);
  analysisContent.innerHTML = mdToHtml(data.analysis || '');

  resultsWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderOverview(latest) {
  if (!latest || !Object.keys(latest).length) {
    overviewTable.innerHTML = '<tr><td>无数据</td></tr>';
    return;
  }
  const rows = [
    ['报告期', latest.report_date || '—'],
    ['营业收入', fmtYi(latest.revenue) + '（同比 ' + fmtPct(latest.revenue_yoy) + '）'],
    ['归母净利润', fmtYi(latest.parent_net_profit) + '（同比 ' + fmtPct(latest.parent_net_profit_yoy) + '）'],
    ['毛利率', fmtPct(latest.gross_margin)],
    ['净利率', fmtPct(latest.net_margin)],
    ['ROE（归母）', fmtPct(latest.roe)],
    ['总资产周转率', fmtNum(latest.asset_turnover, 3)],
    ['权益乘数（杠杆）', fmtNum(latest.equity_multiplier, 3)],
    ['资产负债率', fmtPct(latest.debt_ratio)],
    ['流动比率', fmtNum(latest.current_ratio, 3)],
    ['经营现金流 / 净利润', fmtNum(latest.ocf_to_net_profit, 3)],
    ['商誉 / 总资产', fmtPct(latest.goodwill_ratio)],
    ['基本每股收益', fmtNum(latest.eps, 4)],
  ];
  overviewTable.innerHTML =
    '<tr><th style="text-align:left;">指标</th><th>数值</th></tr>' +
    rows.map((r) => '<tr><td>' + esc(r[0]) + '</td><td>' + esc(r[1]) + '</td></tr>').join('');
}

function renderTrend(history) {
  if (!history || !history.length) {
    trendTable.innerHTML = '<tr><td>无数据</td></tr>';
    return;
  }
  const head = ['报告期', '营收(亿)', '归母净利(亿)', '毛利率', '净利率', 'ROE', '资产负债率', '经营现金流(亿)'];
  const body = history.map((y) => {
    return '<tr><td>' + esc(y.year || y.report_date || '—') + '</td>' +
      '<td>' + fmtNum(y.revenue / 1e8, 2) + '</td>' +
      '<td>' + fmtNum(y.parent_net_profit / 1e8, 2) + '</td>' +
      '<td>' + fmtPct(y.gross_margin) + '</td>' +
      '<td>' + fmtPct(y.net_margin) + '</td>' +
      '<td>' + fmtPct(y.roe) + '</td>' +
      '<td>' + fmtPct(y.debt_ratio) + '</td>' +
      '<td>' + fmtNum(y.ocf / 1e8, 2) + '</td></tr>';
  }).join('');
  trendTable.innerHTML =
    '<tr>' + head.map((h) => '<th>' + esc(h) + '</th>').join('') + '</tr>' + body;
}

// ── Markdown 渲染（轻量自实现，覆盖报告所需语法） ──
function mdToHtml(md) {
  const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
  let html = '';
  let i = 0;
  let listOpen = null;   // 'ul' | 'ol'
  let inCode = false;
  let codeBuf = [];

  const closeList = () => {
    if (listOpen) { html += '</' + listOpen + '>'; listOpen = null; }
  };

  const inline = (text) => {
    let t = esc(text);
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    return t;
  };

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trimEnd();

    // 代码块
    if (line.trim().startsWith('```')) {
      if (!inCode) { inCode = true; codeBuf = []; i++; continue; }
      else { html += '<pre><code>' + esc(codeBuf.join('\n')) + '</code></pre>'; inCode = false; i++; continue; }
    }
    if (inCode) { codeBuf.push(raw); i++; continue; }

    const t = line.trim();

    if (!t) { closeList(); html += ''; i++; continue; }

    // 表格
    if (t.startsWith('|') && t.endsWith('|')) {
      closeList();
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        rows.push(lines[i].trim());
        i++;
      }
      html += renderTable(rows);
      continue;
    }

    // 标题
    const h = t.match(/^(#{1,6})\s+(.*)$/);
    if (h) { closeList(); const lv = h[1].length; html += '<h' + lv + '>' + inline(h[2]) + '</h' + lv + '>'; i++; continue; }

    // 分隔线
    if (/^(-{3,}|\*{3,})$/.test(t)) { closeList(); html += '<hr>'; i++; continue; }

    // 引用块
    if (t.startsWith('>')) { closeList(); html += '<blockquote>' + inline(t.replace(/^>\s?/, '')) + '</blockquote>'; i++; continue; }

    // 列表
    const ul = t.match(/^[-*+]\s+(.*)$/);
    const ol = t.match(/^\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const kind = ul ? 'ul' : 'ol';
      if (listOpen !== kind) { closeList(); html += '<' + kind + '>'; listOpen = kind; }
      html += '<li>' + inline(ul ? ul[1] : ol[1]) + '</li>';
      i++;
      continue;
    }

    // 普通段落
    closeList();
    html += '<p>' + inline(t) + '</p>';
    i++;
  }

  if (inCode) html += '<pre><code>' + esc(codeBuf.join('\n')) + '</code></pre>';
  closeList();
  return html;
}

function renderTable(rows) {
  const cells = rows.map((r) =>
    r.replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
  );
  if (!cells.length) return '';
  const header = cells[0];
  let html = '<table><thead><tr>' +
    header.map((c) => '<th>' + esc(c.replace(/\*\*/g, '')) + '</th>').join('') +
    '</tr></thead><tbody>';
  for (let r = 1; r < cells.length; r++) {
    // 跳过分隔行 |---|---|
    if (cells[r].every((c) => /^:?-{2,}:?$/.test(c))) continue;
    html += '<tr>' + cells[r].map((c) => '<td>' + esc(c.replace(/\*\*/g, '')) + '</td>').join('') + '</tr>';
  }
  html += '</tbody></table>';
  return html;
}

// ── 事件绑定 ──────────────────────────────
btnSearch.addEventListener('click', doSearch);
companyInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
providerSelect.addEventListener('change', onProviderChange);
btnAnalyze.addEventListener('click', doAnalyze);
btnDownload.addEventListener('click', downloadExcel);
btnConfirm.addEventListener('click', doConfirm);
stmtTabs.addEventListener('click', (e) => {
  const tab = e.target.closest('.stmt-tab');
  if (!tab) return;
  state.curStmt = tab.dataset.stmt;
  stmtTabs.querySelectorAll('.stmt-tab').forEach((b) => {
    b.classList.toggle('active', b.dataset.stmt === state.curStmt);
  });
  renderStmtTable(state.curStmt);
});

// ── 设置面板 ──────────────────────────────
const btnOpenSettings = $('btnOpenSettings');
const btnCloseSettings = $('btnCloseSettings');
const settingsOverlay = $('settingsOverlay');
const settingsPanel = $('settingsPanel');
const apiConfigList = $('apiConfigList');
const depList = $('depList');
const btnInstallDeps = $('btnInstallDeps');
const depLog = $('depLog');
// 数据获取设置
const fsMode = $('fsMode');
const fsSpoofing = $('fsSpoofing');
const fsInterval = $('fsInterval');
const fsRetries = $('fsRetries');
const fsTimeout = $('fsTimeout');
const fsTtl = $('fsTtl');
const fsYears = $('fsYears');
const fsIncremental = $('fsIncremental');
const btnSaveFetch = $('btnSaveFetch');
const btnResetLegal = $('btnResetLegal');
// 法律确认
const legalOverlay = $('legalOverlay');
const legalAgree = $('legalAgree');
const btnLegalConfirm = $('btnLegalConfirm');
const btnLegalCancel = $('btnLegalCancel');

function openSettings() {
  settingsOverlay.classList.add('open');
  settingsPanel.classList.add('open');
  loadSettings();
}
function closeSettings() {
  settingsOverlay.classList.remove('open');
  settingsPanel.classList.remove('open');
  loadProviders(); // 刷新模型下拉（key 配置状态可能已变）
}

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    renderApiConfig(data.providers || []);
    renderDeps(data.dependencies || []);
    loadFetchSettings();
    loadRecSettings();
  } catch (e) {
    apiConfigList.innerHTML = '<div class="settings-desc">加载设置失败：' + esc(e.message) + '</div>';
  }
}

function renderApiConfig(providers) {
  apiConfigList.innerHTML = '';
  providers.forEach((p) => {
    const card = document.createElement('div');
    card.className = 'api-card';
    const badge = p.api_key_configured
      ? '<span class="badge ok">已配置</span>'
      : '<span class="badge no">未配置</span>';
    card.innerHTML =
      '<div class="api-card-head">' +
        '<div><div class="api-card-name">' + esc(p.display_name) + '</div>' +
        '<div class="api-card-meta">' + esc(p.base_url) + '</div></div>' +
        badge +
      '</div>' +
      '<div class="api-card-row">' +
        '<input type="password" class="api-key-input" placeholder="' +
          (p.api_key_configured ? '已配置：' + esc(p.api_key_masked) : '请输入 API Key') +
          '" autocomplete="off" spellcheck="false">' +
        '<button class="btn-sm save-key">保存</button>' +
        '<button class="btn-sm ghost clear-key">清除</button>' +
      '</div>';

    card.querySelector('.save-key').addEventListener('click', async () => {
      const input = card.querySelector('.api-key-input');
      const val = input.value.trim();
      if (!val) { input.focus(); return; }
      await saveApiKey(p.name, val);
      input.value = '';
      loadSettings();
    });
    card.querySelector('.clear-key').addEventListener('click', async () => {
      await fetch('/api/settings/' + encodeURIComponent(p.name), { method: 'DELETE' });
      loadSettings();
    });

    apiConfigList.appendChild(card);
  });
}

async function saveApiKey(name, key) {
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: name, api_key: key }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || '保存失败'); }
  } catch (e) {
    alert('保存失败：' + e.message);
  }
}

function renderDeps(packages) {
  depList.innerHTML = '';
  packages.forEach((d) => {
    const div = document.createElement('div');
    div.className = 'dep-item';
    const badge = d.installed
      ? '<span class="badge ok">已安装</span>'
      : '<span class="badge no">缺失</span>';
    const ver = d.installed
      ? '已装 v' + esc(d.version) + ' ｜ 需要 ' + esc(d.required)
      : '需要 ' + esc(d.required);
    div.innerHTML =
      '<div><div class="dep-name">' + esc(d.name) + '</div>' +
      '<div class="dep-version">' + ver + '</div></div>' +
      '<div class="dep-status">' + badge + '</div>';
    depList.appendChild(div);
  });
}

async function installDeps() {
  btnInstallDeps.disabled = true;
  btnInstallDeps.textContent = '⏳ 安装中…';
  depLog.classList.remove('hidden');
  depLog.classList.remove('error');
  depLog.textContent = '正在安装缺失依赖，请稍候…\n';

  try {
    const res = await fetch('/api/install', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await res.json();
    depLog.textContent = data.output || (data.ok ? '安装完成' : '安装失败');
    if (!data.ok) depLog.classList.add('error');
    loadSettings(); // 刷新依赖状态
  } catch (e) {
    depLog.classList.add('error');
    depLog.textContent = '安装请求失败：' + e.message;
  } finally {
    btnInstallDeps.disabled = false;
    btnInstallDeps.textContent = '🛠 一键安装缺失依赖';
  }
}

btnOpenSettings.addEventListener('click', openSettings);
btnCloseSettings.addEventListener('click', closeSettings);
settingsOverlay.addEventListener('click', closeSettings);
btnInstallDeps.addEventListener('click', installDeps);

// ── 数据获取设置 ──────────────────────────
async function loadFetchSettings() {
  try {
    const res = await fetch('/api/fetch-settings');
    const fs = await res.json();
    fsMode.value = fs.mode || 'auto';
    fsSpoofing.checked = !!fs.spoofing;
    fsInterval.value = (fs.min_interval_seconds == null ? 3 : fs.min_interval_seconds);
    fsRetries.value = (fs.max_retries == null ? 2 : fs.max_retries);
    fsTimeout.value = (fs.timeout_seconds == null ? 20 : fs.timeout_seconds);
    fsTtl.value = (fs.cache_ttl_hours == null ? 24 : fs.cache_ttl_hours);
    fsYears.value = (fs.max_years == null ? 7 : fs.max_years);
    fsIncremental.checked = !!fs.incremental;
  } catch (e) {
    /* 忽略加载失败 */
  }
}

async function saveFetchSettings() {
  const body = {
    mode: fsMode.value,
    spoofing: fsSpoofing.checked,
    min_interval_seconds: parseInt(fsInterval.value, 10),
    max_retries: parseInt(fsRetries.value, 10),
    timeout_seconds: parseInt(fsTimeout.value, 10),
    cache_ttl_hours: parseInt(fsTtl.value, 10),
    max_years: parseInt(fsYears.value, 10),
    incremental: fsIncremental.checked,
  };
  try {
    const res = await fetch('/api/fetch-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) {
      const btn = btnSaveFetch;
      const old = btn.textContent;
      btn.textContent = '✅ 已保存';
      setTimeout(() => { btn.textContent = old; }, 1500);
    } else {
      alert(data.error || '保存失败');
    }
  } catch (e) {
    alert('保存失败：' + e.message);
  }
}

btnSaveFetch.addEventListener('click', saveFetchSettings);

// ── 法律与合规确认 ────────────────────────
let _legalResolve = null;

function ensureLegalConsent() {
  if (localStorage.getItem('legal_consent') === '1') return Promise.resolve(true);
  legalAgree.checked = false;
  btnLegalConfirm.disabled = true;
  legalOverlay.classList.remove('hidden');
  return new Promise((resolve) => { _legalResolve = resolve; });
}

function closeLegalModal(ok) {
  legalOverlay.classList.add('hidden');
  if (_legalResolve) { _legalResolve(ok); _legalResolve = null; }
}

btnLegalConfirm.addEventListener('click', () => {
  if (!legalAgree.checked) return;
  localStorage.setItem('legal_consent', '1');
  closeLegalModal(true);
});
btnLegalCancel.addEventListener('click', () => closeLegalModal(false));
legalOverlay.addEventListener('click', (e) => {
  if (e.target === legalOverlay) closeLegalModal(false);
});
legalAgree.addEventListener('change', () => {
  btnLegalConfirm.disabled = !legalAgree.checked;
});
btnResetLegal.addEventListener('click', () => {
  localStorage.removeItem('legal_consent');
  ensureLegalConsent();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (settingsPanel.classList.contains('open')) closeSettings();
    else if (!legalOverlay.classList.contains('hidden')) closeLegalModal(false);
  }
});

// ── 优质公司推荐 ──────────────────────────
const recSort = $('recSort');
const btnRefreshRec = $('btnRefreshRec');
const btnOpenRecSettings = $('btnOpenRecSettings');
const recStatus = $('recStatus');
const recList = $('recList');
// 推荐设置
const recMaxCandidates = $('recMaxCandidates');
const recMinRoe = $('recMinRoe');
const recMinNetMargin = $('recMinNetMargin');
const recMinGrossMargin = $('recMinGrossMargin');
const recMinRevYoy = $('recMinRevYoy');
const recMaxDebt = $('recMaxDebt');
const btnSaveRec = $('btnSaveRec');

function pctInput(v, def) {
  return (v == null ? def : Math.round(v * 100));
}

async function loadRecommendations() {
  const consented = await ensureLegalConsent();
  if (!consented) return;

  btnRefreshRec.disabled = true;
  btnRefreshRec.textContent = '⏳ 获取中…';
  recStatus.innerHTML = '<span class="spinner"></span>正在批量抓取候选公司的财报指标（候选较多时需 1~3 分钟，请耐心等待）…';
  recStatus.className = 'recommend-status loading';

  try {
    const res = await fetch('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const data = await res.json();
    if (!res.ok) {
      recStatus.innerHTML = '<span class="error">' + esc(data.error || '获取失败') + '</span>';
      recStatus.className = 'recommend-status error';
      return;
    }
    state.recResults = data.results || [];
    const st = data.stats || {};
    recStatus.innerHTML = '✅ 共筛查 ' + (st.total_candidates || 0) + ' 家，' +
      (st.matched || 0) + ' 家符合门槛' +
      (st.failed ? '（' + st.failed + ' 家数据获取失败已跳过）' : '');
    recStatus.className = 'recommend-status';
    renderRecList();
  } catch (e) {
    recStatus.innerHTML = '<span class="error">获取推荐失败：' + esc(e.message) + '</span>';
    recStatus.className = 'recommend-status error';
  } finally {
    btnRefreshRec.disabled = false;
    btnRefreshRec.textContent = '🔄 刷新推荐';
  }
}

function sortRecResults(list) {
  const by = recSort.value;
  const sorted = list.slice();
  if (by === 'debt_ratio') {
    sorted.sort((a, b) => {
      const av = a.debt_ratio, bv = b.debt_ratio;
      if (av == null) return 1;
      if (bv == null) return -1;
      return av - bv;
    });
  } else if (by === 'score') {
    sorted.sort((a, b) => (b.score || 0) - (a.score || 0));
  } else {
    sorted.sort((a, b) => (b[by] == null ? -Infinity : b[by]) - (a[by] == null ? -Infinity : a[by]));
  }
  return sorted;
}

function renderRecList() {
  if (!state.recResults.length) {
    recList.innerHTML = '<div class="rec-empty">暂无符合门槛的推荐，可在「门槛」中放宽条件后重试</div>';
    return;
  }
  const list = sortRecResults(state.recResults);
  recList.innerHTML = list.map((r) => {
    return '<div class="rec-card" data-name="' + esc(r.name) + '">' +
      '<div class="rec-card-head">' +
        '<div class="rec-name">' + esc(r.name) +
          '<span class="rec-code">' + esc(r.security_code || r.code) + '</span></div>' +
        '<div class="rec-score">' + (r.score != null ? r.score.toFixed(1) : '—') + '<span>分</span></div>' +
      '</div>' +
      '<div class="rec-metrics">' +
        '<div><label>ROE</label><b>' + fmtPct(r.roe) + '</b></div>' +
        '<div><label>净利率</label><b>' + fmtPct(r.net_margin) + '</b></div>' +
        '<div><label>毛利率</label><b>' + fmtPct(r.gross_margin) + '</b></div>' +
        '<div><label>营收增速</label><b>' + fmtPct(r.revenue_yoy) + '</b></div>' +
        '<div><label>资产负债率</label><b>' + fmtPct(r.debt_ratio) + '</b></div>' +
      '</div>' +
      '<div class="rec-adv">💡 ' + esc(r.advantage || '') + '</div>' +
    '</div>';
  }).join('');
}

recSort.addEventListener('change', renderRecList);
btnRefreshRec.addEventListener('click', loadRecommendations);
btnOpenRecSettings.addEventListener('click', () => {
  openSettings();
  // 延迟滚动到推荐设置区块
  setTimeout(() => {
    const el = $('btnSaveRec');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 300);
});
recList.addEventListener('click', (e) => {
  const card = e.target.closest('.rec-card');
  if (!card || !card.dataset.name) return;
  companyInput.value = card.dataset.name;
  doSearch();
});

async function loadRecSettings() {
  try {
    const res = await fetch('/api/recommend-settings');
    const s = await res.json();
    recMaxCandidates.value = s.max_candidates == null ? 15 : s.max_candidates;
    const th = s.thresholds || {};
    recMinRoe.value = pctInput(th.min_roe, 12);
    recMinNetMargin.value = pctInput(th.min_net_margin, 6);
    recMinGrossMargin.value = pctInput(th.min_gross_margin, 20);
    recMinRevYoy.value = pctInput(th.min_revenue_yoy, -5);
    recMaxDebt.value = pctInput(th.max_debt_ratio, 70);
  } catch (e) { /* 忽略加载失败 */ }
}

async function saveRecSettings() {
  const body = {
    max_candidates: parseInt(recMaxCandidates.value, 10),
    thresholds: {
      min_roe: (parseFloat(recMinRoe.value) || 0) / 100,
      min_net_margin: (parseFloat(recMinNetMargin.value) || 0) / 100,
      min_gross_margin: (parseFloat(recMinGrossMargin.value) || 0) / 100,
      min_revenue_yoy: (parseFloat(recMinRevYoy.value) || 0) / 100,
      max_debt_ratio: (parseFloat(recMaxDebt.value) || 100) / 100,
    },
  };
  try {
    const res = await fetch('/api/recommend-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) {
      const btn = btnSaveRec;
      const old = btn.textContent;
      btn.textContent = '✅ 已保存';
      setTimeout(() => { btn.textContent = old; }, 1500);
    } else {
      alert(data.error || '保存失败');
    }
  } catch (e) {
    alert('保存失败：' + e.message);
  }
}
btnSaveRec.addEventListener('click', saveRecSettings);

// ── 历史记录 ──────────────────────────────
const btnOpenHistory = $('btnOpenHistory');
const btnCloseHistory = $('btnCloseHistory');
const historyOverlay = $('historyOverlay');
const historyPanel = $('historyPanel');
const historyList = $('historyList');
const btnClearHistory = $('btnClearHistory');

function openHistory() {
  historyOverlay.classList.add('open');
  historyPanel.classList.add('open');
  loadHistory();
}
function closeHistory() {
  historyOverlay.classList.remove('open');
  historyPanel.classList.remove('open');
}

async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    renderHistory(data.entries || []);
  } catch (e) {
    historyList.innerHTML = '<div class="settings-desc">加载历史失败：' + esc(e.message) + '</div>';
  }
}

function renderHistory(entries) {
  if (!entries || !entries.length) {
    historyList.innerHTML = '<div class="settings-desc">暂无历史记录。</div>';
    return;
  }
  historyList.innerHTML = entries.map((en) => {
    const latest = en.indicators && en.indicators.latest;
    const rev = latest && latest.revenue != null ? fmtYi(latest.revenue) : '—';
    const roe = latest && latest.roe != null ? fmtPct(latest.roe) : '—';
    return '<div class="history-item" data-id="' + esc(en.id) + '">' +
      '<div class="history-head">' +
        '<div class="history-name">' + esc(en.name) +
          ' <span class="history-code">' + esc(en.code) + '</span></div>' +
        '<div class="history-time">' + esc(en.saved_at || '') + '</div>' +
      '</div>' +
      '<div class="history-sub">' + esc(en.provider + ' / ' + en.model) +
        ' ｜ 营收 ' + rev + ' ｜ ROE ' + roe + '</div>' +
      '<div class="history-actions">' +
        '<button class="btn-sm history-view">查看</button>' +
        '<button class="btn-sm ghost history-del">删除</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

historyList.addEventListener('click', async (e) => {
  const item = e.target.closest('.history-item');
  if (!item) return;
  const id = item.dataset.id;
  if (e.target.classList.contains('history-del')) {
    await fetch('/api/history/' + encodeURIComponent(id), { method: 'DELETE' });
    loadHistory();
  } else if (e.target.classList.contains('history-view')) {
    const res = await fetch('/api/history');
    const data = await res.json();
    const entry = (data.entries || []).find((x) => x.id === id);
    if (entry) {
      renderResults(entry);
      closeHistory();
    }
  }
});

btnClearHistory.addEventListener('click', async () => {
  if (!confirm('确定清空全部历史记录？')) return;
  await fetch('/api/history', { method: 'DELETE' });
  loadHistory();
});

btnOpenHistory.addEventListener('click', openHistory);
btnCloseHistory.addEventListener('click', closeHistory);
historyOverlay.addEventListener('click', closeHistory);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && historyPanel.classList.contains('open')) closeHistory();
});

function maybeAutoLoadRecommendations() {
  if (localStorage.getItem('legal_consent') === '1') {
    loadRecommendations();
  } else {
    recStatus.textContent = '点击「刷新推荐」获取优质公司榜单（首次会弹出法律合规确认）';
    recStatus.className = 'recommend-status';
    recList.innerHTML = '<div class="rec-empty">点击右上角「🔄 刷新推荐」查看优质公司推荐</div>';
  }
}

// ── 启动 ──────────────────────────────────
loadProviders();
maybeAutoLoadRecommendations();
