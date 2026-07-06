/* PaiLei 排雷 MVP · 前端: EventSource 接 SSE, Card 流式渲染 */
const $ = id => document.getElementById(id);
const show = el => el.classList.remove('hidden');
const hide = el => el.classList.add('hidden');
const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const FIELD_LABELS = {
  year: '年份', monetary_funds: '货币资金', short_loan: '短期借款', long_loan: '长期借款',
  accounts_rece: '应收账款', goodwill: '商誉', total_equity: '净资产', total_assets: '总资产',
  opinion: '审计意见', operate_income: '营业收入', parent_netprofit: '归母净利润',
  netprofit: '净利润', netcash_operate: '经营现金流', interest_debt: '有息负债',
  income_yoy: '营收增速', receivable_yoy: '应收增速', gap_pp: '背离', gap: '差额',
  ratio_pct: '占比', changed: '变化', turn_nonstd: '转非标',
};
const fieldLabel = k => FIELD_LABELS[k] || k;

function go(screen) {
  ['screen-input', 'screen-report'].forEach(id => {
    const el = $(id);
    if (id === screen) show(el); else hide(el);
  });
  window.scrollTo({ top: 0 });
}

let es = null;
let finished = false;
function start(code) {
  if (es) es.close();
  finished = false;
  $('cards').innerHTML = '';
  $('report-brand').textContent = `正在排雷: ${code} …`;
  go('screen-report');
  es = new EventSource(`/api/analyze?code=${encodeURIComponent(code)}`);
  es.addEventListener('card_start', e => onCardStart(JSON.parse(e.data)));
  es.addEventListener('card_data', e => onCardData(JSON.parse(e.data)));
  es.addEventListener('card_done', e => onCardDone(JSON.parse(e.data)));
  es.addEventListener('analysis_chunk', e => onAnalysisChunk(JSON.parse(e.data)));
  es.addEventListener('analysis_done', e => onAnalysisDone(JSON.parse(e.data)));
  es.addEventListener('fatal', e => onFatal(JSON.parse(e.data)));
  es.addEventListener('deep_hint', e => onDeepHint(JSON.parse(e.data)));
  es.onerror = () => { if (finished && es) es.close(); };
}

const cardEls = {};

function onCardStart(d) {
  const el = document.createElement('div');
  el.className = `card fetching layer-${d.layer}`;
  el.dataset.id = d.cardId;
  el.innerHTML = `
    <div class="card-head">
      <span class="layer-tag">${layerLabel(d.layer)}</span>
      <span class="card-title">${esc(d.title)}</span>
      <span class="card-status"><span class="spinner"></span>获取中</span>
    </div>
    <div class="card-body"></div>`;
  $('cards').appendChild(el);
  cardEls[d.cardId] = el;
  if (d.cardId === 'analysis') {
    el.querySelector('.card-body').innerHTML =
      '<div class="analysis-placeholder">🤔 大模型分析中，首字约 2-3 秒，完整生成约 20-30 秒，请稍候…</div>';
  }
}

function onCardData(d) {
  const el = cardEls[d.cardId];
  if (!el) return;
  el.querySelector('.card-body').innerHTML = renderBody(d.cardId, d.payload);
}

function onCardDone(d) {
  const el = cardEls[d.cardId];
  if (!el) return;
  el.classList.remove('fetching');
  el.classList.add('done');
  if (d.flag) el.classList.add('flag-' + d.flag);
  const status = el.querySelector('.card-status');
  if (d.flag === 'hit') status.innerHTML = '<span class="flag-pill flag-hit">命中</span>';
  else if (d.flag === 'miss') status.innerHTML = '<span class="flag-pill flag-miss">未命中</span>';
  else if (d.flag === 'nodata') status.innerHTML = '<span class="flag-pill flag-nodata">数据不可得</span>';
  else status.innerHTML = '✓ 完成';
  if (d.summary) {
    const body = el.querySelector('.card-body');
    const sm = document.createElement('div');
    sm.className = 'card-summary';
    sm.textContent = d.summary;
    body.insertBefore(sm, body.firstChild);
  }
}

