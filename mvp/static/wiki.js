/* PaiLei PDF Wiki 前端: prepare(SSE 进度) → 浏览(左章节/右MD) */
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

let es = null, finished = false, currentMeta = null;

function prepare() {
  const code = $('code').value.trim();
  const year = $('year').value.trim();
  if (!code || !year) return;
  if (es) es.close();
  finished = false;
  resetSteps();
  $('dl-bar').style.width = '0%';
  setMsg('准备中…');
  $('wiki-view').classList.remove('ready');
  $('prepare-section').style.display = 'block';
  es = new EventSource(`/api/wiki/prepare?code=${encodeURIComponent(code)}&year=${encodeURIComponent(year)}`);
  es.addEventListener('progress', e => onProgress(JSON.parse(e.data)));
  es.addEventListener('fatal', e => { setMsg('错误: ' + JSON.parse(e.data).message, true); if (es) es.close(); });
  es.onerror = () => { if (finished && es) es.close(); };
}

function onProgress(d) {
  const stage = d.stage;
  if (stage === 'step') {
    const m = d.meta || {};
    if (m.step && m.status) updateStep(m.step, m.status, d.message);
    setMsg(d.message);
  } else if (stage === 'download_progress') {
    const pct = (d.meta && d.meta.pct) || 0;
    $('dl-bar').style.width = pct + '%';
    setMsg('下载中: ' + d.message);
  } else if (stage === 'error') {
    setMsg(d.message, true);
  } else if (stage === 'done' || stage === 'cache') {
    finished = true;
    if (es) es.close();
    if (stage === 'done') { $('dl-bar').style.width = '100%'; loadIndex(); }
    if (d.meta) showView(d.meta);
  }
}

function resetSteps() {
  document.querySelectorAll('.step').forEach(el => {
    el.classList.remove('active', 'done');
    el.querySelector('.step-icon').textContent = '○';
    el.querySelector('.step-detail').textContent = '';
  });
}
function updateStep(step, status, msg) {
  const el = document.querySelector(`.step[data-step="${step}"]`);
  if (!el) return;
  el.classList.remove('active', 'done');
  el.classList.add(status);
  el.querySelector('.step-icon').textContent = status === 'done' ? '✓' : (status === 'active' ? '⏳' : '○');
  if (msg) el.querySelector('.step-detail').textContent = msg;
}
function setMsg(msg, isErr) {
  const el = $('progress-msg');
  el.textContent = msg;
  el.classList.toggle('err', !!isErr);
}

function showView(meta) {
  currentMeta = meta;
  $('prepare-section').style.display = 'none';
  $('wiki-list').style.display = 'none';
  $('wiki-view').classList.add('ready');
  $('doc-meta').innerHTML =
    `<strong>${esc(meta.company)}</strong><br>${meta.code} · ${meta.year} 年年度报告 · ` +
    `${meta.char_count} 字 / ${meta.page_count || '?'} 页 · 披露 ${meta.publish_date || '?'} · ` +
    `解析 ${meta.parse_seconds || '?'}s`;

  let nav = '<h3>导航</h3>';
  nav += `<a data-target="full" class="active">📄 全文 full.md</a>`;
  if (meta.sections && meta.sections.length) {
    nav += '<h3>章节(切分)</h3>';
    meta.sections.forEach(s => {
      const label = s.id.replace(/^\d+_/, '');
      nav += `<a data-target="${s.id}">${esc(label)} · ${esc(s.title)} (${s.char_count}字)</a>`;
    });
  } else {
    nav += '<a style="color:#777;cursor:default">章节切分未成功, 仅全文</a>';
  }
  $('sidebar').innerHTML = nav;
  document.querySelectorAll('.wiki-sidebar a[data-target]').forEach(a => {
    a.addEventListener('click', () => {
      document.querySelectorAll('.wiki-sidebar a').forEach(x => x.classList.remove('active'));
      a.classList.add('active');
      loadDoc(a.dataset.target);
    });
  });
  loadDoc('full');
}

