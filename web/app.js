const APP_BUILD = '2026-08-20f';
console.log('[NIMBY toolkit] app.js build', APP_BUILD, document.querySelector('script[src*="app.js"]')?.src || '');
const state = { bootstrap: null, analysis: null, cleanup: null, cleanMode: 'automatic', taskAction: null, plan: null };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const viewMeta = {
  dashboard: ['CONTROL CENTER', '铁路运营总览'], analytics: ['OPERATIONS ANALYTICS', '运营分析'], map: ['TRANSIT MAP', '线路图'], realnet: ['REAL-WORLD REFERENCE', '现实路网参考图'], timetable: ['TIMETABLE STUDIO', '时刻表配置'],
  extensions: ['DEPOT CONTROL', '车库接班管理'], vehicle: ['ROLLING STOCK WORKSHOP', '车辆工坊'], scripts: ['SCRIPT WORKSHOP', 'NimbyScript 规则生成器'], history: ['FLEET HISTORY', '历史与性能'], cleanup: ['STORAGE CARE', '副本清理中心'], roadmap: ['CAPABILITY LADDER', '开发路线']
};
const SVG_NS = 'http://www.w3.org/2000/svg';
function lineColor(raw) {
  if (!raw) return '#8a9ba4';
  let hex = String(raw).replace(/^0x/i, '').replace(/^#/, '');
  if (hex.length === 8) hex = hex.slice(2);
  return /^[0-9a-fA-F]{6}$/.test(hex) ? `#${hex}` : '#8a9ba4';
}
function secToClock(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.round(seconds) % 86400; const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
function minutesText(seconds) { return (seconds === null || seconds === undefined) ? '—' : `${(seconds / 60).toFixed(1)} 分`; }
const RISK_LABELS = { critical: '严重', warning: '提醒', info: '注意', good: '健康' };

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}
function toast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.className = `toast${error ? ' error' : ''}`; el.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, 5500);
}
async function api(path, options = {}) {
  const { timeoutMs = 20000, ...rest } = options;
  let controller, timer;
  if (typeof AbortController !== 'undefined') { controller = new AbortController(); timer = setTimeout(() => controller.abort(), timeoutMs); }
  try {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, cache: 'no-store', signal: controller && controller.signal, ...rest });
    const data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || '操作失败'); return data;
  } finally { if (timer) clearTimeout(timer); }
}
function switchView(name) {
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === name));
  $$('.view').forEach(el => el.classList.toggle('active', el.id === `view-${name}`));
  $('#view-eyebrow').textContent = viewMeta[name][0]; $('#view-title').textContent = viewMeta[name][1];
  if (name === 'realnet') initRealnet();
}
function setOptions(select, files) {
  select.innerHTML = files.map((file, index) => `<option value="${escapeHtml(file.path)}" ${index === 0 ? 'selected' : ''}>${escapeHtml(file.name)} · ${formatBytes(file.size)}</option>`).join('');
}
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function escapeHtml(value = '') { return String(value).replace(/[&<>"']/g, ch => HTML_ESCAPES[ch]); }
function timestamp() { const d = new Date(); return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}_${String(d.getHours()).padStart(2,'0')}${String(d.getMinutes()).padStart(2,'0')}${String(d.getSeconds()).padStart(2,'0')}`; }
function outputPath(kind) {
  const save = $('#save-select').value; const slash = Math.max(save.lastIndexOf('\\'), save.lastIndexOf('/'));
  const dir = save.slice(0, slash + 1); const base = save.slice(slash + 1).replace(/\.nimbyrails5$/i, '');
  return `${dir}${base}_${kind}_${timestamp()}.nimbyrails5`;
}
function refreshOutputNames() { $('#migration-output').value = outputPath('Toolkit'); $('#extension-output').value = outputPath('Extension'); $('#fix-output').value = outputPath('Repair'); const rec = $('#recover-output'); if (rec) rec.value = outputPath('Recovery'); }

function setCompareOptions(exports) {
  const options = exports.map(f => `<option value="${escapeHtml(f.path)}">${escapeHtml(f.name)}</option>`).join('');
  ['#compare-before', '#netdiff-before', '#compare-after', '#netdiff-after'].forEach(sel => { const el = $(sel); if (el) el.innerHTML = options; });
  if (exports.length > 1) {
    ['#compare-after', '#netdiff-after'].forEach(sel => { const el = $(sel); if (el) el.selectedIndex = 0; });
    ['#compare-before', '#netdiff-before'].forEach(sel => { const el = $(sel); if (el) el.selectedIndex = 1; });
  }
}
async function loadBootstrap() {
  const data = await api('/api/bootstrap'); state.bootstrap = data;
  setOptions($('#save-select'), data.files.saves); setOptions($('#export-select'), data.files.exports); setCompareOptions(data.files.exports); refreshOutputNames();
  $('#cleanup-enabled').checked = data.settings.enabled; $('#cleanup-days').value = data.settings.days; $('#cleanup-keep').value = data.settings.keep;
  state.cleanup = data.cleanup; renderCleanup(); renderRoadmap(data.capabilities);
  if (data.startup_cleanup?.error) toast(`启动清理未完成：${data.startup_cleanup.error}`, true);
  else if (data.startup_cleanup?.result?.moved_file_count) toast(`启动清理已将 ${data.startup_cleanup.result.moved_group_count} 组过期副本移入回收站`);
}
function renderAnalysis(a) {
  state.analysis = a;
  const matched = a.compatible_schedule_count === a.expected_schedule_count && a.located_train_count === a.train_count;
  const gv = a.game_version || {};
  const gvClass = { supported: 'ok', compatible: 'ok', newer: 'warn', unknown: 'warn', outdated: 'bad' }[gv.status] || 'ok';
  const gvChip = gv.model_version != null ? `<span class="ver-chip ${gvClass}" title="${escapeHtml(gv.note || '')}">游戏版本 model ${gv.model_version} · ${({supported:'已适配',compatible:'兼容',newer:'更新版',unknown:'未知',outdated:'过旧'}[gv.status] || gv.status)}</span>` : '';
  $('#health-summary').innerHTML = `<div class="health-wrap"><div class="health-ring" style="--score:${a.health_score}"><div><b>${a.health_score}</b><small>/ 100</small></div></div><div class="health-copy"><strong>${matched ? '文件完全匹配' : '文件不匹配'}</strong><p>${a.compatible_schedule_count}/${a.expected_schedule_count} 张时刻表<br>${a.located_train_count}/${a.train_count} 列车已核对</p>${gvChip}</div></div>`;
  state.gameVersion = gv;
  if (gv.status === 'newer' || gv.status === 'unknown' || gv.status === 'outdated') toast(gv.note, gv.status !== 'newer');
  const metrics = [
    ['时刻表', a.schedule_count, '张'], ['列车', a.train_count, '列'], ['严重问题', a.severity_counts.critical, '项'], ['车库扩展', a.garage_enabled_total, '列车']
  ];
  $('#metric-grid').innerHTML = metrics.map(x => `<div class="metric-card"><small>${x[0]}</small><b>${x[1]}</b><em>${x[2]}</em></div>`).join(''); $('#metric-grid').hidden = false;
  $('#finding-count').textContent = a.findings.length; $('#findings-panel').hidden = false;
  $('#finding-list').innerHTML = renderFindingGroups(a.findings);
  renderPairs(a.suggested_pairs || []); renderSchedules(a.health_schedules || []); renderRepairTasks(a);
  renderAnalytics(a); renderRecoverTargets(a);
  toast(matched ? `体检完成：${a.expected_schedule_count} 张表与 ${a.train_count} 列车全部匹配` : '体检发现文件不匹配，请重新选择同一存档导出的 JSON', !matched);
}
function renderAnalytics(a) {
  const an = a.analytics; if (!an) return;
  const kpi = [
    ['时刻表', a.schedule_count, '张'], ['班次', an.total_shifts, '个'], ['列车', an.unique_train_count, '列'],
    ['总运行段', an.total_runs.toLocaleString(), '段'], ['载客时刻表', an.service_schedule_count, '张'], ['车库时刻表', an.depot_schedule_count, '张'],
    ['最早发车', secToClock(an.earliest_service_seconds), ''], ['最晚发车', secToClock(an.latest_service_seconds), ''],
  ];
  $('#analytics-kpi').innerHTML = kpi.map(x => `<div class="metric-card"><small>${x[0]}</small><b>${x[1]}</b><em>${x[2]}</em></div>`).join('');
  $('#analytics-panel').hidden = false;
  drawAnalyticsList();
}
function analyticsRows() {
  const a = state.analysis; if (!a) return [];
  return (a.health_schedules || []).map(s => {
    const o = s.operations || {};
    return { name: s.name, risk: s.risk_level || 'good', shifts: s.shift_count || 0, trains: s.train_count || 0,
      service_line: o.service_line || '', start: o.service_start_seconds, end: o.service_end_seconds,
      headway_median: o.headway_median_seconds, headway_min: o.headway_min_seconds, phase: o.phase_status,
      days: o.service_day_count || 0, day_names: o.service_day_names || [], runs: o.run_total || 0,
      depot_lines: o.depot_line_count || 0, findings: s.findings || [] };
  });
}
function drawAnalyticsList() {
  const q = ($('#analytics-search').value || '').trim().toLowerCase();
  const filter = $('#analytics-filter').value;
  let rows = analyticsRows();
  if (q) rows = rows.filter(r => r.name.toLowerCase().includes(q) || (r.service_line || '').toLowerCase().includes(q));
  if (filter === 'critical') rows = rows.filter(r => r.risk === 'critical');
  else if (filter === 'warning') rows = rows.filter(r => r.risk === 'warning');
  else if (filter === 'good') rows = rows.filter(r => r.risk === 'good');
  else if (filter === 'issues') rows = rows.filter(r => r.risk !== 'good');
  const rank = { critical: 0, warning: 1, info: 2, good: 3 };
  rows.sort((x, y) => (rank[x.risk] - rank[y.risk]) || (y.runs - x.runs));
  if (!rows.length) { $('#analytics-list').innerHTML = '<div class="placeholder">没有匹配的时刻表。</div>'; return; }
  $('#analytics-list').innerHTML = rows.map(r => {
    const win = (r.start === null || r.start === undefined) ? '无运行段' : `${secToClock(r.start)}–${secToClock(r.end)}`;
    const findingsHtml = r.findings.length ? r.findings.map(f => `<div class="finding ${f.severity}"><div><strong>${escapeHtml(f.title)}</strong><small>${escapeHtml(f.action || f.detail)}</small></div></div>`).join('') : '<div class="placeholder">该时刻表没有诊断问题。</div>';
    return `<details class="analytics-row ${r.risk}"><summary>
      <span class="a-name"><span class="risk-dot ${r.risk}"></span>${escapeHtml(r.name)}</span>
      <span class="a-cell">${r.shifts} 班 / ${r.trains} 车</span>
      <span class="a-cell">${win}</span>
      <span class="a-cell">班距 ${minutesText(r.headway_median)}</span>
      <span class="a-cell">${r.days}/7 天</span>
      <span class="a-cell">${r.runs.toLocaleString()} 段</span>
    </summary><div class="analytics-detail">
      <div class="a-detail-grid">
        <div><small>载客主线路</small><b>${escapeHtml(r.service_line || '—')}</b></div>
        <div><small>相位</small><b>${({good:'均匀',warning:'部分重叠',critical:'全部同点',not_applicable:'不适用',insufficient_data:'样本不足'}[r.phase] || r.phase || '—')}</b></div>
        <div><small>最小班距</small><b>${minutesText(r.headway_min)}</b></div>
        <div><small>车库线路</small><b>${r.depot_lines} 条</b></div>
        <div><small>覆盖</small><b>${r.day_names.length ? r.day_names.join(' ') : '—'}</b></div>
      </div>
      ${findingsHtml}
    </div></details>`;
  }).join('');
}
function exportReport(kind) {
  const a = state.analysis; if (!a) { toast('请先完成体检', true); return; }
  const rows = analyticsRows();
  const stamp = timestamp();
  let blob, filename;
  if (kind === 'csv') {
    const header = ['时刻表', '风险', '班次', '列车', '主线路', '最早发车', '最晚发车', '班距中位数(分)', '最小班距(分)', '覆盖天数', '运行段', '车库线路'];
    const csvRows = rows.map(r => [r.name, RISK_LABELS[r.risk] || r.risk, r.shifts, r.trains, r.service_line,
      secToClock(r.start), secToClock(r.end), r.headway_median != null ? (r.headway_median / 60).toFixed(1) : '',
      r.headway_min != null ? (r.headway_min / 60).toFixed(1) : '', r.days, r.runs, r.depot_lines]);
    const esc = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = '\ufeff' + [header, ...csvRows].map(line => line.map(esc).join(',')).join('\r\n');
    blob = new Blob([csv], { type: 'text/csv;charset=utf-8' }); filename = `运营报告_${stamp}.csv`;
  } else {
    blob = new Blob([JSON.stringify({ generated: new Date().toISOString(), export: a.export, health_score: a.health_score, analytics: a.analytics, schedules: rows }, null, 2)], { type: 'application/json' });
    filename = `运营报告_${stamp}.json`;
  }
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 500);
  toast(`已导出 ${filename}`);
}
function renderRecoverTargets(a) {
  const targets = (a.health_schedules || []).filter(s => s.is_blank_template);
  const sel = $('#recover-target');
  sel.innerHTML = targets.length
    ? targets.map(s => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}${(s.lines || []).length ? ' · ' + escapeHtml((s.lines || []).slice(0, 2).join('、')) : ''}</option>`).join('')
    : '<option value="">没有可恢复的空白模板</option>';
  $('#find-reference-btn').disabled = !targets.length;
  $('#reference-list').innerHTML = '<div class="placeholder">选择目标模板后点“自动查找历史车队”。</div>';
  state.reference = null; $('#recover-btn').disabled = true;
  $('#recover-output').value = outputPath('Recovery');
}
function renderReference(result) {
  const list = result.candidates || [];
  state.reference = null; $('#recover-btn').disabled = true;
  if (!list.length) { $('#reference-list').innerHTML = '<div class="placeholder">没有找到匹配的历史车队。</div>'; return; }
  $('#reference-list').innerHTML = list.map((c, i) => {
    const when = c.export_modified_timestamp ? new Date(c.export_modified_timestamp * 1000).toLocaleString() : '';
    const file = (c.export || '').split(/[\\/]/).pop();
    return `<label class="pair-card"><input class="reference-check" type="radio" name="reference-pick" data-index="${i}" ${i === 0 ? 'checked' : ''}><div><div class="pair-route"><span>${escapeHtml(c.source)}</span><i></i><span>${escapeHtml(result.target)}</span></div><small>${escapeHtml(c.reason)} · ${c.train_count} 列车 · ${escapeHtml(file)} · ${escapeHtml(when)}</small></div><span class="confidence">匹配 ${c.score}</span></label>`;
  }).join('');
  state.referenceCandidates = list;
  const pick = (i) => { const c = state.referenceCandidates[i]; state.reference = { export: c.export, source: c.source }; $('#recover-btn').disabled = false; };
  pick(0);
  $$('.reference-check').forEach(el => el.addEventListener('change', () => pick(+el.dataset.index)));
  toast(`找到 ${list.length} 个候选历史车队，最佳：${result.best.source}`);
}
function renderFindingGroups(findings) {
  if (!findings.length) return '<div class="placeholder">没有需要处理的问题，全部检查通过。</div>';
  const groups = [['critical', '严重问题'], ['warning', '需要注意'], ['info', '提示']];
  const findingCard = f => `<div class="finding ${f.severity}"><div><strong>${escapeHtml(f.title)}</strong><small>${escapeHtml(f.action || f.detail)}</small></div><span class="schedule-name">${escapeHtml(f.schedule || '全局检查')}</span></div>`;
  return groups.map(([sev, label]) => {
    const rows = findings.filter(f => f.severity === sev);
    if (!rows.length) return '';
    return `<div class="finding-group-title ${sev}">${label} <span>${rows.length}</span></div>` + rows.map(findingCard).join('');
  }).join('');
}
function renderRepairTasks(a) {
  const tasks = a.repair_tasks || [];
  const matched = a.compatible_schedule_count === a.expected_schedule_count && a.located_train_count === a.train_count;
  $('#repair-count').textContent = tasks.length;
  $('#repair-panel').hidden = tasks.length === 0;
  if (!tasks.length) return;
  $('#repair-list').innerHTML = tasks.map(t => `<label class="schedule-option"><input class="repair-check" type="checkbox" data-repair-type="${escapeHtml(t.type)}" data-repair-value="${escapeHtml(t.type === 'retire_overlap' ? t.pair : t.schedule)}" ${t.selected_by_default ? 'checked' : ''}><span><strong>${escapeHtml(t.label)}</strong><small>解决：${escapeHtml((t.resolves || []).join('、'))}</small></span></label>`).join('');
  refreshOutputNames();
  const btn = $('#fix-button');
  btn.disabled = !matched;
  btn.title = matched ? '' : '存档与导出未完全匹配，请先解决“文件不匹配”再修复';
}
function renderPairs(pairs) {
  $('#pair-count').textContent = pairs.length;
  $('#pair-list').innerHTML = pairs.length ? pairs.map((p, i) => `<label class="pair-card"><input class="pair-check" type="checkbox" data-pair="${escapeHtml(`${p.source}::${p.target}`)}" ${p.ready ? 'checked' : 'disabled'}><div><div class="pair-route"><span>${escapeHtml(p.source)}</span><i></i><span>${escapeHtml(p.target)}</span></div><small>${escapeHtml(p.reason)} · ${p.fleet_size} 列车</small></div><span class="confidence">${escapeHtml(p.confidence)}</span></label>`).join('') : '<div class="placeholder">没有找到可直接执行的迁移方案。</div>';
}
function renderSchedules(schedules) {
  const usable = schedules.filter(x => x.train_count > 0);
  $('#schedule-list').innerHTML = usable.length ? usable.map(s => `<label class="schedule-option"><input class="schedule-check" type="checkbox" value="${escapeHtml(s.name)}"><span><strong>${escapeHtml(s.name)}</strong><small>${s.train_count} 列车 · 已启用 ${s.garage_enabled}</small></span></label>`).join('') : '<div class="placeholder">没有可配置的车队。</div>';
}
function renderCleanup() {
  const c = state.cleanup; if (!c) return;
  $('#cleanup-summary').innerHTML = `<div class="clean-stat"><small>工具副本</small><b>${c.completed_copy_count}</b></div><div class="clean-stat"><small>保护最新</small><b>${c.protected_copy_count}</b></div><div class="clean-stat"><small>可清理组</small><b>${c.candidate_count}</b></div><div class="clean-stat"><small>预计释放</small><b>${formatBytes(c.candidate_bytes)}</b></div>`;
  $('#cleanup-list').innerHTML = c.targets.length ? c.targets.map(x => `<div class="cleanup-item"><div><strong>${escapeHtml(x.name)}</strong><small>${escapeHtml(x.reason)}</small></div><span>${formatBytes(x.bytes)}</span></div>`).join('') : '<div class="placeholder">当前规则下没有可清理文件。正式存档始终不会出现在这里。</div>';
  $('#cleanup-explanation').textContent = state.cleanMode === 'compact' ? `立即瘦身会保留最新 ${c.keep} 份，其余工具副本移入回收站。` : `自动规则：保留最新 ${c.keep} 份，只清理超过 ${c.days} 天的额外副本。`;
  $('#execute-cleanup').disabled = c.candidate_count === 0;
}
function renderRoadmap(items) {
  const labels = {available:'已可用',next:'下一阶段',planned:'已规划',research:'研究阶段'};
  $('#roadmap-list').innerHTML = items.map(x => `<article class="road-item ${x.status}"><div class="road-rank">${x.rank}</div><div><h3>${escapeHtml(x.name)}</h3><p>${escapeHtml(x.detail)}</p></div><span class="road-status">${labels[x.status]}</span></article>`).join('');
}
function renderInventory(result) {
  const summary = $('#inventory-summary');
  summary.className = 'metric-grid'; summary.hidden = false;
  summary.innerHTML = [
    ['导出份数', (result.exports || []).length, '份'],
    ['并行进程', result.workers_used, '个'],
    ['总耗时', `${result.elapsed_seconds}`, '秒'],
    ['逻辑核心', result.logical_cpu_count, '个'],
  ].map(x => `<div class="metric-card"><small>${x[0]}</small><b>${x[1]}</b><em>${x[2]}</em></div>`).join('');
  const rows = result.exports || [];
  $('#inventory-list').innerHTML = rows.length ? rows.map(r => {
    if (!r.ok) return `<div class="cleanup-item"><div><strong>${escapeHtml(r.name)}</strong><small class="danger-text">读取失败：${escapeHtml(r.error || '未知错误')}</small></div><span>${r.elapsed_seconds}s</span></div>`;
    const crit = r.severity_counts?.critical || 0, warn = r.severity_counts?.warning || 0;
    const critNames = (r.critical_schedules || []).length ? ` · 严重表：${escapeHtml(r.critical_schedules.slice(0,3).join('、'))}${r.critical_schedules.length>3?'…':''}` : '';
    return `<div class="cleanup-item"><div><strong>${escapeHtml(r.name)}</strong><small>健康 ${r.health_score} · 严重 ${crit} · 提醒 ${warn} · 来源 ${r.source_count} · 空白模板 ${r.blank_template_count} · ${formatBytes(r.file_size)}${critNames}</small></div><span class="health-pill h${r.health_score>=90?'good':r.health_score>=70?'warn':'bad'}">${r.health_score}</span></div>`;
  }).join('') : '<div class="placeholder">目录中没有历史导出。</div>';
  toast(`盘点完成：${rows.length} 份导出，用 ${result.workers_used} 个进程耗时 ${result.elapsed_seconds}s`);
}
function changeLabel(change) { return { added:'新增', removed:'删除', modified:'修改' }[change] || change; }
function renderCompare(result) {
  const grid = `<div class="metric-grid"><div class="metric-card"><small>较早健康</small><b>${result.before_health_score}</b><em>分</em></div><div class="metric-card"><small>较新健康</small><b>${result.after_health_score}</b><em>分</em></div><div class="metric-card"><small>变化时刻表</small><b>${result.change_count}</b><em>张</em></div><div class="metric-card"><small>新增/解决问题</small><b>${(result.new_findings||[]).length}/${(result.resolved_findings||[]).length}</b><em>项</em></div></div>`;
  const changes = (result.changes || []).map(c => {
    let detail = '';
    if (c.change === 'modified' && c.fields) {
      detail = Object.entries(c.fields).map(([k,v]) => `${escapeHtml(k)}: ${escapeHtml(JSON.stringify(v.before))} → ${escapeHtml(JSON.stringify(v.after))}`).join(' ; ');
    }
    return `<div class="cleanup-item"><div><strong>${escapeHtml(c.schedule)}</strong><small>${detail || '—'}</small></div><span class="change-tag ${c.change}">${changeLabel(c.change)}</span></div>`;
  }).join('') || '<div class="placeholder">两份导出的时刻表结构一致。</div>';
  const findingsBlock = (title, list, cls) => (list && list.length) ? `<div class="plan-section-title">${title}</div>` + list.map(f => `<div class="finding ${cls}"><div><strong>${escapeHtml(f.title)}</strong><small>${escapeHtml(f.schedule || '全局')}</small></div><span class="schedule-name">${escapeHtml(f.code)}</span></div>`).join('') : '';
  $('#compare-result').innerHTML = grid + `<div class="plan-section-title">时刻表变化</div>` + changes
    + findingsBlock('新增的问题', result.new_findings, 'critical')
    + findingsBlock('已解决的问题', result.resolved_findings, 'info');
  toast(`对比完成：${result.change_count} 张时刻表有变化`);
}
function parseClock(value) { const [h,m]=value.split(':').map(Number); if(!Number.isFinite(h)||!Number.isFinite(m))throw new Error(`时间格式无效：${value}`); return h*60+m; }
function clockText(minutes) { const normalized=((Math.round(minutes)%1440)+1440)%1440; return `${String(Math.floor(normalized/60)).padStart(2,'0')}:${String(normalized%60).padStart(2,'0')}`; }
function parseWindows(value) {
  return value.split(/[,，]/).map(x=>x.trim()).filter(Boolean).map(x=>{const parts=x.split('-').map(y=>y.trim());if(parts.length!==2)throw new Error(`高峰时段格式无效：${x}`);let start=parseClock(parts[0]),end=parseClock(parts[1]);if(end<=start)end+=1440;return [start,end];});
}
function isPeakMinute(minute, windows) { const dayMinute=((minute%1440)+1440)%1440; return windows.some(([s,e])=>{if(e<=1440)return dayMinute>=s&&dayMinute<e;return dayMinute>=s||dayMinute<e-1440;}); }
function calculatePlan() {
  try {
    const name=$('#plan-name').value.trim()||'未命名方案'; let first=parseClock($('#plan-first').value),last=parseClock($('#plan-last').value);if(last<=first)last+=1440;
    const cycle=Number($('#plan-cycle').value),peak=Number($('#plan-peak').value),offpeak=Number($('#plan-offpeak').value),phase=Number($('#plan-phase').value)||0,windows=parseWindows($('#plan-windows').value);
    if([cycle,peak,offpeak].some(x=>!Number.isFinite(x)||x<=0))throw new Error('循环时间和班距必须大于 0');
    const departures=[];let minute=first+phase;let guard=0;while(minute<=last&&guard++<10000){const peakNow=isPeakMinute(minute,windows);departures.push({minute,peak:peakNow,time:clockText(minute)});minute+=peakNow?peak:offpeak;}
    const peakFleet=Math.ceil(cycle/peak),offpeakFleet=Math.ceil(cycle/offpeak);
    const fleet=Math.max(peakFleet,offpeakFleet);const spacing=cycle/fleet;const phases=Array.from({length:fleet},(_,i)=>i*spacing);
    const peakCount=departures.filter(x=>x.peak).length;
    state.plan={name,first:clockText(first),last:clockText(last),cycle_minutes:cycle,peak_headway_minutes:peak,offpeak_headway_minutes:offpeak,peak_windows:$('#plan-windows').value,phase_start_minutes:phase,minimum_fleet:fleet,peak_fleet:peakFleet,offpeak_fleet:offpeakFleet,uniform_phase_spacing_minutes:spacing,phase_offsets_minutes:phases,departure_count:departures.length,peak_departure_count:peakCount,departures};
    const phaseText=phases.map(x=>x.toFixed(1)).join(', ');
    const departureText=departures.map(x=>x.time).join(', ');
    state.planCopy={phases:phaseText,departures:departureText};
    $('#planner-results').innerHTML=`<div class="plan-stat-grid"><div class="plan-stat"><small>全天发车</small><b>${departures.length}</b><em>其中高峰 ${peakCount}</em></div><div class="plan-stat"><small>高峰最低配车</small><b>${peakFleet} 列</b><em>平峰 ${offpeakFleet} 列</em></div><div class="plan-stat"><small>均匀相位</small><b>${spacing.toFixed(1)} 分</b><em>共 ${fleet} 列</em></div></div><div class="plan-section-title">发车序列 <button class="text-button mini" data-copy="departures">复制</button></div><div class="departure-cloud">${departures.map(x=>`<span class="departure ${x.peak?'peak':''}">${x.time}</span>`).join('')}</div><div class="plan-section-title">${fleet} 列车的循环相位（分钟） <button class="text-button mini" data-copy="phases">复制</button></div><div class="phase-table">${phases.map((x,i)=>`<span>${String(i+1).padStart(2,'0')} · +${x.toFixed(1)}</span>`).join('')}</div><p class="plan-note">配车按“完整循环 ÷ 班距”向上取整：高峰班距更密所以需要更多车。实际运营建议另加备用车，并在游戏中用模板的真实运行时间复核。相位可直接复制到游戏偏移分组。</p>`;
  } catch(e){toast(e.message,true);}
}

function renderMapData(result) {
  state.network = { lines: result.lines || [], stations: result.stations || {} };
  const lines = state.network.lines;
  if (!lines.length) { $('#map-line-list').innerHTML = '<div class="placeholder">这份导出没有可绘制的线路。</div>'; return; }
  $('#map-line-list').innerHTML = lines.map(l => {
    const c = lineColor(l.color);
    const service = l.stop_count > 1;
    return `<label class="map-line-option"><input class="map-line-check" type="checkbox" value="${escapeHtml(l.id)}" data-service="${service ? 1 : 0}" ${service ? 'checked' : ''}><span class="line-swatch" style="background:${c}"></span><span><strong>${escapeHtml(l.name)}</strong><small>${escapeHtml(l.code || '')}${l.code ? ' · ' : ''}${l.stop_count} 站</small></span></label>`;
  }).join('');
  $('#map-render-panel').hidden = false;
  drawTransitMap();
  toast(`已载入 ${lines.length} 条线路、${result.station_count} 个车站`);
}
function selectedMapLines() {
  const ids = new Set($$('.map-line-check:checked').map(x => x.value));
  return (state.network?.lines || []).filter(l => ids.has(l.id));
}
// Schematic (octilinear) relaxation: snap every edge to the nearest of 8
// directions with roughly uniform spacing, keeping interchange nodes shared.
// This is a good-enough metro-map approximation, not an exact optimizer.
function octilinearize(raw, lines, usedIds) {
  const edges = [];
  const seen = new Set();
  lines.forEach(l => {
    const seq = l.stops.filter(id => raw[id]);
    for (let i = 0; i < seq.length - 1; i++) {
      const a = seq[i], b = seq[i + 1];
      if (a === b) continue;
      const key = a < b ? `${a}|${b}` : `${b}|${a}`;
      if (seen.has(key)) continue;
      seen.add(key); edges.push([a, b]);
    }
  });
  if (!edges.length) return;
  // Normalize so the median edge length becomes ~1 (uniform target spacing).
  const lens = edges.map(([a, b]) => Math.hypot(raw[a].x - raw[b].x, raw[a].y - raw[b].y)).sort((p, q) => p - q);
  const med = lens[Math.floor(lens.length / 2)] || 1e-6;
  usedIds.forEach(id => { raw[id].x /= med; raw[id].y /= med; });
  const QUART = Math.PI / 4;
  for (let iter = 0; iter < 140; iter++) {
    const damping = 0.5 * (1 - iter / 200);
    const acc = {};
    usedIds.forEach(id => { acc[id] = [0, 0, 0]; });
    edges.forEach(([a, b]) => {
      const dx = raw[b].x - raw[a].x, dy = raw[b].y - raw[a].y;
      const snapped = Math.round(Math.atan2(dy, dx) / QUART) * QUART;
      const ux = Math.cos(snapped), uy = Math.sin(snapped);
      const mx = (raw[a].x + raw[b].x) / 2, my = (raw[a].y + raw[b].y) / 2;
      acc[a][0] += mx - ux / 2; acc[a][1] += my - uy / 2; acc[a][2]++;
      acc[b][0] += mx + ux / 2; acc[b][1] += my + uy / 2; acc[b][2]++;
    });
    usedIds.forEach(id => {
      if (!acc[id][2]) return;
      const tx = acc[id][0] / acc[id][2], ty = acc[id][1] / acc[id][2];
      raw[id].x += damping * (tx - raw[id].x);
      raw[id].y += damping * (ty - raw[id].y);
    });
  }
}
function mapStyle() { return $('#map-style')?.value || 'geo'; }
function drawTransitMap() {
  if (!state.network) return;
  const stations = state.network.stations;
  const lines = selectedMapLines().filter(l => l.stops.length >= 2);
  const canvas = $('#map-canvas');
  if (!lines.length) { canvas.innerHTML = '<div class="placeholder">请至少选择一条有 2 站以上的线路。</div>'; return; }
  if (mapStyle() === 'strip') { drawStripDiagram(lines, stations); return; }
  const usedIds = [...new Set(lines.flatMap(l => l.stops))].filter(id => stations[id]);
  if (!usedIds.length) { canvas.innerHTML = '<div class="placeholder">所选线路的车站缺少坐标。</div>'; return; }
  const lats = usedIds.map(id => stations[id].lat);
  const meanLat = lats.reduce((a, b) => a + b, 0) / lats.length;
  const k = Math.cos(meanLat * Math.PI / 180);
  const schematic = mapStyle() === 'schematic';
  const raw = {};
  usedIds.forEach(id => { raw[id] = { x: stations[id].lon * k, y: -stations[id].lat }; });
  if (schematic) octilinearize(raw, lines, usedIds);
  const xs = usedIds.map(id => raw[id].x), ys = usedIds.map(id => raw[id].y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 1200, H = 820, pad = 70;
  const spanX = (maxX - minX) || 1e-6, spanY = (maxY - minY) || 1e-6;
  const scale = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const offX = (W - scale * spanX) / 2, offY = (H - scale * spanY) / 2;
  const project = id => ({ x: offX + (raw[id].x - minX) * scale, y: offY + (raw[id].y - minY) * scale });
  // Count how many selected lines touch each station -> interchange detection.
  const usage = {};
  lines.forEach(l => [...new Set(l.stops)].forEach(id => { if (stations[id]) usage[id] = (usage[id] || 0) + 1; }));
  const curved = $('#map-curved').checked && !schematic;
  const allLabels = $('#map-all-labels').checked;
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('class', 'transit-svg');
  svg.setAttribute('xmlns', SVG_NS);
  const bg = document.createElementNS(SVG_NS, 'rect');
  bg.setAttribute('x', 0); bg.setAttribute('y', 0); bg.setAttribute('width', W); bg.setAttribute('height', H); bg.setAttribute('fill', '#ffffff');
  svg.appendChild(bg);
  const pathFor = pts2 => {
    if (!curved || pts2.length < 3) return pts2.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
    let d = `M${pts2[0].x.toFixed(1)} ${pts2[0].y.toFixed(1)}`;
    for (let i = 0; i < pts2.length - 1; i++) {
      const mx = (pts2[i].x + pts2[i + 1].x) / 2, my = (pts2[i].y + pts2[i + 1].y) / 2;
      d += ` Q${pts2[i].x.toFixed(1)} ${pts2[i].y.toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`;
    }
    const last = pts2[pts2.length - 1];
    d += ` L${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
    return d;
  };
  // Draw thicker lines first so shorter ones stay visible on top.
  [...lines].sort((a, b) => b.stops.length - a.stops.length).forEach(l => {
    const seq = l.stops.filter(id => stations[id]).map(project);
    if (seq.length < 2) return;
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', pathFor(seq));
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', lineColor(l.color));
    path.setAttribute('stroke-width', 6);
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('opacity', '0.92');
    svg.appendChild(path);
  });
  // Station dots + labels.
  const labelIds = new Set();
  lines.forEach(l => { const s = l.stops.filter(id => stations[id]); if (s.length) { labelIds.add(s[0]); labelIds.add(s[s.length - 1]); } });
  Object.keys(usage).forEach(id => { if (usage[id] > 1) labelIds.add(id); });
  usedIds.forEach(id => {
    const p = project(id); const interchange = usage[id] > 1;
    const dot = document.createElementNS(SVG_NS, 'circle');
    dot.setAttribute('cx', p.x.toFixed(1)); dot.setAttribute('cy', p.y.toFixed(1));
    dot.setAttribute('r', interchange ? 6 : 3.2);
    dot.setAttribute('fill', interchange ? '#ffffff' : '#0b1d2a');
    dot.setAttribute('stroke', interchange ? '#0b1d2a' : '#ffffff');
    dot.setAttribute('stroke-width', interchange ? 2.4 : 1.2);
    svg.appendChild(dot);
    if (allLabels || labelIds.has(id)) {
      const t = document.createElementNS(SVG_NS, 'text');
      t.setAttribute('x', (p.x + 8).toFixed(1)); t.setAttribute('y', (p.y - 6).toFixed(1));
      t.setAttribute('class', interchange ? 'st-label major' : 'st-label');
      t.textContent = stations[id].name;
      svg.appendChild(t);
    }
  });
  // Legend.
  const legendX = 24, legendY = 30;
  lines.forEach((l, i) => {
    const y = legendY + i * 24;
    const sw = document.createElementNS(SVG_NS, 'rect');
    sw.setAttribute('x', legendX); sw.setAttribute('y', y - 11); sw.setAttribute('width', 26); sw.setAttribute('height', 8); sw.setAttribute('rx', 4);
    sw.setAttribute('fill', lineColor(l.color)); svg.appendChild(sw);
    const t = document.createElementNS(SVG_NS, 'text');
    t.setAttribute('x', legendX + 34); t.setAttribute('y', y); t.setAttribute('class', 'legend-label');
    t.textContent = `${l.name}${l.code ? ' (' + l.code + ')' : ''}`;
    svg.appendChild(t);
  });
  canvas.innerHTML = '';
  canvas.appendChild(svg);
  state.mapSvg = svg;
}
function svgEl(name, attrs) {
  const e = document.createElementNS(SVG_NS, name);
  for (const k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
  return e;
}
// Metro-sticker single-line strip diagram (like the printed line maps at stations).
// One evenly-spaced strip per selected line, with terminus caps, interchange
// rings and transfer badges pulled from the whole network. Text uses inline
// attributes so the SVG export stays faithful without external CSS.
function drawStripDiagram(lines, stations) {
  const canvas = $('#map-canvas');
  const vertical = ($('#map-orient')?.value || 'h') === 'v';
  const allLines = state.network.lines || [];
  const stationLines = {};
  allLines.forEach(l => [...new Set(l.stops)].forEach(id => { (stationLines[id] || (stationLines[id] = [])).push(l); }));
  const rows = lines.map(l => ({ line: l, stops: l.stops.filter(id => stations[id]) })).filter(r => r.stops.length >= 2);
  if (!rows.length) { canvas.innerHTML = '<div class="placeholder">所选线路的车站缺少坐标。</div>'; return; }
  const maxStops = Math.max(...rows.map(r => r.stops.length));
  const FONT = '"Microsoft YaHei UI","Segoe UI",sans-serif';
  const gap = 66, dotR = 8;
  const svg = svgEl('svg', { class: 'transit-svg', xmlns: SVG_NS });

  // Pills size themselves to their text (CJK ~1em, ASCII ~0.58em) so full line
  // codes and station names always fit — nothing is truncated.
  const estWidth = (text, fs) => { let u = 0; for (const ch of String(text)) u += (ch.charCodeAt(0) > 255 ? 1 : 0.58); return u * fs; };
  const pillW = (text, fs) => Math.max(fs * 2, estWidth(text, fs) + fs * 1.2);
  const pill = (cx, cy, text, color, fs, wOverride) => {
    const w = wOverride || pillW(text, fs), h = fs * 1.75, r = h / 2;
    svg.appendChild(svgEl('rect', { x: (cx - w / 2).toFixed(1), y: (cy - h / 2).toFixed(1), width: w.toFixed(1), height: h.toFixed(1), rx: r.toFixed(1), fill: color }));
    const t = svgEl('text', { x: cx.toFixed(1), y: (cy + fs * 0.35).toFixed(1), 'text-anchor': 'middle', 'font-family': FONT, 'font-size': fs, 'font-weight': 800, fill: '#ffffff' });
    t.textContent = text; svg.appendChild(t);
    return w;
  };
  // Interchange badges: every distinct connecting line at the station (deduped by
  // label so identical codes aren't repeated). No cap — the canvas grows to fit.
  const transferBadges = (id, selfId) => {
    const seen = new Set(); const out = [];
    (stationLines[id] || []).forEach(tl => {
      if (tl.id === selfId) return;
      const lab = (tl.code || tl.name || '').trim();
      if (!lab || seen.has(lab)) return; seen.add(lab);
      out.push({ label: lab, color: lineColor(tl.color) });
    });
    return out;
  };
  const lineFS = 14, badgeFS = 11, nameFS = 14;
  const dot = (cx, cy, term, inter, color) => {
    svg.appendChild(svgEl('circle', { cx: cx.toFixed(1), cy: cy.toFixed(1), r: term ? dotR + 2 : (inter ? dotR : 5.5), fill: term ? color : '#ffffff', stroke: color, 'stroke-width': 3 }));
    if (inter) svg.appendChild(svgEl('circle', { cx: cx.toFixed(1), cy: cy.toFixed(1), r: 2.6, fill: color }));
  };
  const badgesFor = {};
  rows.forEach(r => r.stops.forEach(id => { badgesFor[r.line.id + '|' + id] = transferBadges(id, r.line.id); }));
  const lineLabels = rows.map(r => (r.line.code || r.line.name || '').trim());
  const badgeRowW = bs => bs.reduce((s, b) => s + pillW(b.label, badgeFS) + 7, 0);

  let W, H;
  if (!vertical) {
    // Space above each strip for the (angled) full station names, space below for
    // the vertical stack of every transfer badge; horizontal gap widens so a
    // station's badge column never touches its neighbour's.
    const maxNameW = Math.max(...rows.flatMap(r => r.stops.map(id => estWidth(stations[id].name, nameFS))));
    const maxBadgeW = Math.max(0, ...rows.flatMap(r => r.stops.flatMap(id => badgesFor[r.line.id + '|' + id].map(b => pillW(b.label, badgeFS)))));
    const maxTransfers = Math.max(0, ...rows.flatMap(r => r.stops.map(id => badgesFor[r.line.id + '|' + id].length)));
    const localGap = Math.max(gap, maxBadgeW + 12);
    const aboveSpace = Math.ceil(Math.sin(0.96) * maxNameW) + 26;   // ~55° angled name height
    const belowSpace = 26 + maxTransfers * (badgeFS * 1.75 + 6) + 12;
    const rowH = aboveSpace + belowSpace + 24;
    const maxLinePillW = Math.max(...lineLabels.map(t => pillW(t, lineFS)));
    const badgeCx = 20 + maxLinePillW / 2;
    const leftPad = 20 + maxLinePillW + 28;
    const rightPad = Math.ceil(Math.cos(0.96) * maxNameW) + 60;
    const topPad = 24;
    W = leftPad + (maxStops - 1) * localGap + rightPad;
    H = topPad + rows.length * rowH + 20;
    svg.setAttribute('viewBox', `0 0 ${W.toFixed(0)} ${H.toFixed(0)}`);
    svg.appendChild(svgEl('rect', { x: 0, y: 0, width: W, height: H, fill: '#ffffff' }));
    rows.forEach((r, ri) => {
      const color = lineColor(r.line.color);
      const yMid = topPad + ri * rowH + aboveSpace;
      const x1 = leftPad + (r.stops.length - 1) * localGap;
      svg.appendChild(svgEl('line', { x1: leftPad, y1: yMid, x2: x1, y2: yMid, stroke: color, 'stroke-width': 12, 'stroke-linecap': 'round' }));
      pill(badgeCx, yMid, lineLabels[ri], color, lineFS, maxLinePillW);
      r.stops.forEach((id, j) => {
        const x = leftPad + j * localGap;
        const term = j === 0 || j === r.stops.length - 1;
        const badges = badgesFor[r.line.id + '|' + id];
        dot(x, yMid, term, badges.length > 0, color);
        const ny = yMid - 20;
        const nm = svgEl('text', { x: (x + 4).toFixed(1), y: ny.toFixed(1), 'text-anchor': 'start', transform: `rotate(-55 ${(x + 4).toFixed(1)} ${ny.toFixed(1)})`, 'font-family': FONT, 'font-size': term || badges.length ? nameFS : 13, 'font-weight': term || badges.length ? 800 : 500, fill: '#12202b' });
        nm.textContent = stations[id].name; svg.appendChild(nm);
        badges.forEach((b, k) => pill(x, yMid + 28 + k * (badgeFS * 1.75 + 6), b.label, b.color, badgeFS));
      });
    });
  } else {
    // Each station on its own row: full name to the right, every transfer badge
    // laid out to the left. Column width grows to fit the widest name and the
    // busiest interchange so nothing overlaps.
    const nameMaxW = Math.max(...rows.flatMap(r => r.stops.map(id => estWidth(stations[id].name, nameFS))));
    const leftArea = Math.max(60, ...rows.flatMap(r => r.stops.map(id => badgeRowW(badgesFor[r.line.id + '|' + id])))) + 18;
    const maxLinePillW = Math.max(...lineLabels.map(t => pillW(t, lineFS)));
    const colW = Math.max(leftArea + 24 + nameMaxW + 44, maxLinePillW + 30);
    const topPad = 92, botPad = 40, leftPad = 24;
    H = topPad + (maxStops - 1) * gap + botPad;
    W = leftPad + rows.length * colW + 20;
    svg.setAttribute('viewBox', `0 0 ${W.toFixed(0)} ${H.toFixed(0)}`);
    svg.appendChild(svgEl('rect', { x: 0, y: 0, width: W, height: H, fill: '#ffffff' }));
    rows.forEach((r, ri) => {
      const color = lineColor(r.line.color);
      const xMid = leftPad + ri * colW + leftArea;
      const y1 = topPad + (r.stops.length - 1) * gap;
      svg.appendChild(svgEl('line', { x1: xMid, y1: topPad, x2: xMid, y2: y1, stroke: color, 'stroke-width': 12, 'stroke-linecap': 'round' }));
      pill(xMid, 46, lineLabels[ri], color, lineFS);
      r.stops.forEach((id, j) => {
        const y = topPad + j * gap;
        const term = j === 0 || j === r.stops.length - 1;
        const badges = badgesFor[r.line.id + '|' + id];
        dot(xMid, y, term, badges.length > 0, color);
        const nm = svgEl('text', { x: (xMid + 20).toFixed(1), y: (y + 5).toFixed(1), 'text-anchor': 'start', 'font-family': FONT, 'font-size': term || badges.length ? nameFS : 13, 'font-weight': term || badges.length ? 800 : 500, fill: '#12202b' });
        nm.textContent = stations[id].name; svg.appendChild(nm);
        let bx = xMid - dotR - 12;
        badges.forEach(b => { const w = pillW(b.label, badgeFS); pill(bx - w / 2, y, b.label, b.color, badgeFS, w); bx -= (w + 7); });
      });
    });
  }
  canvas.innerHTML = '';
  canvas.appendChild(svg);
  state.mapSvg = svg;
}
function buildMapSvgData() {
  const clone = state.mapSvg.cloneNode(true);
  const css = 'text.st-label{font:11px "Segoe UI",sans-serif;fill:#0b1d2a;paint-order:stroke;stroke:#fff;stroke-width:3px;}text.st-label.major{font-weight:700;font-size:12px;}text.legend-label{font:13px "Segoe UI",sans-serif;fill:#0b1d2a;}';
  const style = document.createElementNS(SVG_NS, 'style'); style.textContent = css; clone.insertBefore(style, clone.firstChild);
  return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(clone);
}
async function exportMapSvg() {
  if (!state.mapSvg) { toast('请先绘制线路图', true); return; }
  const data = buildMapSvgData();
  const filename = `线路图_${timestamp()}.svg`;
  // Save through the local service so it reliably lands on disk in the desktop
  // window (WebView2 often ignores JS blob downloads); show the full path.
  try {
    const res = await api('/api/map/export', { method: 'POST', body: JSON.stringify({ svg: data, filename, format: 'svg' }) });
    toast(`已保存到下载文件夹：${res.path}`);
    return;
  } catch (e) {
    // Fall back to a browser download if the service save is unavailable.
    const blob = new Blob([data], { type: 'image/svg+xml' });
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
    document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 500);
    toast('已触发下载（若窗口未弹出，请查看浏览器/下载文件夹）');
  }
}
function renderNetworkDiff(r) {
  const grid = `<div class="metric-grid"><div class="metric-card"><small>线路变化</small><b>${r.line_change_count}</b><em>条</em></div><div class="metric-card"><small>车站变化</small><b>${r.station_change_count}</b><em>个</em></div><div class="metric-card"><small>较早路网</small><b>${r.before_summary.lines}/${r.before_summary.stations}</b><em>线/站</em></div><div class="metric-card"><small>较新路网</small><b>${r.after_summary.lines}/${r.after_summary.stations}</b><em>线/站</em></div></div>`;
  const tag = { added: 'added', removed: 'removed', modified: 'modified', renamed: 'modified', moved: 'modified' };
  const label = { added: '新增', removed: '删除', modified: '修改', renamed: '改名', moved: '移动' };
  const row = c => `<div class="cleanup-item"><div><strong>${escapeHtml(c.name)}</strong><small>${escapeHtml(c.detail || '—')}</small></div><span class="change-tag ${tag[c.change]}">${label[c.change]}</span></div>`;
  const block = (title, list) => list.length ? `<div class="plan-section-title">${title}</div>` + list.map(row).join('') : '';
  const body = block('线路变化', r.line_changes) + block('车站变化', r.station_changes)
    || '<div class="placeholder">两份导出的线路与车站完全一致。</div>';
  $('#netdiff-result').innerHTML = grid + body;
  toast(`路网差分完成：${r.line_change_count} 条线路、${r.station_change_count} 个车站有变化`);
}
// ---- Real-world reference map (Leaflet + OpenRailwayMap overlay) ----------
const REALNET = { map: null, ready: false, gameLayer: null, ormLayer: null, baseLayers: {}, pinLayer: null, pins: [], loader: null };
function loadJson(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; } }
function saveJson(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {} }
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (REALNET.loader) return REALNET.loader;
  REALNET.loader = new Promise((resolve, reject) => {
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'; document.head.appendChild(css);
    const js = document.createElement('script'); js.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    js.onload = () => resolve(); js.onerror = () => reject(new Error('无法加载地图组件（Leaflet），请检查网络后重试')); document.head.appendChild(js);
  });
  return REALNET.loader;
}
function realnetSetBase(kind) {
  const map = REALNET.map; if (!map) return;
  Object.values(REALNET.baseLayers).forEach(l => { if (map.hasLayer(l)) map.removeLayer(l); });
  (REALNET.baseLayers[kind] || REALNET.baseLayers.carto).addTo(map);
}
function realnetSetOverlay(style) {
  const map = REALNET.map; if (!map) return;
  if (REALNET.ormLayer) { map.removeLayer(REALNET.ormLayer); REALNET.ormLayer = null; }
  if (style === 'none') return;
  REALNET.ormLayer = L.tileLayer(`https://{s}.tiles.openrailwaymap.org/${style}/{z}/{x}/{y}.png`,
    { subdomains: 'abc', maxZoom: 19, tileSize: 256, opacity: 0.9, attribution: '© OpenRailwayMap (CC-BY-SA 2.0)' }).addTo(map);
}
function realnetDrawGame() {
  if (!REALNET.ready || !REALNET.gameLayer) return;
  REALNET.gameLayer.clearLayers();
  if (!$('#realnet-show-game').checked || !state.network) return;
  const st = state.network.stations || {};
  (state.network.lines || []).forEach(l => {
    const pts = (l.stops || []).filter(id => st[id]).map(id => [st[id].lat, st[id].lon]);
    if (pts.length >= 2) L.polyline(pts, { color: lineColor(l.color), weight: 4, opacity: 0.85 }).addTo(REALNET.gameLayer);
  });
  const drawn = new Set();
  (state.network.lines || []).forEach(l => (l.stops || []).forEach(id => {
    if (!st[id] || drawn.has(id)) return; drawn.add(id);
    L.circleMarker([st[id].lat, st[id].lon], { radius: 3, color: '#0b1d2a', weight: 1, fillColor: '#ffffff', fillOpacity: 1 })
      .bindTooltip(st[id].name).addTo(REALNET.gameLayer);
  }));
}
function realnetEnsureData() {
  if (state.network) { realnetDrawGame(); return; }
  const exp = $('#export-select')?.value;
  if (exp) startTask('map-data', { export: exp });
  else toast('请先在“总览与体检”选择时刻表导出', true);
}
function realnetFitGame() {
  if (!state.network) { realnetEnsureData(); return; }
  const st = state.network.stations || {}; const pts = [];
  (state.network.lines || []).forEach(l => (l.stops || []).forEach(id => { if (st[id]) pts.push([st[id].lat, st[id].lon]); }));
  if (!pts.length) { toast('游戏路网没有坐标可定位', true); return; }
  REALNET.map.fitBounds(pts, { padding: [40, 40] });
}
function addRealnetPin(lat, lng, name) {
  const p = { lat: +(+lat).toFixed(6), lng: +(+lng).toFixed(6), name: name || `规划点 ${REALNET.pins.length + 1}`, note: '' };
  REALNET.pins.push(p); saveJson('nimby_realnet_pins', REALNET.pins); renderRealnetPins();
}
function renderRealnetPins() {
  if (REALNET.pinLayer) {
    REALNET.pinLayer.clearLayers();
    REALNET.pins.forEach(p => L.marker([p.lat, p.lng]).addTo(REALNET.pinLayer).bindPopup(`<b>${escapeHtml(p.name)}</b><br>${p.lat}, ${p.lng}`));
  }
  const count = REALNET.pins.length;
  $('#realnet-pin-count').textContent = `规划针 ${count} 个`;
  $('#realnet-pin-panel').hidden = count === 0;
  $('#realnet-pin-list').innerHTML = REALNET.pins.map((p, i) =>
    `<div class="realnet-pin-row"><div><strong>${escapeHtml(p.name)}</strong><small>${p.lat}, ${p.lng}</small></div><div class="realnet-pin-acts"><button class="text-button" data-pin-go="${i}">定位</button><button class="text-button" data-pin-rename="${i}">改名</button><button class="text-button danger-text" data-pin-del="${i}">删除</button></div></div>`
  ).join('');
}
function exportPins(kind) {
  if (!REALNET.pins.length) { toast('还没有规划针', true); return; }
  const stamp = timestamp(); let blob, filename;
  if (kind === 'geojson') {
    const gj = { type: 'FeatureCollection', features: REALNET.pins.map(p => ({ type: 'Feature', properties: { name: p.name, note: p.note || '' }, geometry: { type: 'Point', coordinates: [p.lng, p.lat] } })) };
    blob = new Blob([JSON.stringify(gj, null, 2)], { type: 'application/geo+json' }); filename = `规划针_${stamp}.geojson`;
  } else {
    const esc = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = '\ufeff' + [['name', 'lat', 'lon', 'note'], ...REALNET.pins.map(p => [p.name, p.lat, p.lng, p.note || ''])].map(r => r.map(esc).join(',')).join('\r\n');
    blob = new Blob([csv], { type: 'text/csv;charset=utf-8' }); filename = `规划针_${stamp}.csv`;
  }
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 500);
  toast(`已导出 ${filename}`);
}
async function realnetSearch() {
  const q = ($('#realnet-search').value || '').trim(); if (!q) return;
  const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (m) { REALNET.map.setView([+m[1], +m[2]], 13); return; }
  try {
    const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`, { headers: { Accept: 'application/json' } });
    const data = await r.json();
    if (!data.length) { toast('没找到该地点', true); return; }
    REALNET.map.setView([+data[0].lat, +data[0].lon], 13);
  } catch (e) { toast('地点搜索失败，请检查网络', true); }
}
function renderImported() {
  if (!REALNET.importLayer) REALNET.importLayer = L.layerGroup().addTo(REALNET.map);
  REALNET.importLayer.clearLayers();
  (REALNET.imported || []).forEach(s => {
    L.circleMarker([s.lat, s.lon], { radius: 4, color: '#b5530f', weight: 1.5, fillColor: '#e67e22', fillOpacity: 0.9 })
      .bindTooltip(`${s.name}（现实）`).addTo(REALNET.importLayer);
  });
  const has = (REALNET.imported || []).length;
  $('#realnet-import-to-pins').disabled = !has;
  $('#realnet-import-clear').disabled = !has;
  $('#realnet-import-count').textContent = has ? `已导入 ${has} 个真实车站` : '';
}
const OVERPASS_ENDPOINTS = [
  'https://overpass-api.de/api/interpreter',
  'https://overpass.kumi.systems/api/interpreter',
  'https://overpass.private.coffee/api/interpreter',
];
async function importRealStations() {
  if (!REALNET.map) { toast('地图未就绪', true); return; }
  if (REALNET.map.getZoom() < 8) { toast('范围太大，请先放大到城市级别再拉取', true); return; }
  const b = REALNET.map.getBounds();
  const bbox = `${b.getSouth().toFixed(5)},${b.getWest().toFixed(5)},${b.getNorth().toFixed(5)},${b.getEast().toFixed(5)}`;
  const q = `[out:json][timeout:60];node["railway"~"^(station|halt)$"](${bbox});out body 800;`;
  const btn = $('#realnet-import-stations'); btn.disabled = true;
  let lastErr = '';
  for (let i = 0; i < OVERPASS_ENDPOINTS.length; i++) {
    toast(`正在从 OpenStreetMap 拉取真实车站…（源 ${i + 1}/${OVERPASS_ENDPOINTS.length}）`);
    try {
      const r = await fetch(OVERPASS_ENDPOINTS[i], { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: q });
      if (!r.ok) { lastErr = 'HTTP ' + r.status; continue; }
      const data = await r.json();
      const items = (data.elements || []).map(e => {
        const lat = e.lat ?? e.center?.lat, lon = e.lon ?? e.center?.lon;
        return (lat && lon) ? { lat, lon, name: (e.tags && (e.tags.name || e.tags['name:en'])) || '未命名车站' } : null;
      }).filter(Boolean);
      REALNET.imported = items; renderImported();
      toast(items.length ? `已拉取 ${items.length} 个真实车站，可一键加入规划针` : '该范围没有找到车站，换个区域或放大再试', !items.length);
      btn.disabled = false; return;
    } catch (e) { lastErr = e.message; }
  }
  btn.disabled = false;
  toast(`拉取失败：${lastErr}。Overpass 公共服务器可能繁忙，请缩小范围或稍后再试`, true);
}
function importedToPins() {
  const items = REALNET.imported || [];
  if (!items.length) { toast('请先拉取真实车站', true); return; }
  items.forEach(s => REALNET.pins.push({ lat: +(+s.lat).toFixed(6), lng: +(+s.lon).toFixed(6), name: s.name, note: 'OSM 导入' }));
  saveJson('nimby_realnet_pins', REALNET.pins); renderRealnetPins();
  toast(`已把 ${items.length} 个真实车站加入规划针清单`);
}
async function initRealnet() {
  if (REALNET.ready) { setTimeout(() => REALNET.map.invalidateSize(), 60); if (state.network) realnetDrawGame(); return; }
  try { await loadLeaflet(); } catch (e) { $('#realnet-map').innerHTML = `<div class="placeholder">${escapeHtml(e.message)}</div>`; return; }
  const el = $('#realnet-map'); el.innerHTML = '';
  const saved = loadJson('nimby_realnet_view', { lat: 35.681, lng: 139.767, zoom: 11 });
  const map = L.map(el, { zoomControl: true, worldCopyJump: true }).setView([saved.lat, saved.lng], saved.zoom);
  REALNET.map = map;
  REALNET.baseLayers = {
    carto: L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { maxZoom: 20, subdomains: 'abcd', attribution: '© OpenStreetMap © CARTO' }),
    osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }),
    dark: L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 20, subdomains: 'abcd', attribution: '© OpenStreetMap © CARTO' }),
  };
  realnetSetBase($('#realnet-base').value);
  realnetSetOverlay($('#realnet-overlay').value);
  REALNET.gameLayer = L.layerGroup().addTo(map);
  REALNET.pinLayer = L.layerGroup().addTo(map);
  REALNET.pins = loadJson('nimby_realnet_pins', []);
  renderRealnetPins();
  map.on('moveend zoomend', () => saveJson('nimby_realnet_view', { lat: map.getCenter().lat, lng: map.getCenter().lng, zoom: map.getZoom() }));
  map.on('click', e => { if ($('#realnet-pin-mode').checked) addRealnetPin(e.latlng.lat, e.latlng.lng); });
  REALNET.ready = true;
  if (state.network) realnetDrawGame(); else realnetEnsureData();
  setTimeout(() => map.invalidateSize(), 80);
}

// Poll from a Web Worker heartbeat: worker timers are NOT throttled when the
// window loses focus / is occluded (e.g. the user tabs into NIMBY Rails), so
// the task dock keeps updating and always reaches completion.
function ensureTicker() {
  if ('taskTicker' in state) return state.taskTicker;
  try {
    const src = "let id=null;onmessage=function(e){if(e.data==='start'){if(!id)id=setInterval(function(){postMessage(1)},500);}else if(e.data==='stop'){clearInterval(id);id=null;}};";
    const worker = new Worker(URL.createObjectURL(new Blob([src], { type: 'application/javascript' })));
    worker.onmessage = () => { if (state.taskActive) pollOnce(); };
    state.taskTicker = worker;
  } catch (e) {
    state.taskTicker = null;
  }
  return state.taskTicker;
}
function fallbackLoop() {
  if (!state.taskActive) return;
  clearTimeout(state.fallbackTimer);
  state.fallbackTimer = setTimeout(async () => { await pollOnce(); fallbackLoop(); }, 500);
}
function finishTask() {
  state.taskActive = false;
  $('#task-dock').hidden = true;
  const worker = ensureTicker();
  if (worker) worker.postMessage('stop');
  clearTimeout(state.fallbackTimer);
}
const WRITE_ACTIONS = new Set(['batch-migrate', 'fix-tasks', 'extension', 'recover-template']);
async function startTask(action, payload) {
  if (WRITE_ACTIONS.has(action) && state.gameVersion && state.gameVersion.safe_to_write === false) {
    if (!confirm(`${state.gameVersion.note || '当前游戏版本尚未完全验证写入。'}\n\n工具仍只写入新存档、绝不覆盖原档。是否继续？`)) return;
  }
  try {
    state.taskAction = action; state.pollFailures = 0; state.pollBusy = false; state.taskActive = true;
    await api('/api/task/start', { method:'POST', body:JSON.stringify({ action, ...payload }) });
    $('#task-dock').hidden = false; $('#task-progress').style.width = '2%'; $('#task-message').textContent = '正在准备任务…';
    const worker = ensureTicker();
    if (worker) worker.postMessage('start'); else fallbackLoop();
    pollOnce();
  } catch (e) { state.taskActive = false; toast(e.message, true); }
}
async function pollOnce() {
  if (state.pollBusy || !state.taskActive) return;
  state.pollBusy = true;
  try {
    const s = await api(`/api/task/status?_=${Date.now()}`, { timeoutMs: 12000 });
    state.pollFailures = 0;
    if (s.state === 'running') {
      const p = s.progress || {}; $('#task-message').textContent = p.message || '正在后台处理…'; $('#task-progress').style.width = `${p.percent || 3}%`; return;
    }
    if (s.state === 'complete') {
      finishTask();
      if (s.action === 'analyze') renderAnalysis(s.result);
      else if (s.action === 'inventory') renderInventory(s.result);
      else if (s.action === 'compare') renderCompare(s.result);
      else if (s.action === 'find-reference') renderReference(s.result);
      else if (s.action === 'map-data') { renderMapData(s.result); if (REALNET.ready) realnetDrawGame(); }
      else if (s.action === 'network-diff') renderNetworkDiff(s.result);
      else { toast(`新存档已创建：${s.result.output_save?.split(/[\\/]/).pop() || '操作完成'}`); await refreshFileLists(); refreshOutputNames(); }
      return;
    }
    if (s.state === 'failed') { finishTask(); toast(s.result?.error || '后台操作失败', true); return; }
  } catch (e) {
    state.pollFailures = (state.pollFailures || 0) + 1;
    if (state.pollFailures <= 10) { $('#task-message').textContent = `连接中断，正在重试…(${state.pollFailures})`; return; }
    finishTask(); toast(`无法获取任务状态：${e.message}`, true);
  } finally {
    state.pollBusy = false;
  }
}
// Snap the dock up to date the instant the window is shown again.
document.addEventListener('visibilitychange', () => { if (!document.hidden && state.taskActive) pollOnce(); });
async function refreshFileLists() {
  const data = await api('/api/bootstrap'); state.bootstrap = data; const saveValue=$('#save-select').value, exportValue=$('#export-select').value;
  setOptions($('#save-select'), data.files.saves); setOptions($('#export-select'), data.files.exports);
  const beforeValue=$('#compare-before').value, afterValue=$('#compare-after').value; setCompareOptions(data.files.exports);
  if ([...$('#compare-before').options].some(x=>x.value===beforeValue)) $('#compare-before').value=beforeValue;
  if ([...$('#compare-after').options].some(x=>x.value===afterValue)) $('#compare-after').value=afterValue;
  if ([...$('#save-select').options].some(x=>x.value===saveValue)) $('#save-select').value=saveValue;
  if ([...$('#export-select').options].some(x=>x.value===exportValue)) $('#export-select').value=exportValue;
}
async function updateCleanupPreview() {
  try {
    const data = await api('/api/cleanup/preview', { method:'POST', body:JSON.stringify({ days:+$('#cleanup-days').value, keep:+$('#cleanup-keep').value, compact:state.cleanMode==='compact' }) }); state.cleanup=data.cleanup; renderCleanup();
  } catch(e) { toast(e.message,true); }
}

$('#main-nav').addEventListener('click', e => { const b=e.target.closest('[data-view]'); if(b) switchView(b.dataset.view); });
$('#refresh-files').addEventListener('click', async()=>{await refreshFileLists(); toast('文件列表已刷新');});
$('#select-latest').addEventListener('click',()=>{ $('#save-select').selectedIndex=0; $('#export-select').selectedIndex=0; refreshOutputNames(); toast('已选择最新存档和最新即时导出'); });
$('#save-select').addEventListener('change', refreshOutputNames);
$('#scan-button').addEventListener('click',()=>startTask('analyze',{save:$('#save-select').value,export:$('#export-select').value}));
$('#migrate-button').addEventListener('click',()=>{ const pairs=$$('.pair-check:checked').map(x=>x.dataset.pair); if(!pairs.length)return toast('请至少勾选一组迁移方案',true); startTask('batch-migrate',{save:$('#save-select').value,export:$('#export-select').value,output:$('#migration-output').value,pairs,garage_join:$('#garage-join').checked}); });
$('#toggle-schedules').addEventListener('click',()=>{const boxes=$$('.schedule-check'); const all=boxes.length&&boxes.every(x=>x.checked); boxes.forEach(x=>x.checked=!all); $('#toggle-schedules').textContent=all?'全选':'清空';});
$('#fix-button').addEventListener('click',()=>{
  const checked=$$('.repair-check:checked');
  if(!checked.length)return toast('请至少勾选一个可修复任务',true);
  const pairs=checked.filter(x=>x.dataset.repairType==='retire_overlap').map(x=>x.dataset.repairValue);
  const depot_schedules=checked.filter(x=>x.dataset.repairType==='depot_x1').map(x=>x.dataset.repairValue);
  startTask('fix-tasks',{save:$('#save-select').value,export:$('#export-select').value,output:$('#fix-output').value,pairs,depot_schedules});
});
$('#load-lines').addEventListener('click',()=>{ if(!$('#export-select').value)return toast('请先在“总览与体检”选择时刻表导出',true); startTask('map-data',{export:$('#export-select').value}); });
$('#draw-map').addEventListener('click',drawTransitMap);
$('#export-map-svg').addEventListener('click',exportMapSvg);
$('#map-all-labels').addEventListener('change',drawTransitMap);
$('#map-curved').addEventListener('change',drawTransitMap);
$('#map-style').addEventListener('change',()=>{ $('#map-orient-wrap').hidden = mapStyle()!=='strip'; drawTransitMap(); });
$('#map-orient').addEventListener('change',drawTransitMap);
$('#map-select-all').addEventListener('click',()=>{ $$('.map-line-check').forEach(x=>x.checked=true); drawTransitMap(); });
$('#map-clear').addEventListener('click',()=>{ $$('.map-line-check').forEach(x=>x.checked=false); drawTransitMap(); });
$('#map-select-service').addEventListener('click',()=>{ $$('.map-line-check').forEach(x=>x.checked=x.dataset.service==='1'); drawTransitMap(); });
$('#map-line-list').addEventListener('change',e=>{ if(e.target.classList.contains('map-line-check')&&!$('#map-render-panel').hidden) drawTransitMap(); });
$('#realnet-base').addEventListener('change',()=>realnetSetBase($('#realnet-base').value));
$('#realnet-overlay').addEventListener('change',()=>realnetSetOverlay($('#realnet-overlay').value));
$('#realnet-show-game').addEventListener('change',realnetDrawGame);
$('#realnet-go').addEventListener('click',realnetSearch);
$('#realnet-search').addEventListener('keydown',e=>{ if(e.key==='Enter') realnetSearch(); });
$('#realnet-fit-game').addEventListener('click',realnetFitGame);
$('#realnet-export-geojson').addEventListener('click',()=>exportPins('geojson'));
$('#realnet-export-csv').addEventListener('click',()=>exportPins('csv'));
$('#realnet-clear-pins').addEventListener('click',()=>{ if(!REALNET.pins.length)return; if(!confirm('清空所有规划针？此操作不可撤销。'))return; REALNET.pins=[]; saveJson('nimby_realnet_pins',REALNET.pins); renderRealnetPins(); });
$('#realnet-import-stations').addEventListener('click',importRealStations);
$('#realnet-import-to-pins').addEventListener('click',importedToPins);
$('#realnet-import-clear').addEventListener('click',()=>{ REALNET.imported=[]; renderImported(); });
$('#realnet-pin-list').addEventListener('click',e=>{
  const go=e.target.closest('[data-pin-go]'), rn=e.target.closest('[data-pin-rename]'), del=e.target.closest('[data-pin-del]');
  if(go){ const p=REALNET.pins[+go.dataset.pinGo]; if(p) REALNET.map.setView([p.lat,p.lng],14); }
  else if(rn){ const i=+rn.dataset.pinRename; const p=REALNET.pins[i]; const name=prompt('规划点名称',p.name); if(name!==null){ p.name=name.trim()||p.name; saveJson('nimby_realnet_pins',REALNET.pins); renderRealnetPins(); } }
  else if(del){ const i=+del.dataset.pinDel; REALNET.pins.splice(i,1); saveJson('nimby_realnet_pins',REALNET.pins); renderRealnetPins(); }
});
$('#run-netdiff').addEventListener('click',()=>{ const before=$('#netdiff-before').value, after=$('#netdiff-after').value; if(!before||!after)return toast('请先完成一次体检以载入导出列表',true); if(before===after)return toast('请选择两份不同的导出',true); startTask('network-diff',{before,after}); });
$('#analytics-search').addEventListener('input', drawAnalyticsList);
$('#analytics-filter').addEventListener('change', drawAnalyticsList);
$('#export-report-csv').addEventListener('click', () => exportReport('csv'));
$('#export-report-json').addEventListener('click', () => exportReport('json'));
$('#run-inventory').addEventListener('click',()=>startTask('inventory',{limit:12}));
$('#run-compare').addEventListener('click',()=>{
  const before=$('#compare-before').value, after=$('#compare-after').value;
  if(!before||!after)return toast('请先完成体检以载入导出列表',true);
  if(before===after)return toast('请选择两份不同的导出',true);
  startTask('compare',{before,after});
});
function extensionTask(mode){const schedules=$$('.schedule-check:checked').map(x=>x.value); if(!schedules.length)return toast('请至少选择一张时刻表',true); startTask('extension',{save:$('#save-select').value,export:$('#export-select').value,output:$('#extension-output').value,schedules,mode});}
$('#add-extension').addEventListener('click',()=>extensionTask('add')); $('#remove-extension').addEventListener('click',()=>extensionTask('remove'));
$('#save-cleanup-settings').addEventListener('click',async()=>{try{await api('/api/settings',{method:'POST',body:JSON.stringify({enabled:$('#cleanup-enabled').checked,days:+$('#cleanup-days').value,keep:+$('#cleanup-keep').value})}); await updateCleanupPreview(); toast('自动清理规则已保存');}catch(e){toast(e.message,true);}});
$$('[data-clean-mode]').forEach(b=>b.addEventListener('click',()=>{$$('[data-clean-mode]').forEach(x=>x.classList.toggle('active',x===b));state.cleanMode=b.dataset.cleanMode;updateCleanupPreview();}));
$('#execute-cleanup').addEventListener('click',async()=>{const c=state.cleanup;if(!c?.candidate_count)return;if(!confirm(`将 ${c.candidate_count} 组文件移入 Windows 回收站，预计释放 ${formatBytes(c.candidate_bytes)}。继续吗？`))return;try{const d=await api('/api/cleanup/execute',{method:'POST',body:JSON.stringify({days:+$('#cleanup-days').value,keep:+$('#cleanup-keep').value,compact:state.cleanMode==='compact'})});toast(`已将 ${d.result.moved_group_count} 组文件移入回收站`);await updateCleanupPreview();await refreshFileLists();}catch(e){toast(e.message,true);}});
$('#find-reference-btn').addEventListener('click',()=>{
  const target=$('#recover-target').value;
  if(!target)return toast('没有可恢复的空白模板',true);
  if(!$('#export-select').value)return toast('请先在“总览与体检”选择导出并完成体检',true);
  startTask('find-reference',{export:$('#export-select').value,target,limit:15});
});
$('#recover-btn').addEventListener('click',()=>{
  const target=$('#recover-target').value;
  if(!state.reference)return toast('请先选择一个历史车队',true);
  if(!target)return toast('请选择目标模板',true);
  startTask('recover-template',{save:$('#save-select').value,export:$('#export-select').value,output:$('#recover-output').value,reference_export:state.reference.export,reference_source:state.reference.source,target,garage_join:$('#recover-garage').checked});
});
$('#calculate-plan').addEventListener('click',calculatePlan);
$('#planner-results').addEventListener('click',async e=>{const btn=e.target.closest('[data-copy]');if(!btn||!state.planCopy)return;const text=state.planCopy[btn.dataset.copy]||'';try{await navigator.clipboard.writeText(text);toast('已复制到剪贴板');}catch(err){const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');toast('已复制到剪贴板');}catch(_){toast('复制失败，请手动选择',true);}ta.remove();}});
$('#export-plan').addEventListener('click',()=>{if(!state.plan)calculatePlan();if(!state.plan)return;const blob=new Blob([JSON.stringify(state.plan,null,2)],{type:'application/json'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${state.plan.name.replace(/[\\/:*?"<>|]/g,'_')}_plan.json`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),500);});
function vehiclePayload(){
  const num=(id)=>Number($(id).value);
  return {
    mod_name:$('#veh-mod-name').value, author:$('#veh-author').value, version:$('#veh-version').value,
    model_name:$('#veh-model-name').value, model_id:$('#veh-model-id').value,
    role:$('#veh-role').value, power_type:$('#veh-power-type').value, gauge:$('#veh-gauge').value,
    year_introduced:num('#veh-year'), country:$('#veh-country').value,
    two_cabs:$('#veh-two-cabs').checked, middle_enabled:$('#veh-middle-enabled').checked,
    middle_min:num('#veh-middle-min'), middle_def:num('#veh-middle-def'), middle_max:num('#veh-middle-max'),
    head_length:num('#veh-head-length'), head_width:num('#veh-head-width'), head_max_speed:num('#veh-head-max-speed'),
    head_power:num('#veh-head-power'), head_empty_mass:num('#veh-head-empty-mass'), head_price:num('#veh-head-price'),
    head_max_pax:num('#veh-head-max-pax'), head_standing_pax:num('#veh-head-standing-pax'),
    middle_length:num('#veh-middle-length'), middle_width:num('#veh-middle-width'), middle_max_speed:num('#veh-middle-max-speed'),
    middle_power:num('#veh-middle-power'), middle_empty_mass:num('#veh-middle-empty-mass'), middle_price:num('#veh-middle-price'),
    middle_max_pax:num('#veh-middle-max-pax'), middle_standing_pax:num('#veh-middle-standing-pax'),
    body_color:$('#veh-body-color').value, window_color:$('#veh-window-color').value, door_color:$('#veh-door-color').value,
  };
}
$('#generate-vehicle').addEventListener('click',async()=>{
  try{
    const data=await api('/api/vehicle/generate',{method:'POST',body:JSON.stringify(vehiclePayload())});
    const link=document.createElement('a');link.href=data.download_url;link.download=`${data.meta.mod_id}.zip`;document.body.appendChild(link);link.click();link.remove();
    const m=data.meta;
    $('#veh-preview').innerHTML=`<div class="veh-preview-head"><strong>${escapeHtml(m.model_name)}</strong><span class="verified-chip">${escapeHtml(m.tags)}</span></div><div class="veh-preview-meta">编组 ${m.units} 节 · 组成：<code>${escapeHtml(m.composition)}</code></div><pre class="veh-modtext">${escapeHtml(m.mod_text)}</pre>`;
    toast(`车辆模组已生成：${m.model_name}`);
  }catch(e){toast(e.message,true);}
});
$('#generate-script').addEventListener('click',async()=>{try{const data=await api('/api/script/generate',{method:'POST',body:JSON.stringify({name:$('#script-name').value,id:$('#script-id').value,garage_join:$('#rule-garage').checked,arrival_hold:$('#rule-hold').checked,hold_seconds:+$('#rule-hold-seconds').value,signal_speed_limit:$('#rule-speed').checked,speed_kmh:+$('#rule-speed-kmh').value})});const link=document.createElement('a');link.href=data.download_url;link.download=`${data.meta.script_id}.zip`;document.body.appendChild(link);link.click();link.remove();toast(`规则包已生成：${data.meta.enabled_rules.join('、')}`);}catch(e){toast(e.message,true);}});
$('#cancel-task').addEventListener('click',async()=>{await api('/api/task/cancel',{method:'POST',body:'{}'});finishTask();toast('任务已取消');});
setInterval(()=>fetch(`/api/ping?_=${Date.now()}`,{cache:'no-store'}).catch(()=>{}),5000);
loadBootstrap().catch(e=>toast(e.message,true));