function onAnalysisChunk(d) {
  const el = cardEls['analysis'];
  if (!el) return;
  const body = el.querySelector('.card-body');
  if (!body.dataset.started) {
    body.className = 'card-body analysis-body';
    body.dataset.md = '';
    body.dataset.started = '1';
  }
  body.dataset.md = (body.dataset.md || '') + d.text;
  body.innerHTML = renderMd(body.dataset.md) + '<span class="cursor"></span>';
}

function onAnalysisDone(d) {
  const el = cardEls['analysis'];
  if (!el) return;
  el.classList.remove('fetching');
  el.classList.add('done');
  const body = el.querySelector('.card-body');
  if (body.dataset.md) body.innerHTML = renderMd(body.dataset.md);
  el.querySelector('.card-status').innerHTML = '✓ 分析完成';
  finished = true;
  // 不立即 close es: deep_hint 事件紧随 analysis_done, 提前关闭会丢失它; 由 onDeepHint / onerror 关闭
}

function onFatal(d) {
  const el = document.createElement('div');
  el.className = 'fatal';
  el.textContent = d.message;
  $('cards').appendChild(el);
  finished = true;
  if (es) es.close();
}

function onDeepHint(d) {
  const el = document.createElement('div');
  el.className = 'card layer-deep deep-hint-card';
  el.innerHTML = `
    <div class="card-head">
      <span class="layer-tag">深度</span>
      <span class="card-title">深度排雷（读年报附注）</span>
    </div>
    <div class="card-body">
      <div class="deep-hint-msg">初分完成。要深度排雷吗？读 <b>${esc(d.name || '')} ${esc(d.code)}</b> 的年报附注（关联交易 / 会计政策变更 / 审计措辞 / 商誉承诺 / 或有负债），约 2 分钟。${d.has_wiki ? '✅ ' + d.year + ' wiki 已沉淀, 秒过。' : '⏳ 首次需下载解析 PDF。'}</div>
      <div class="deep-year-row">
        <label>年份</label>
        <input id="deep-year" type="text" value="${d.year}" inputmode="numeric" autocomplete="off">
        <button class="deep-btn" id="deep-start-btn">📄 开始深度排雷</button>
      </div>
      <div class="deep-hint-tip">默认最新年（${d.year}）。测暴雷期可改：康美 2018、康得新 002450 2018、獐子岛 002069 等。</div>
    </div>`;
  $('cards').appendChild(el);
  if (es) es.close();
  el.querySelector('#deep-start-btn').addEventListener('click', () => {
    const y = parseInt((el.querySelector('#deep-year').value || '').trim()) || d.year;
    el.querySelector('.card-body').innerHTML = `<div class="deep-hint-msg">深度排雷（${esc(d.code)} ${y}）进行中, 见下方卡片 ↓</div>`;
    startDeep(d.code, y);
  });
}

let esDeep = null;
function startDeep(code, year) {
  if (esDeep) esDeep.close();
  esDeep = new EventSource(`/api/agent/analyze?code=${encodeURIComponent(code)}&year=${encodeURIComponent(year)}`);
  esDeep.addEventListener('card_start', e => onCardStart(JSON.parse(e.data)));
  esDeep.addEventListener('card_data', e => onCardData(JSON.parse(e.data)));
  esDeep.addEventListener('card_done', e => onCardDone(JSON.parse(e.data)));
  esDeep.addEventListener('deep_progress', e => onDeepProgress(JSON.parse(e.data)));
  esDeep.addEventListener('fatal', e => onFatal(JSON.parse(e.data)));
  esDeep.onerror = () => { if (esDeep) esDeep.close(); };
}