async function loadIndex() {
  try {
    const r = await fetch('/api/wiki/index');
    const list = await r.json();
    renderIndexCards(list);
  } catch (e) {
    $('wiki-cards').innerHTML = '<div class="wiki-empty">列表加载失败</div>';
  }
}
function renderIndexCards(list) {
  const box = $('wiki-cards');
  if (!list || !list.length) {
    box.innerHTML = '<div class="wiki-empty">还没有沉淀的 wiki。输入代码 + 年份点「沉淀 / 加载」开始。</div>';
    return;
  }
  box.innerHTML = list.map(it => {
    const name = (it.company || '').replace(/\d{4}年年度报告/, '').trim() || it.code;
    return `<div class="wiki-card" data-code="${esc(it.code)}" data-year="${it.year}">
      <div class="wc-company">${esc(name)}</div>
      <div class="wc-meta">${esc(it.code)} · ${it.year} 年报</div>
      <div class="wc-stat">${it.char_count || '?'} 字 / ${it.page_count || '?'} 页</div>
    </div>`;
  }).join('');
  box.querySelectorAll('.wiki-card').forEach(c => {
    c.addEventListener('click', () => openWiki(c.dataset.code, parseInt(c.dataset.year)));
  });
}
async function openWiki(code, year) {
  const r = await fetch(`/api/wiki/${code}/${year}/meta`);
  if (!r.ok) { setMsg('该 wiki 的 meta 读取失败 (HTTP ' + r.status + ')', true); return; }
  const meta = await r.json();
  showView(meta);
}
function showList() {
  if (es) es.close();
  finished = true;
  $('wiki-view').classList.remove('ready');
  $('prepare-section').style.display = 'block';
  $('wiki-list').style.display = 'block';
  window.scrollTo({ top: 0 });
  resetSteps();
  $('dl-bar').style.width = '0%';
  setMsg('选择上方卡片进入明细, 或输入新代码沉淀。');
  loadIndex();
}

async function loadDoc(target) {
  $('md-content').textContent = '加载中…';
  const { code, year } = currentMeta;
  const url = target === 'full'
    ? `/api/wiki/${code}/${year}/md`
    : `/api/wiki/${code}/${year}/section/${target}`;
  try {
    const r = await fetch(url);
    if (!r.ok) { $('md-content').innerHTML = `<p>加载失败 (HTTP ${r.status})</p>`; return; }
    const md = await r.text();
    let display = md, truncated = false;
    if (target === 'full' && md.length > 80000) {
      display = md.slice(0, 80000);
      truncated = true;
    }
    $('md-content').innerHTML = renderMd(display) +
      (truncated ? `<p style="color:var(--ink-dim);margin-top:28px;border-top:1px solid var(--rule);padding-top:14px">… 全文 ${md.length} 字, 已渲染前 8 万字(浏览器性能限制)。完整内容见本地 <code>wiki/${code}/${year}/full.md</code></p>` : '');
  } catch (e) {
    $('md-content').innerHTML = `<p>加载失败: ${esc(e)}</p>`;
  }
}

function renderMd(md) {
  let h = esc(md);
  // 表格(先处理, 整块转)
  h = h.replace(/(?:^\|.+\|\n?)+/gm, block => {
    const lines = block.trim().split('\n').filter(l => l.trim());
    if (lines.length < 2 || !/^\|[\s:|-]+\|$/.test(lines[1].trim())) return block;
    const cells = l => l.trim().replace(/^\||\|$/g, '').split('|').map(s => s.trim());
    const header = cells(lines[0]);
    const rows = lines.slice(2).map(cells);
    let t = '<table><thead><tr>' + header.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>';
    t += rows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('');
    return t + '</tbody></table>';
  });
  h = h.replace(/^#{1,2} (.+)$/gm, '<h2>$1</h2>');
  h = h.replace(/^#{3,4} (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/^#{5,6} (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  h = h.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(?:<li>.*<\/li>\n?)+/g, m => '<ul>' + m.replace(/\n/g, '') + '</ul>');
  h = h.split(/\n\n+/).map(p => {
    p = p.trim();
    if (!p) return '';
    if (/^<(h\d|ul|table)/.test(p)) return p;
    return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
  }).join('\n');
  return h;
}

document.addEventListener('DOMContentLoaded', () => {
  $('prepare-btn').addEventListener('click', prepare);
  ['code', 'year'].forEach(id => $(id).addEventListener('keydown', e => { if (e.key === 'Enter') prepare(); }));
  $('back-to-list').addEventListener('click', showList);
  loadIndex();
});