function onDeepProgress(d) {
  const el = cardEls[d.cardId];
  if (!el) return;
  const m = d.meta || {};
  let txt = d.message || '';
  if (d.stage === 'download_progress' && m.pct != null) txt = `下载 ${m.pct}% (${m.downloaded ? Math.round(m.downloaded/1024) : 0} KB)`;
  else if (d.stage === 'step') txt = `[${m.step || ''}] ${d.message}`;
  const body = el.querySelector('.card-body');
  if (body) body.innerHTML = `<div class="deep-prog">${esc(txt)}</div>`;
}

function layerLabel(layer) {
  return { data: '数据', rule: '规则', summary: '汇总', analysis: 'AI 分析', deep: '深度' }[layer] || layer;
}

function renderBody(cardId, p) {
  switch (cardId) {
    case 'overview': return renderOverview(p);
    case 'balance': return renderTable(p, ['year', 'monetary_funds', 'short_loan', 'accounts_rece', 'goodwill', 'total_equity', 'total_assets', 'opinion']);
    case 'profit': return renderTable(p, ['year', 'operate_income', 'parent_netprofit']);
    case 'cashflow': return renderTable(p, ['year', 'netcash_operate']);
    case 'summary': return renderSummary(p);
    case 'deep_result': return `<div class="deep-result">${esc(p.msg || '')}</div>`;
    case 'deep_number': return renderDeepNumber(p);
    case 'deep_notes': return renderDeepNotes(p);
    default:
      if (p && p.id) return renderRule(p);
      return '';
  }
}

function renderOverview(p) {
  const v = (x, u = '亿') => (x == null ? '—' : x.toFixed(2) + u);
  return `<div class="overview-grid">
    <div class="item"><div class="k">公司</div><div class="v">${esc(p.name)}</div></div>
    <div class="item"><div class="k">代码</div><div class="v" style="font-size:14px">${esc(p.code)}</div></div>
    <div class="item"><div class="k">最新报告期</div><div class="v" style="font-size:14px">${esc(p.latest_report)}</div></div>
    <div class="item"><div class="k">总资产</div><div class="v">${v(p.total_assets)}</div></div>
    <div class="item"><div class="k">净资产</div><div class="v">${v(p.total_equity)}</div></div>
    <div class="item"><div class="k">年报数</div><div class="v">${p.report_count}</div></div>
  </div>`;
}

function renderTable(rows, cols) {
  if (!rows || !rows.length) return '<div class="card-summary">无数据</div>';
  const head = cols.map(c => `<th>${fieldLabel(c)}</th>`).join('');
  const body = rows.map(r => {
    const hit = r.hit === true;
    return `<tr class="${hit ? 'hit-row' : ''}">${cols.map(c => `<td class="${c === 'opinion' ? 'opinion' : ''}">${cellVal(c, r[c])}</td>`).join('')}</tr>`;
  }).join('');
  return `<table class="fin"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function cellVal(col, v) {
  if (col === 'year') return v;
  if (col === 'opinion') return esc(v || '—');
  if (v === null || v === undefined) return '—';
  const n = typeof v === 'number' ? v.toFixed(2) : v;
  return `<span class="${typeof v === 'number' && v < 0 ? 'neg' : ''}">${n}</span>`;
}

function renderRule(p) {
  if (!p.yearly || !p.yearly.length) return '';
  const rows = p.yearly.map(y => {
    const cls = y.hit ? 'yr hit' : 'yr';
    const vals = Object.entries(y)
      .filter(([k]) => !['hit', 'year'].includes(k))
      .map(([k, v]) => `${fieldLabel(k)}: ${ruleVal(v)}`).join(' · ');
    return `<div class="${cls}"><span class="y">${y.year}</span>${y.hit ? '🔴 ' : '⚪ '}${vals}</div>`;
  }).join('');
  return `<div class="rule-yearly">${rows}</div>`;
}

function ruleVal(v) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? '是' : '否';
  if (typeof v === 'number') {
    const cls = v < 0 ? 'neg' : '';
    const txt = Math.abs(v) < 1000 ? v : v.toFixed(2) + '亿';
    return `<span class="${cls}">${txt}</span>`;
  }
  return esc(v);
}

function renderSummary(p) {
  return `<div class="summary-grid">
    <div class="s"><span class="n hit">${p.hit}</span><span class="l">命中</span></div>
    <div class="s"><span class="n miss">${p.miss}</span><span class="l">未命中</span></div>
    <div class="s"><span class="n nodata">${p.nodata}</span><span class="l">数据不可得</span></div>
    <div class="s"><span class="n" style="color:var(--ink)">${p.total}</span><span class="l">总规则</span></div>
  </div>`;
}

function renderDeepNumber(p) {
  let h = '';
  if (p.rule_results && p.rule_results.length) {
    h += '<div class="deep-sub">📊 规则层（akshare, 同初分）</div>';
    h += p.rule_results.map(r => {
      const cls = r.hit === true ? 'hit' : '';
      const flag = r.hit === true ? '🔴 命中' : (r.hit === null ? '⚫ 不可得' : '⚪ 未命中');
      return `<div class="deep-row ${cls}"><span class="dr-name">${esc(r.title)}</span><span class="dr-flag">${flag}</span><span class="dr-sum">${esc(r.summary || '')}</span></div>`;
    }).join('');
  }
  if (p.cross_diffs && p.cross_diffs.length) {
    h += '<div class="deep-sub warn">⚠️ wiki vs akshare 交叉差异（>5%）</div>';
    h += '<div style="font-size:11px;color:var(--ink-faint);margin-bottom:6px">wiki 数字提取为实验性(markitdown 表格解析), 差异可能是提取误差, 以 akshare 为准</div>';
    h += p.cross_diffs.map(d => `<div class="deep-row cross">${esc(d['科目'] || '')}: akshare ${d.akshare_亿}亿 / wiki ${d.wiki_亿}亿（差 ${d.差异率}）</div>`).join('');
  } else if (p.wiki_numbers && Object.keys(p.wiki_numbers).length) {
    h += '<div class="deep-sub ok">✅ wiki 与 akshare 关键数字基本一致</div>';
  }
  return h || '<div class="deep-result">无数据</div>';
}

function renderDeepNotes(p) {
  const fs = p.findings || [];
  if (!fs.length) return '<div class="deep-result">无附注分析</div>';
  return fs.map(f => {
    const sev = f.severity || 'info';
    const hitTxt = f.hit === true ? '🔴 命中' : (f.hit === false ? '⚪ 未命中' : (f.hit === 'unknown' ? '❓ 信息不足' : '⚫ 跳过'));
    return `<div class="finding ${sev} ${f.hit === true ? 'hit' : ''}">
      <div class="f-head"><span class="f-sev ${sev}">${sev}</span><b>${esc(f.title)}</b><span class="f-hit">${hitTxt}</span></div>
      <div class="f-sum">${esc(f.summary || '')}</div>
      ${f.evidence ? `<details class="f-ev"><summary>原文引用${f.section_ref ? ' · ' + esc(f.section_ref) : ''}</summary><pre>${esc(f.evidence)}</pre></details>` : ''}
    </div>`;
  }).join('');
}

function renderMd(md) {
  let h = esc(md);
  h = h.replace(/^###? (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(?:<li>.*<\/li>\n?)+/g, m => '<ul>' + m.replace(/\n/g, '') + '</ul>');
  h = h.split(/\n\n+/).map(p => {
    p = p.trim();
    if (!p) return '';
    if (/^<(h\d|ul|p)/.test(p)) return p;
    return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
  }).join('');
  return h;
}

document.addEventListener('DOMContentLoaded', () => {
  $('start-btn').addEventListener('click', () => start($('code-input').value.trim()));
  $('code-input').addEventListener('keydown', e => { if (e.key === 'Enter') start($('code-input').value.trim()); });
  document.querySelectorAll('.case-pick').forEach(b => b.addEventListener('click', () => {
    $('code-input').value = b.dataset.code;
    start(b.dataset.code);
  }));
  $('back-btn').addEventListener('click', () => { if (es) es.close(); go('screen-input'); });
});
