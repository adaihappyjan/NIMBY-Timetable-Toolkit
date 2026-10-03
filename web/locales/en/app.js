const APP_BUILD = '2026-09-30-independent-corridor-clearance';
console.log('[NIMBY toolkit] app.js build', APP_BUILD, document.querySelector('script[src*="app.js"]')?.src || '');
const state = { bootstrap: null, analysis: null, cleanup: null, cleanMode: 'automatic', taskAction: null, plan: null, vehicleCatalog: null, vehicleMod: null, binderBinding: null, update: null };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const viewMeta = {
  dashboard: ['CONTROL CENTER', "Railway operations overview"], analytics: ['OPERATIONS ANALYTICS', "Operating analysis"], map: ['TRANSIT MAP', "Route maps"], realnet: ['REAL-WORLD REFERENCE', "Real-world reference map"], timetable: ['TIMETABLE STUDIO', "Timetables"],
  extensions: ['DEPOT CONTROL', "Depot-join management"], binder: ['BATCH BINDER', "Batch extension binding"], vehicle: ['ROLLING STOCK WORKSHOP', "Vehicle workshop"], scripts: ['SCRIPT WORKSHOP', "NimbyScript Rule generator"], history: ['FLEET HISTORY', "History comparison"], cleanup: ['STORAGE CARE', "Copy cleanup"], roadmap: ['CAPABILITY LADDER', "Features"], author: ['MEET THE MAKER', "About"],
  workspace: ['LINE WORKSPACE', "Line workspace"], learn: ['GETTING STARTED', "Tutorials"]
};
const SVG_NS = 'http://www.w3.org/2000/svg';
function lineColor(raw) {
  if (!raw) return '#8a9ba4';
  let hex = String(raw).trim().replace(/^0x/i, '').replace(/^#/, '');
  if (hex.length === 8) hex = hex.slice(2); // drop alpha: AABBGGRR -> BBGGRR
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) return '#8a9ba4';
  // NIMBY Rails stores line colors as ABGR (0xAABBGGRR), so swap the red and
  // blue bytes back to standard RGB (e.g. STM Yellow 0xff00cdff -> #ffcd00).
  return `#${hex.slice(4, 6)}${hex.slice(2, 4)}${hex.slice(0, 2)}`.toLowerCase();
}
function secToClock(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.round(seconds) % 86400; const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
function minutesText(seconds) { return (seconds === null || seconds === undefined) ? '—' : `${(seconds / 60).toFixed(1)} min`; }
const RISK_LABELS = { critical: "Critical", warning: "Warning", info: "Note", good: "Healthy" };

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}
function toast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.className = `toast${error ? ' error' : ''}`; el.hidden = false;
  if (error) showErrorHelp(message);
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, 5500);
}
function showErrorHelp(message) {
  let box = $('#error-help');
  if (!box) {
    box = document.createElement('aside'); box.id = 'error-help'; box.className = 'error-help';
    box.setAttribute('role', 'alert'); document.body.appendChild(box);
  }
  const detail = String(message);
  let next = "Keep the diagnostic information below. If a new copy exists, inspect it in game before deciding to use it. Do not overwrite the original.";
  if (/更新|回滚|恢复不完整|update|rollback|restor/i.test(detail)) next = "Check the installation/recovery status below. If restoration is incomplete, stop using the app, retain logs and backups, and extract a complete release again. This is an application-update issue; re-exporting game timetables will not fix it.";
  else if (/JSON|export|不匹配|missing from export/i.test(detail)) next = "Check the file type first. For timetable data, pause and save in game, keep it paused and export Timetable Export JSON. Refresh the overview and verify that save/export pair.";
  else if (/Permission|权限|拒绝访问/i.test(detail)) next = "Choose a writable folder, check free space and file locks, then retry. Do not disable system security.";
  else if (/Node|组件缺失/i.test(detail)) next = "Extract the complete portable package again, retaining runtime. Source installations need Node.js 22+. Re-exporting timetables is not required.";
  else if (/指纹|预览.*变化|存档.*变化|fingerprint|(?:preview|save|file).*changed/i.test(detail)) next = "Input files changed after preview. Refresh, reload and preview again before writing. Do not bypass verification.";
  else if (/轨道表|索引|结构|版本|track table|index|structure|version/i.test(detail)) next = "This structure cannot be recognized reliably, so writing is blocked. Keep the original save and diagnostics for investigation. Re-exporting JSON may not resolve this.";
  else if (/Order ID|Timing|Enter|Exit/.test(detail)) next = "Check the order fields. Leave new order IDs blank for automatic assignment. The line, entry stop, exit stop and timing point must use the same line's stop sequence.";
  box.innerHTML = `<button type="button" aria-label="Close error details">Off</button><strong>Operation incomplete</strong><p>${escapeHtml(detail.slice(0,300))}${detail.length>300?'…':''}</p><p>${escapeHtml(next)}</p><p>This message does not confirm a successful write or rollback. Check the task result and output files.</p><details><summary>Show diagnostics (copy when reporting issues)</summary><pre>${escapeHtml(detail)}</pre></details>`;
  box.querySelector('button').onclick = () => box.remove();
}
function updateFailureMessage(result) {
  const reason = result.error || "Unknown reason";
  if (result.rollback_complete === true) return `Update failed; previous program files restored: ${reason}`;
  if (result.rollback_complete === false) return `Update failed and previous files were not fully restored. Stop using the app and retain the backup ${result.backup_dir || result.backup || "(See update log)"}, Extract the complete release again. Reason: ${reason}`;
  return `Update incomplete; installation and recovery status are uncertain. Check the update log and extract a complete package again if needed: ${reason}`;
}
async function api(path, options = {}) {
  const { timeoutMs = 20000, ...rest } = options;
  let controller, timer;
  if (typeof AbortController !== 'undefined') { controller = new AbortController(); timer = setTimeout(() => controller.abort(), timeoutMs); }
  try {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json', 'X-NIMBY-Language': document.documentElement?.lang || 'zh-CN' }, cache: 'no-store', signal: controller && controller.signal, ...rest });
    const data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || "Operation failed"); return data;
  } finally { if (timer) clearTimeout(timer); }
}
function switchView(name) {
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === name));
  $$('.view').forEach(el => el.classList.toggle('active', el.id === `view-${name}`));
  $('#view-eyebrow').textContent = viewMeta[name][0]; $('#view-title').textContent = viewMeta[name][1];
  if (name === 'realnet') initRealnet();
  if (name === 'tilecache') window.refreshTileCache?.();
  if (name === 'map') applyMapZoom();
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
function refreshOutputNames() { $('#migration-output').value = outputPath('Toolkit'); $('#extension-output').value = outputPath('Extension'); $('#fix-output').value = outputPath('Repair'); const rec = $('#recover-output'); if (rec) rec.value = outputPath('Recovery'); const bnd = $('#binder-output'); if (bnd) bnd.value = outputPath('GarageJoin'); syncStationNameExport(); }

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
  $('#map-export-dir').value = data.map_export_dir || '';
  setOptions($('#save-select'), data.files.saves); setOptions($('#export-select'), data.files.exports); setCompareOptions(data.files.exports); refreshOutputNames();
  $('#cleanup-enabled').checked = data.settings.enabled; $('#cleanup-days').value = data.settings.days; $('#cleanup-keep').value = data.settings.keep;
  state.cleanup = data.cleanup; renderCleanup(); renderRoadmap(data.capabilities);
  renderSaveDir(data.save_status);
  const updateAuto = $('#update-auto-check'); if (updateAuto) updateAuto.checked = data.settings.auto_check_updates !== false;
  const updateLabel = $('#update-label'); if (updateLabel) updateLabel.textContent = `v${data.app_version || '—'} · Check for updates`;
  if (data.update_result?.ok) toast(`Toolkit updated from v${data.update_result.from_version} Update to v${data.update_result.to_version}`);
  else if (data.update_result && !data.update_result.ok) toast(updateFailureMessage(data.update_result), true);
  if (data.startup_cleanup?.error) toast(`Startup cleanup incomplete: ${data.startup_cleanup.error}`, true);
  else if (data.startup_cleanup?.result?.moved_file_count) toast(`Startup cleanup moved ${data.startup_cleanup.result.moved_group_count} expired copy groups moved to Recycle Bin`);
  if (data.settings.auto_check_updates !== false) setTimeout(() => checkToolkitUpdate(false), 900);
  await window.restoreWorkspaceSelection?.();
  state.bootstrapReady=true;
  window.startLiveFiles?.(data);
  window.toolkitStartup?.ready();
}

function renderToolkitUpdate(update) {
  state.update = update;
  const button = $('#update-check'), label = $('#update-label'), banner = $('#update-banner');
  button?.classList.toggle('available', !!update.available);
  if (label) label.textContent = update.available ? `v${update.latest_version} Update available` : `v${update.current_version} · Up to date`;
  if (!update.available) { if (banner) banner.hidden = true; return; }
  $('#update-title').textContent = `Toolkit update available v${update.latest_version}`;
  $('#update-detail').textContent = `Current v${update.current_version} · ${formatBytes(update.asset_size)} · Download, verify, replace files and restart`;
  const notes = String(update.notes || '').trim();
  const notesBox = $('#update-notes-box'); notesBox.hidden = !notes;
  if (notes) $('#update-notes').textContent = notes;
  const install = $('#update-install');
  install.disabled = !update.install_supported;
  install.textContent = update.install_supported ? "Download update and restart" : "Update source checkouts with Git";
  banner.hidden = false;
}

async function checkToolkitUpdate(force = false) {
  const button = $('#update-check');
  if (button?.classList.contains('checking')) return;
  button?.classList.add('checking'); if (button) button.disabled = true;
  try {
    const result = await api(`/api/update/check${force ? '?force=1' : ''}`, { timeoutMs: 25000 });
    renderToolkitUpdate(result.update);
    if (force && !result.update.available) toast(`Current v${result.update.current_version} Already up to date`);
  } catch (error) {
    if (force) toast(`Update check failed: ${error.message}`, true);
  } finally {
    button?.classList.remove('checking'); if (button) button.disabled = false;
  }
}

async function installToolkitUpdate() {
  const update = state.update;
  if (!update?.available || !update.install_supported) return;
  if (!confirm(`From v${update.current_version} Update to v${update.latest_version}.

Download the official portable package, verify SHA-256 and every file, then close, replace and reopen the toolkit. Game saves and personal settings are not changed. Continue?`)) return;
  const install = $('#update-install'), dismiss = $('#update-dismiss'), check = $('#update-check');
  install.disabled = true; dismiss.disabled = true; check.disabled = true;
  install.textContent = "Downloading and verifying…";
  $('#update-detail').textContent = "Downloading from the official release. The app will restart after verification; do not open another instance.";
  try {
    const result = await api('/api/update/install', {
      method: 'POST',
      body: JSON.stringify({ version: update.latest_version }),
      timeoutMs: 120000,
    });
    install.textContent = "Verified; restarting…";
    $('#update-detail').textContent = `Verified ${result.update.file_count} files and SHA-256 checks verified; replacing files and restarting.`;
  } catch (error) {
    install.disabled = false; dismiss.disabled = false; check.disabled = false;
    install.textContent = "Retry download and update";
    $('#update-detail').textContent = `Update did not start: ${error.message}`;
    toast(`Update failed: ${error.message}`, true);
  }
}
function renderSaveDir(info) {
  if (!info) return;
  state.saveStatus = info;
  const box = $('#save-dir-box'); const current = $('#save-dir-current'); const hint = $('#save-dir-hint');
  current.textContent = info.save_dir || "(Not set)";
  const found = info.exists && info.has_saves;
  current.className = 'sd-path ' + (found ? 'ok' : (info.exists ? 'warn' : 'bad'));
  const input = $('#save-dir-input'); if (input) input.value = info.save_dir || '';
  const applyBtn = $('#save-dir-apply'); const detectBtn = $('#save-dir-detect');
  if (info.env_locked) {
    hint.innerHTML = "The save directory is set by the environment variable <code>NIMBY_SAVE_DIR</code> and cannot be changed in the interface.";
    if (applyBtn) applyBtn.disabled = true; if (input) input.disabled = true;
  } else {
    if (applyBtn) applyBtn.disabled = false; if (input) input.disabled = false;
    if (found) hint.innerHTML = `Found <b>${info.save_count}</b> saves, <b>${info.export_count}</b> timetable exports. If your saves are elsewhere, change the directory below.`;
    else if (info.exists) hint.innerHTML = "The directory exists, but no files were found <code>.nimbyrails5</code> saves or timetable exports. Confirm this is the NIMBY Rails save directory, or choose a detected directory below.";
    else hint.innerHTML = "NIMBY Rails save directory not found automatically. Choose a candidate below or paste its path.<br>The default save directory is usually <code>Saved Games/Weird and Wry/NIMBY Rails</code>; Export timetable data from the game first; the toolkit does not generate it automatically.";
  }
  const cands = (info.candidates || []).filter(c => c.exists || c.has_saves);
  const wrap = $('#save-dir-cands');
  if (!cands.length) { wrap.innerHTML = ''; }
  else {
    wrap.innerHTML = "<p class=\"cands-title\">Detected directories: </p>" + cands.map(c =>
      `<button class="cand-row${c.has_saves ? ' has' : ''}" data-path="${escapeHtml(c.path)}" ${info.env_locked ? 'disabled' : ''}>
        <span class="cand-dot"></span><span class="cand-path">${escapeHtml(c.path)}</span>
        <span class="cand-tag">${c.has_saves ? "Saves found" : "Empty directory"}</span></button>`).join('');
    wrap.querySelectorAll('.cand-row').forEach(btn => btn.addEventListener('click', () => applySaveDir(btn.dataset.path)));
  }
  // Auto-open the config when nothing usable was found so new users notice it.
  if (!found && !box.dataset.userToggled) box.open = true;
  if (!found) { const sel = $('#save-select'); if (sel && !sel.options.length) sel.innerHTML = "<option value=\"\">No saves found; set the save directory first</option>"; }
}
async function applySaveDir(path) {
  if (!path || !path.trim()) { toast("Enter a save directory path", true); return; }
  try {
    const res = await api('/api/config/save-dir', { method: 'POST', body: JSON.stringify({ path: path.trim() }) });
    setOptions($('#save-select'), res.files.saves); setOptions($('#export-select'), res.files.exports); setCompareOptions(res.files.exports); refreshOutputNames();
    renderSaveDir(res.save_status);
    window.resetLiveFiles?.(res.files);
    toast(res.save_status.has_saves ? `Save directory changed; found ${res.save_status.save_count} saves` : "Directory changed, but no saves were found", !res.save_status.has_saves);
  } catch (e) { toast(e.message, true); }
}
function renderAnalysis(a) {
  state.analysis = a;
  const matched = a.compatible_schedule_count === a.expected_schedule_count && a.located_train_count === a.train_count;
  const gv = a.game_version || {};
  const gvClass = { supported: 'ok', compatible: 'ok', newer: 'warn', unknown: 'warn', outdated: 'bad' }[gv.status] || 'ok';
  const gvChip = `<span class="ver-chip ${gvClass}" title="${escapeHtml(gv.note || '')}">${escapeHtml(gv.save_release ? `Save ${gv.save_release} · ` : '')}model ${gv.model_version ?? "Unknown"} · ${gv.safe_to_write ? "Format verified" : "Read-only checks"}</span>`;
  $('#health-summary').innerHTML = `<div class="health-wrap"><div class="health-ring" style="--score:${a.health_score}"><div><b>${a.health_score}</b><small>/ 100</small></div></div><div class="health-copy"><strong>${matched ? "Files match" : "Files do not match"}</strong><p>${a.compatible_schedule_count}/${a.expected_schedule_count} timetables<br>${a.located_train_count}/${a.train_count} Trains verified</p>${gvChip}</div></div>`;
  state.gameVersion = gv;
  if (gv.status === 'newer' || gv.status === 'unknown' || gv.status === 'outdated') toast(gv.note, gv.status !== 'newer');
  const metrics = [
    ["Timetable", a.schedule_count, "timetables"], ["Trains", a.train_count, "trains"], ["Critical issues", a.severity_counts.critical, "items"], ["Depot extension", a.garage_enabled_total, "Trains"]
  ];
  $('#metric-grid').innerHTML = metrics.map(x => `<div class="metric-card"><small>${x[0]}</small><b>${x[1]}</b><em>${x[2]}</em></div>`).join(''); $('#metric-grid').hidden = false;
  $('#finding-count').textContent = a.findings.length; $('#findings-panel').hidden = false;
  $('#finding-list').innerHTML = renderFindingGroups(a.findings);
  renderPairs(a.suggested_pairs || []); renderSchedules(a.health_schedules || []); renderRepairTasks(a);
  renderAnalytics(a); renderRecoverTargets(a);
  toast(matched ? `Health check complete: ${a.expected_schedule_count} timetables and ${a.train_count} All trains matched` : "The health check found mismatched files. Select data exported from the same save JSON", !matched);
}
function renderAnalytics(a) {
  const an = a.analytics; if (!an) return;
  const kpi = [
    ["Timetable", a.schedule_count, "timetables"], ["Shifts", an.total_shifts, "items"], ["Trains", an.unique_train_count, "trains"],
    ["Total run segments", an.total_runs.toLocaleString(), "sections"], ["Passenger timetable", an.service_schedule_count, "timetables"], ["Depot timetable", an.depot_schedule_count, "timetables"],
    ["First departure", secToClock(an.earliest_service_seconds), ''], ["Last departure", secToClock(an.latest_service_seconds), ''],
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
function headwayText(sec) {
  if (sec == null) return '—';
  const m = sec / 60;
  return m >= 1 ? `${(Math.round(m * 10) / 10)} min` : `${Math.round(sec)} s`;
}
function durText(sec) {
  sec = Math.round(sec || 0);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}
function renderLineTimetable(r) {
  state.lineTimetable = r;
  const wrap = $('#timetable-lines');
  const routes = r.routes || [];
  if (!routes.length) { wrap.innerHTML = "<div class=\"placeholder\">No timed line templates found in this save.</div>"; return; }
  wrap.innerHTML = routes.map((t, i) => {
    const rows = t.stops.map(s => `<tr><td>${escapeHtml(s.station)}</td><td>${durText(s.arrival)}</td><td>${durText(s.departure)}</td><td>${s.dwell}s</td></tr>`).join('');
    return `<details class="tt-line"${i === 0 ? ' open' : ''}><summary><i class="ov-swatch" style="background:${lineColor(t.color)}"></i><strong>${escapeHtml(t.name)}</strong><span>${t.stop_count} stops</span><span>Run ${durText(t.cycle_seconds)}</span></summary>`
      + `<div class="tt-scroll"><table class="tt-table"><thead><tr><th>Stations</th><th>Arrival</th><th>Departure</th><th>Stops</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
  }).join('');
  ttdPopulateLines(routes);
  toast(`Stop-by-stop times loaded: ${routes.length} line templates`);
}
function renderOpsAnalyze(r) {
  state.opsAnalyze = r;
  const sum = $('#ops-summary'), wrap = $('#ops-lines');
  const routes = r.routes || [];
  const s = r.summary || {};
  const rec = r.reconciliation;
  const hasPlan = routes.some(x => x.plan);
  const recCard = rec
    ? `<div class="metric-card"><small>Median reconciliation error</small><b>${rec.headway_error_median_pct ?? '—'}%</b><em>10%within ${rec.within_10pct}/${rec.matched_routes}</em></div>`
    : '';
  sum.innerHTML = `<div class="metric-grid">`
    + `<div class="metric-card"><small>Lines available for estimation</small><b>${s.route_count || 0}</b><em>items</em></div>`
    + `<div class="metric-card"><small>Median headway(Estimate)</small><b>${headwayText(s.headway_estimate_median_seconds || 0)}</b><em>h≈T/N</em></div>`
    + `<div class="metric-card"><small>Total assigned trains</small><b>${s.total_assigned_trains || 0}</b><em>trains</em></div>`
    + recCard + `</div>`;
  if (!routes.length) { wrap.innerHTML = "<div class=\"placeholder\">No estimable passenger lines found; both template duration and assigned train count are required).</div>"; return; }
  const head = `<tr><th>Lines</th><th>Train count N</th><th>Template / estimated duration T</th><th>Headway(Estimate)</th>`
    + (rec ? `<th>Headway(Game export)</th><th>Error</th>` : '')
    + (hasPlan ? `<th>Target→Trains required</th>` : '') + `</tr>`;
  const body = routes.map(t => {
    const errCls = t.headway_error_pct == null ? '' : (t.headway_error_pct <= 10 ? 'ok' : (t.headway_error_pct <= 20 ? 'warn' : 'bad'));
    let row = `<tr><td><i class="ov-swatch" style="background:${lineColor(t.color)}"></i>${escapeHtml(t.name)}</td>`
      + `<td>${t.train_count}</td><td>${headwayText(t.cycle_seconds)}</td>`
      + `<td><strong>${headwayText(t.headway_estimate_seconds)}</strong></td>`;
    if (rec) row += `<td>${t.headway_real_seconds != null ? headwayText(t.headway_real_seconds) : '—'}</td>`
      + `<td>${t.headway_error_pct != null ? `<span class="hw-delta ${errCls}">${t.headway_error_pct}%</span>` : '—'}</td>`;
    if (hasPlan) {
      const p = t.plan;
      const d = p && p.delta_trains;
      const dTxt = d == null ? '—' : (d > 0 ? `plus ${d}` : (d < 0 ? `minus ${-d}` : "Unchanged"));
      const dCls = d > 0 ? 'bad' : (d < 0 ? 'warn' : 'ok');
      row += `<td>${p ? `<strong>${p.required_train_count}</strong> <span class="hw-delta ${dCls}">${dTxt}</span>` : '—'}</td>`;
    }
    return row + '</tr>';
  }).join('');
  wrap.innerHTML = `<div class="tt-scroll"><table class="tt-table"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
  toast(`Direct-save operating estimates complete: ${routes.length} lines` + (rec ? `, Median error ${rec.headway_error_median_pct}%` : ''));
}
function renderHeadwayPlan() {
  const targetMin = +$('#headway-target').value;
  const onlyService = $('#headway-only-service').checked;
  const summary = $('#headway-summary');
  if (!state.analysis) { summary.innerHTML = "<div class=\"placeholder\">Run a health check in Overview & health first.</div>"; $('#headway-table').hidden = true; $('#headway-export').hidden = true; return; }
  if (!(targetMin > 0)) { toast("Enter a valid target headway (min)", true); return; }
  const target = targetMin * 60;
  let rows = analyticsRows().filter(r => r.trains > 0 && r.headway_median != null && r.headway_median > 0);
  if (onlyService) rows = rows.filter(r => r.service_line);
  if (!rows.length) { summary.innerHTML = "<div class=\"placeholder\">No passenger timetables available for planning; headway data is required).</div>"; $('#headway-table').hidden = true; $('#headway-export').hidden = true; return; }
  const plan = rows.map(r => {
    const cycle = r.headway_median * r.trains;         // T = h × N, constant per line
    const need = Math.max(1, Math.ceil(cycle / target));
    return { name: r.name, trains: r.trains, headway: r.headway_median, cycle, need, delta: need - r.trains, line: r.service_line };
  }).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.name.localeCompare(b.name));
  state.headwayPlan = { target, targetMin, plan };
  const add = plan.filter(p => p.delta > 0).reduce((s, p) => s + p.delta, 0);
  const rem = plan.filter(p => p.delta < 0).reduce((s, p) => s - p.delta, 0);
  const same = plan.filter(p => p.delta === 0).length;
  summary.innerHTML = `<div class="metric-grid"><div class="metric-card"><small>Target headway</small><b>${targetMin}</b><em>min</em></div><div class="metric-card"><small>Additional trains needed</small><b>+${add}</b><em>trains</em></div><div class="metric-card"><small>Potential fleet reduction</small><b>-${rem}</b><em>trains</em></div><div class="metric-card"><small>Target met</small><b>${same}</b><em>timetables</em></div></div>`;
  $('#headway-rows').innerHTML = plan.map(p => {
    const cls = p.delta > 0 ? 'bad' : (p.delta < 0 ? 'warn' : 'ok');
    const deltaTxt = p.delta > 0 ? `plus ${p.delta}` : (p.delta < 0 ? `minus ${-p.delta}` : "Unchanged");
    return `<tr><td><strong>${escapeHtml(p.name)}</strong>${p.line ? `<small>${escapeHtml(p.line)}</small>` : ''}</td><td>${p.trains}</td><td>${headwayText(p.headway)}</td><td>${headwayText(p.cycle)}</td><td>${headwayText(p.headway * p.trains / p.need)}</td><td><strong>${p.need}</strong></td><td><span class="hw-delta ${cls}">${deltaTxt}</span></td></tr>`;
  }).join('');
  $('#headway-table').hidden = false;
  $('#headway-export').hidden = false;
  toast(`Planned ${plan.length} timetables; target headway ${targetMin} min`);
}
function exportHeadwayCsv() {
  const p = state.headwayPlan; if (!p) return;
  const lines = [["Timetable", "Service lines", "Current train count", "Current headway(s)", "Template / estimated duration T(s)", "Target headway(s)", "Required train count", "Change"].join(',')];
  p.plan.forEach(x => lines.push([`"${x.name.replace(/"/g, '""')}"`, `"${(x.line || '').replace(/"/g, '""')}"`, x.trains, Math.round(x.headway), Math.round(x.cycle), p.target, x.need, x.delta].join(',')));
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob); const a = document.createElement('a');
  a.href = url; a.download = `Headway planning_${p.targetMin} min.csv`; a.click(); URL.revokeObjectURL(url);
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
  if (!rows.length) { $('#analytics-list').innerHTML = "<div class=\"placeholder\">No matching timetables.</div>"; return; }
  $('#analytics-list').innerHTML = rows.map(r => {
    const win = (r.start === null || r.start === undefined) ? "No run segments" : `${secToClock(r.start)}–${secToClock(r.end)}`;
    const findingsHtml = r.findings.length ? r.findings.map(f => `<div class="finding ${f.severity}"><div><strong>${escapeHtml(f.title)}</strong><small>${escapeHtml(f.action || f.detail)}</small></div></div>`).join('') : "<div class=\"placeholder\">No diagnostic issues for this timetable.</div>";
    return `<details class="analytics-row ${r.risk}"><summary>
      <span class="a-name"><span class="risk-dot ${r.risk}"></span>${escapeHtml(r.name)}</span>
      <span class="a-cell">${r.shifts} departures / ${r.trains} trains</span>
      <span class="a-cell">${win}</span>
      <span class="a-cell">Headway ${minutesText(r.headway_median)}</span>
      <span class="a-cell">${r.days}/7 days</span>
      <span class="a-cell">${r.runs.toLocaleString()} sections</span>
    </summary><div class="analytics-detail">
      <div class="a-detail-grid">
        <div><small>Main passenger line</small><b>${escapeHtml(r.service_line || '—')}</b></div>
        <div><small>Phase</small><b>${({good:"Even",warning:"Partial overlap",critical:"All at the same point",not_applicable:"Not applicable",insufficient_data:"Insufficient samples"}[r.phase] || r.phase || '—')}</b></div>
        <div><small>Minimum headway</small><b>${minutesText(r.headway_min)}</b></div>
        <div><small>Depot line</small><b>${r.depot_lines} items</b></div>
        <div><small>Coverage</small><b>${r.day_names.length ? r.day_names.join(' ') : '—'}</b></div>
      </div>
      ${findingsHtml}
    </div></details>`;
  }).join('');
}
function exportReport(kind) {
  const a = state.analysis; if (!a) { toast("Run a health check first", true); return; }
  const rows = analyticsRows();
  const stamp = timestamp();
  let blob, filename;
  if (kind === 'csv') {
    const header = ["Timetable", "Risk", "Shifts", "Trains", "Main line", "First departure", "Last departure", "Median headway(min)", "Minimum headway(min)", "Days covered", "Run segments", "Depot line"];
    const csvRows = rows.map(r => [r.name, RISK_LABELS[r.risk] || r.risk, r.shifts, r.trains, r.service_line,
      secToClock(r.start), secToClock(r.end), r.headway_median != null ? (r.headway_median / 60).toFixed(1) : '',
      r.headway_min != null ? (r.headway_min / 60).toFixed(1) : '', r.days, r.runs, r.depot_lines]);
    const esc = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = '\ufeff' + [header, ...csvRows].map(line => line.map(esc).join(',')).join('\r\n');
    blob = new Blob([csv], { type: 'text/csv;charset=utf-8' }); filename = `Operating report_${stamp}.csv`;
  } else {
    blob = new Blob([JSON.stringify({ generated: new Date().toISOString(), export: a.export, health_score: a.health_score, analytics: a.analytics, schedules: rows }, null, 2)], { type: 'application/json' });
    filename = `Operating report_${stamp}.json`;
  }
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 500);
  toast(`Exported ${filename}`);
}
function renderRecoverTargets(a) {
  const targets = (a.health_schedules || []).filter(s => s.is_blank_template);
  const sel = $('#recover-target');
  sel.innerHTML = targets.length
    ? targets.map(s => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}${(s.lines || []).length ? ' · ' + escapeHtml((s.lines || []).slice(0, 2).join('、')) : ''}</option>`).join('')
    : "<option value=\"\">No blank templates available for recovery</option>";
  $('#find-reference-btn').disabled = !targets.length;
  $('#reference-list').innerHTML = "<div class=\"placeholder\">Select a target template, then Find historical fleets”.</div>";
  state.reference = null; $('#recover-btn').disabled = true;
  $('#recover-output').value = outputPath('Recovery');
}
function renderReference(result) {
  const list = result.candidates || [];
  state.reference = null; $('#recover-btn').disabled = true;
  if (!list.length) { $('#reference-list').innerHTML = "<div class=\"placeholder\">No matching historical fleet found.</div>"; return; }
  $('#reference-list').innerHTML = list.map((c, i) => {
    const when = c.export_modified_timestamp ? new Date(c.export_modified_timestamp * 1000).toLocaleString() : '';
    const file = (c.export || '').split(/[\\/]/).pop();
    return `<label class="pair-card"><input class="reference-check" type="radio" name="reference-pick" data-index="${i}" ${i === 0 ? 'checked' : ''}><div><div class="pair-route"><span>${escapeHtml(c.source)}</span><i></i><span>${escapeHtml(result.target)}</span></div><small>${escapeHtml(c.reason)} · ${c.train_count} Trains · ${escapeHtml(file)} · ${escapeHtml(when)}</small></div><span class="confidence">Match ${c.score}</span></label>`;
  }).join('');
  state.referenceCandidates = list;
  const pick = (i) => { const c = state.referenceCandidates[i]; state.reference = { export: c.export, source: c.source }; $('#recover-btn').disabled = false; };
  pick(0);
  $$('.reference-check').forEach(el => el.addEventListener('change', () => pick(+el.dataset.index)));
  toast(`Found ${list.length} historical fleet candidates; best match: ${result.best.source}`);
}
function renderFindingGroups(findings) {
  if (!findings.length) return "<div class=\"placeholder\">All checks passed; no issues need action.</div>";
  const groups = [['critical', "Critical issues"], ['warning', "Needs attention"], ['info', "Note"]];
  const findingCard = f => `<div class="finding ${f.severity}"><div><strong>${escapeHtml(f.title)}</strong><small>${escapeHtml(f.action || f.detail)}</small></div><span class="schedule-name">${escapeHtml(f.schedule || "Global checks")}</span></div>`;
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
  $('#repair-list').innerHTML = tasks.map(t => `<label class="schedule-option"><input class="repair-check" type="checkbox" data-repair-type="${escapeHtml(t.type)}" data-repair-value="${escapeHtml(t.type === 'retire_overlap' ? t.pair : t.schedule)}" ${t.selected_by_default ? 'checked' : ''}><span><strong>${escapeHtml(t.label)}</strong><small>Resolved: ${escapeHtml((t.resolves || []).join('、'))}</small></span></label>`).join('');
  refreshOutputNames();
  const btn = $('#fix-button');
  btn.disabled = !matched;
  btn.title = matched ? '' : "The save and export do not fully match. Resolve the mismatch before repairing";
}
function renderPairs(pairs) {
  $('#pair-count').textContent = pairs.length;
  $('#pair-list').innerHTML = pairs.length ? pairs.map((p, i) => `<label class="pair-card"><input class="pair-check" type="checkbox" data-pair="${escapeHtml(`${p.source}::${p.target}`)}" ${p.ready ? 'checked' : 'disabled'}><div><div class="pair-route"><span>${escapeHtml(p.source)}</span><i></i><span>${escapeHtml(p.target)}</span></div><small>${escapeHtml(p.reason)} · ${p.fleet_size} Trains</small></div><span class="confidence">${escapeHtml(p.confidence)}</span></label>`).join('') : "<div class=\"placeholder\">No ready-to-run migration plan found.</div>";
}
function renderSchedules(schedules) {
  const usable = schedules.filter(x => x.train_count > 0);
  $('#schedule-list').innerHTML = usable.length ? usable.map(s => `<label class="schedule-option"><input class="schedule-check" type="checkbox" value="${escapeHtml(s.name)}"><span><strong>${escapeHtml(s.name)}</strong><small>${s.train_count} trains · Enabled ${s.garage_enabled}</small></span></label>`).join('') : "<div class=\"placeholder\">No fleets available to configure.</div>";
}
function renderCleanup() {
  const c = state.cleanup; if (!c) return;
  $('#cleanup-summary').innerHTML = `<div class="clean-stat"><small>Verified toolkit copies</small><b>${c.completed_copy_count}</b></div><div class="clean-stat"><small>Copies retained by count</small><b>${c.protected_copy_count}</b></div><div class="clean-stat"><small>Eligible cleanup groups</small><b>${c.candidate_count}</b></div><div class="clean-stat"><small>Candidate size (Recycle Bin still uses disk space)</small><b>${formatBytes(c.candidate_bytes)}</b></div>`;
  $('#cleanup-list').innerHTML = c.targets.length ? c.targets.map((x,i) => `<label class="cleanup-item"><input type="checkbox" class="cleanup-select" data-clean-index="${i}"><div><strong>${escapeHtml(x.name)}</strong><small>${escapeHtml(x.reason)}</small><small>${escapeHtml(x.path)}</small></div><span>${formatBytes(x.bytes)}</span></label>`).join('') : "<div class=\"placeholder\">No files meet the current rules. Unrecorded, modified, selected or protected files are skipped. At least the newest file in each group is retained.</div>";
  $('#cleanup-protection').innerHTML = (c.copies || []).map(x => `<label class="cleanup-item"><input type="checkbox" data-protect-copy="${escapeHtml(x.name)}" ${x.pinned ? 'checked' : ''}><span><strong>${escapeHtml(x.name)}</strong><small>${x.pinned ? "Keep permanently" : x.eligible ? "Matches the creation record; eligible for cleanup" : "Missing creation record or changed content; skipped automatically"}</small></span></label>`).join('') || "<p>No toolkit copies identified.</p>";
  $('#cleanup-explanation').textContent = (state.cleanMode === 'compact' ? `Reduce stored copies: keep newest per group ${c.keep} files; no age filter for the rest.` : `By age: keep the newest in each group ${c.keep} files; only list those older than ${c.days} days old.`) + " Toolkit temporary files older than 1 hour are listed separately. Only selected items are moved. JSON exports never participate in startup cleanup.";
  syncCleanupSelection();
}

function cleanupOptions(){
  return {days:+$('#cleanup-days').value,keep:+$('#cleanup-keep').value,compact:state.cleanMode==='compact',
    include_maps:$('#cleanup-maps').checked,include_timetables:$('#cleanup-timetables').checked,
    protected_paths:[...new Set(['#save-select','#export-select','#compare-before','#compare-after','#netdiff-before','#netdiff-after'].map(id=>$(id)?.value).filter(Boolean))].sort()};
}
function cleanupChosen(){return $$('.cleanup-select:checked').map(box=>state.cleanup?.targets[Number(box.dataset.cleanIndex)]).filter(Boolean);}
function syncCleanupSelection(){
  $('#execute-cleanup').disabled=!!state.cleanupBusy||!!state.taskActive||!cleanupChosen().length||state.cleanupSignature!==JSON.stringify(cleanupOptions());
}
function invalidateCleanup(){state.cleanupSignature=null;$('#execute-cleanup').disabled=true;$('#cleanup-explanation').textContent="Cleanup options or selected files changed. Refresh the cleanup preview.";}
document.addEventListener('change',event=>{if(event.target.classList?.contains('cleanup-select'))syncCleanupSelection();});
document.addEventListener('change', async event => {
  const name = event.target.dataset?.protectCopy;
  if (!name) return;
  const checked = event.target.checked;
  event.target.disabled = true;
  try {
    await api('/api/cleanup/protect', {method:'POST', body:JSON.stringify({name, protected:checked})});
    await updateCleanupPreview(); toast(checked ? "Copy protected from cleanup" : "Protection removed; no cleanup performed");
  } catch(error) {event.target.checked = !checked; toast(error.message,true);}
  finally {event.target.disabled=false;}
});
function renderRoadmap(items) {
  const labels = {available:"Available",next:"Next stage",planned:"Planned",research:"Research phase"};
  $('#roadmap-list').innerHTML = items.map(x => `<article class="road-item ${x.status}"><div class="road-rank">${x.rank}</div><div><h3>${escapeHtml(x.name)}</h3><p>${escapeHtml(x.detail)}</p></div><span class="road-status">${labels[x.status]}</span></article>`).join('');
}
function renderInventory(result) {
  const summary = $('#inventory-summary');
  summary.className = 'metric-grid'; summary.hidden = false;
  summary.innerHTML = [
    ["Export count", (result.exports || []).length, "files"],
    ["Parallel workers", result.workers_used, "items"],
    ["Total time", `${result.elapsed_seconds}`, "s"],
    ["Logical cores", result.logical_cpu_count, "items"],
  ].map(x => `<div class="metric-card"><small>${x[0]}</small><b>${x[1]}</b><em>${x[2]}</em></div>`).join('');
  const rows = result.exports || [];
  $('#inventory-list').innerHTML = rows.length ? rows.map(r => {
    if (!r.ok) return `<div class="cleanup-item"><div><strong>${escapeHtml(r.name)}</strong><small class="danger-text">Read failed: ${escapeHtml(r.error || "Unknown error")}</small></div><span>${r.elapsed_seconds}s</span></div>`;
    const crit = r.severity_counts?.critical || 0, warn = r.severity_counts?.warning || 0;
    const critNames = (r.critical_schedules || []).length ? ` · Timetables with critical issues: ${escapeHtml(r.critical_schedules.slice(0,3).join('、'))}${r.critical_schedules.length>3?'…':''}` : '';
    return `<div class="cleanup-item"><div><strong>${escapeHtml(r.name)}</strong><small>Healthy ${r.health_score} · Critical ${crit} · Warning ${warn} · Source ${r.source_count} · Blank templates ${r.blank_template_count} · ${formatBytes(r.file_size)}${critNames}</small></div><span class="health-pill h${r.health_score>=90?'good':r.health_score>=70?'warn':'bad'}">${r.health_score}</span></div>`;
  }).join('') : "<div class=\"placeholder\">No historical exports in this directory.</div>";
  toast(`Inventory complete: ${rows.length} exports; using ${result.workers_used} workers; elapsed time ${result.elapsed_seconds}s`);
}
function changeLabel(change) { return { added:"Added", removed:"Remove", modified:"Edit" }[change] || change; }
function renderCompare(result) {
  const grid = `<div class="metric-grid"><div class="metric-card"><small>Older health score</small><b>${result.before_health_score}</b><em>min</em></div><div class="metric-card"><small>Newer health score</small><b>${result.after_health_score}</b><em>min</em></div><div class="metric-card"><small>Changed timetables</small><b>${result.change_count}</b><em>timetables</em></div><div class="metric-card"><small>New / resolved issues</small><b>${(result.new_findings||[]).length}/${(result.resolved_findings||[]).length}</b><em>items</em></div></div>`;
  const changes = (result.changes || []).map(c => {
    let detail = '';
    if (c.change === 'modified' && c.fields) {
      detail = Object.entries(c.fields).map(([k,v]) => `${escapeHtml(k)}: ${escapeHtml(JSON.stringify(v.before))} → ${escapeHtml(JSON.stringify(v.after))}`).join(' ; ');
    }
    return `<div class="cleanup-item"><div><strong>${escapeHtml(c.schedule)}</strong><small>${detail || '—'}</small></div><span class="change-tag ${c.change}">${changeLabel(c.change)}</span></div>`;
  }).join('') || "<div class=\"placeholder\">Both exports have identical timetable structures.</div>";
  const findingsBlock = (title, list, cls) => (list && list.length) ? `<div class="plan-section-title">${title}</div>` + list.map(f => `<div class="finding ${cls}"><div><strong>${escapeHtml(f.title)}</strong><small>${escapeHtml(f.schedule || "Global")}</small></div><span class="schedule-name">${escapeHtml(f.code)}</span></div>`).join('') : '';
  $('#compare-result').innerHTML = grid + `<div class="plan-section-title">Timetable changes</div>` + changes
    + findingsBlock("New issues", result.new_findings, 'critical')
    + findingsBlock("Resolved issues", result.resolved_findings, 'info');
  toast(`Comparison complete: ${result.change_count} timetables changed`);
}
function parseClock(value) { const [h,m]=value.split(':').map(Number); if(!Number.isFinite(h)||!Number.isFinite(m))throw new Error(`Invalid time format: ${value}`); return h*60+m; }
function clockText(minutes) { const normalized=((Math.round(minutes)%1440)+1440)%1440; return `${String(Math.floor(normalized/60)).padStart(2,'0')}:${String(normalized%60).padStart(2,'0')}`; }
function parseWindows(value) {
  return value.split(/[,，]/).map(x=>x.trim()).filter(Boolean).map(x=>{const parts=x.split('-').map(y=>y.trim());if(parts.length!==2)throw new Error(`Invalid peak-window format: ${x}`);let start=parseClock(parts[0]),end=parseClock(parts[1]);if(end<=start)end+=1440;return [start,end];});
}
function isPeakMinute(minute, windows) { const dayMinute=((minute%1440)+1440)%1440; return windows.some(([s,e])=>{if(e<=1440)return dayMinute>=s&&dayMinute<e;return dayMinute>=s||dayMinute<e-1440;}); }
function calculatePlan() {
  try {
    const name=$('#plan-name').value.trim()||"Unnamed plan"; let first=parseClock($('#plan-first').value),last=parseClock($('#plan-last').value);if(last<=first)last+=1440;
    const cycle=Number($('#plan-cycle').value),peak=Number($('#plan-peak').value),offpeak=Number($('#plan-offpeak').value),phase=Number($('#plan-phase').value)||0,windows=parseWindows($('#plan-windows').value);
    if([cycle,peak,offpeak].some(x=>!Number.isFinite(x)||x<=0))throw new Error("Cycle time and headway must be greater than 0");
    const departures=[];let minute=first+phase;let guard=0;while(minute<=last&&guard++<10000){const peakNow=isPeakMinute(minute,windows);departures.push({minute,peak:peakNow,time:clockText(minute)});minute+=peakNow?peak:offpeak;}
    const peakFleet=Math.ceil(cycle/peak),offpeakFleet=Math.ceil(cycle/offpeak);
    const fleet=Math.max(peakFleet,offpeakFleet);const spacing=cycle/fleet;const phases=Array.from({length:fleet},(_,i)=>i*spacing);
    const peakCount=departures.filter(x=>x.peak).length;
    state.plan={name,first:clockText(first),last:clockText(last),cycle_minutes:cycle,peak_headway_minutes:peak,offpeak_headway_minutes:offpeak,peak_windows:$('#plan-windows').value,phase_start_minutes:phase,minimum_fleet:fleet,peak_fleet:peakFleet,offpeak_fleet:offpeakFleet,uniform_phase_spacing_minutes:spacing,phase_offsets_minutes:phases,departure_count:departures.length,peak_departure_count:peakCount,departures};
    const phaseText=phases.map(x=>x.toFixed(1)).join(', ');
    const departureText=departures.map(x=>x.time).join(', ');
    state.planCopy={phases:phaseText,departures:departureText};
    $('#planner-results').innerHTML=`<div class="plan-stat-grid"><div class="plan-stat"><small>All-day departures</small><b>${departures.length}</b><em>peak ${peakCount}</em></div><div class="plan-stat"><small>Minimum peak fleet</small><b>${peakFleet} trains</b><em>Off-peak ${offpeakFleet} trains</em></div><div class="plan-stat"><small>Even departure offsets</small><b>${spacing.toFixed(1)} min</b><em>Total ${fleet} trains</em></div></div><div class="plan-section-title">Departure sequence <button class="text-button mini" data-copy="departures">Copy</button></div><div class="departure-cloud">${departures.map(x=>`<span class="departure ${x.peak?'peak':''}">${x.time}</span>`).join('')}</div><div class="plan-section-title">${fleet} Per-train departure offsets (min) <button class="text-button mini" data-copy="phases">Copy</button></div><div class="phase-table">${phases.map((x,i)=>`<span>${String(i+1).padStart(2,'0')} · +${x.toFixed(1)}</span>`).join('')}</div><p class="plan-note">Fleet size uses the full cycle ÷ headway, rounded up. Denser peak departures require more trains. Add spares and verify actual template running times in game. These offsets stagger trains on the same cycle; check orders and offset groups before use.</p>`;
  } catch(e){toast(e.message,true);}
}

function renderMapData(result) {
  state.mapSvg = null; state.metroLayout = null;
  state.mapBranchGroups = Object.create(null);
  $('#map-canvas').innerHTML = '';
  state.network = { lines: result.lines || [], stations: result.stations || {} };
  const lines = state.network.lines;
  state.mapSelected = new Set(lines.filter(l => l.stop_count > 1).map(l => String(l.id)));
  renderMapLineList();
  if (!lines.length) { $('#map-line-list').innerHTML = "<div class=\"placeholder\">No drawable lines in this export.</div>"; return; }
  $('#map-render-panel').hidden = false;
  drawTransitMap();
  toast(`Loaded ${lines.length} lines, ${result.station_count} stations`);
}
function filterMapLines(lines, stations, selected, query='', order='name-asc', onlySelected=false) {
  const words=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const compare=new Intl.Collator(globalThis.document?.documentElement?.lang || 'en',{numeric:true,sensitivity:'base'}).compare;
  const count=line=>line.stop_count ?? (line.stops || []).length;
  return lines.filter(line=>{
    if(onlySelected&&!selected.has(String(line.id)))return false;
    const text=[line.name,line.code,...(line.stops || []).map(id=>stations[id]?.name || '')].join(' ').toLocaleLowerCase();
    return words.every(word=>text.includes(word));
  }).sort((a,b)=>{
    const names=compare(a.name || '',b.name || '') || compare(String(a.id),String(b.id));
    if(order==='name-desc')return -names;
    if(order==='code-asc')return compare(a.code || a.name || '',b.code || b.name || '') || names;
    if(order==='stops-desc')return count(b)-count(a) || names;
    if(order==='stops-asc')return count(a)-count(b) || names;
    if(order==='selected-first')return Number(selected.has(String(b.id)))-Number(selected.has(String(a.id))) || names;
    return names;
  });
}
function visibleMapLines() {
  return filterMapLines(state.network?.lines || [],state.network?.stations || {},state.mapSelected || new Set(),
    $('#map-line-search').value,$('#map-line-sort').value,$('#map-only-selected').checked);
}
function renderMapLineList() {
  if(!state.network)return;
  const focused=document.activeElement?.classList.contains('map-line-check')?document.activeElement.value:null;
  const lines=visibleMapLines();
  $('#map-selection-summary').textContent=`Show ${lines.length} / ${state.network.lines.length} items · Total selected ${state.mapSelected.size} items`;
  $('#map-line-list').innerHTML = lines.map(l => {
    const c = lineColor(l.color);
    const service = l.stop_count > 1;
    const branch=state.mapBranchGroups?.[String(l.id)];
    const badge=branch?` · ${branch==='!independent'?"Keep separate":`Group: ${branch}`}`:'';
    return `<label class="map-line-option"><input class="map-line-check" type="checkbox" value="${escapeHtml(l.id)}" data-service="${service ? 1 : 0}" ${state.mapSelected.has(String(l.id)) ? 'checked' : ''}><span class="line-swatch" style="background:${c}"></span><span><strong>${escapeHtml(l.name)}</strong><small>${escapeHtml(l.code || '')}${l.code ? ' · ' : ''}${l.stop_count} stops ${escapeHtml(badge)}</small></span></label>`;
  }).join('') || "<div class=\"placeholder\">No matching lines. Change the search or disable Selected only. Existing selections are retained.</div>";
  if(focused!==null){const inputs=$$('.map-line-check');(inputs.find(el=>el.value===focused)||inputs[0]||$('#map-line-search')).focus({preventScroll:true});}
}
function selectVisibleMapLines(mode) {
  if(!state.mapSelected)return;
  visibleMapLines().forEach(line=>{
    const id=String(line.id);
    if(mode==='all'||(mode==='service'&&line.stop_count>1))state.mapSelected.add(id);
    else state.mapSelected.delete(id);
  });
  renderMapLineList();drawTransitMap();
}
function selectedMapLines() {
  return (state.network?.lines || []).filter(l => state.mapSelected?.has(String(l.id)));
}
function setMapBranchGroup(mode) {
  const lines=selectedMapLines(),name=$('#map-branch-name').value.trim();
  if(!lines.length)return toast("Select the lines to configure first.",true);
  if(mode==='group'&&(lines.length<2||!name||name==='!independent'))return toast("Select at least two branches and enter a valid group name.",true);
  state.mapBranchGroups ||= Object.create(null);
  for(const line of lines){
    if(mode==='auto')delete state.mapBranchGroups[String(line.id)];
    else state.mapBranchGroups[String(line.id)]=mode==='group'?name:'!independent';
  }
  $('#map-merge-branches').checked=true;
  renderMapLineList();drawTransitMap();
  toast(`Configured ${lines.length} lines, including selected lines hidden by search. Grouping affects only the metro diagram.`);
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
// Rough text width: CJK glyphs ~1em, ASCII ~0.56em. Good enough for layout.
function estTextWidth(text, fs) { let u = 0; for (const ch of String(text)) u += (ch.charCodeAt(0) > 255 ? 1 : 0.56); return u * fs; }
function rectsOverlap(a, b) { return !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y); }
function mapStyle() { return $('#map-style')?.value || 'geo'; }
function mapNum(id, def) { const v = parseFloat($('#' + id)?.value); return Number.isFinite(v) ? v : def; }
function mapOpts() {
  return {
    fontSize: Math.max(6, Math.min(40, mapNum('map-fontsize', 11))),
    width: Math.max(600, Math.min(6000, mapNum('map-width', 1400))),
    height: Math.max(400, Math.min(6000, mapNum('map-height', 940))),
    lineWidth: Math.max(1, Math.min(30, mapNum('map-linewidth', 6))),
    dotScale: Math.max(0.3, Math.min(4, mapNum('map-dotscale', 1))),
    gap: Math.max(24, Math.min(200, mapNum('map-gap', 66))),
  };
}
function drawTransitMap() {
  try {
    drawTransitMapContent();
    const status=$('#map-render-status');
    if(status)status.textContent=state.mapSvg?`Drawn ${selectedMapLines().filter(l=>l.stops.length>=2).length} operating lines ${state.metroLayout?`, Display as ${state.metroLayout.display_lines.length} line groups`:''} · ${state.metroLayout?(state.metroLayout.layout==='grid'?"Grid layout":state.metroLayout.theme==='atlas'?"Railway overview":"Urban metro"):"Line diagram"}. Change zoom or export SVG.`:$('#map-canvas').textContent;
    if(status&&state.metroLayout?.label_leader_crossings)status.textContent+=` ${state.metroLayout.label_leader_crossings} label leader lines still have nearby obstacles; zoom in or adjust station spacing.`;
  } catch(error) {
    state.mapSvg=null;state.metroLayout=null;
    $('#map-canvas').textContent="Drawing did not finish. Try fewer selected lines, or report the diagnostic details below.";
    const status=$('#map-render-status');if(status)status.textContent=`Drawing failed: ${error.message}`;
    console.error('Transit map rendering failed',error);toast(`Route-map drawing failed: ${error.message}`,true);
  }
}
function drawTransitMapContent() {
  if (!state.network) {state.mapSvg=null;state.metroLayout=null;$('#map-canvas').textContent="Load lines from game timetable data first.";return;}
  const stations = state.network.stations;
  const lines = selectedMapLines().filter(l => l.stops.length >= 2);
  const canvas = $('#map-canvas');
  if (!lines.length) { state.mapSvg=null; state.metroLayout=null; canvas.innerHTML = "<div class=\"placeholder\">Select at least one line with 2 or more stops.</div>"; return; }
  if (mapStyle() === 'strip') { state.metroLayout=null; drawStripDiagram(lines, stations); applyMapZoom(); return; }
  if (mapStyle() === 'metro') { drawMetroDiagram(lines, stations); applyMapZoom(); return; }
  state.metroLayout = null;
  const usedIds = [...new Set(lines.flatMap(l => l.stops))].filter(id => stations[id]);
  if (!usedIds.length) { state.mapSvg=null; state.metroLayout=null; canvas.innerHTML = "<div class=\"placeholder\">Selected lines have stations without coordinates.</div>"; return; }
  const lats = usedIds.map(id => stations[id].lat);
  const meanLat = lats.reduce((a, b) => a + b, 0) / lats.length;
  const k = Math.cos(meanLat * Math.PI / 180);
  const schematic = mapStyle() === 'schematic';
  const raw = {};
  usedIds.forEach(id => { raw[id] = { x: stations[id].lon * k, y: -stations[id].lat }; });
  if (schematic) octilinearize(raw, lines, usedIds);
  const o = mapOpts();
  const xs = usedIds.map(id => raw[id].x), ys = usedIds.map(id => raw[id].y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = o.width, H = o.height, pad = Math.max(60, o.fontSize * 5);
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
  // Catmull-Rom spline -> cubic Béziers. Unlike the old quadratic version, this
  // interpolates *through* every station point, so the curve always sits exactly
  // on the dots (smoothing only bends the segments between stations).
  const pathFor = pts2 => {
    if (!curved || pts2.length < 3) return pts2.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
    let d = `M${pts2[0].x.toFixed(1)} ${pts2[0].y.toFixed(1)}`;
    for (let i = 0; i < pts2.length - 1; i++) {
      const p0 = pts2[i - 1] || pts2[i], p1 = pts2[i], p2 = pts2[i + 1], p3 = pts2[i + 2] || p2;
      const cp1x = p1.x + (p2.x - p0.x) / 6, cp1y = p1.y + (p2.y - p0.y) / 6;
      const cp2x = p2.x - (p3.x - p1.x) / 6, cp2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C${cp1x.toFixed(1)} ${cp1y.toFixed(1)} ${cp2x.toFixed(1)} ${cp2y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
    }
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
    path.setAttribute('stroke-width', o.lineWidth);
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('opacity', '0.92');
    svg.appendChild(path);
  });
  // Which stations get labelled: termini + interchanges always; the rest only
  // when "显示所有站名" is on.
  const labelIds = new Set();
  lines.forEach(l => { const s = l.stops.filter(id => stations[id]); if (s.length) { labelIds.add(s[0]); labelIds.add(s[s.length - 1]); } });
  Object.keys(usage).forEach(id => { if (usage[id] > 1) labelIds.add(id); });
  // Reserved boxes act as obstacles for label placement (dots + legend).
  const obstacles = [];
  // Legend, drawn first so labels can route around it.
  const legendX = 24, legendY = 30;
  let legendMaxW = 0;
  lines.forEach((l, i) => {
    const y = legendY + i * 24;
    const sw = document.createElementNS(SVG_NS, 'rect');
    sw.setAttribute('x', legendX); sw.setAttribute('y', y - 11); sw.setAttribute('width', 26); sw.setAttribute('height', 8); sw.setAttribute('rx', 4);
    sw.setAttribute('fill', lineColor(l.color)); svg.appendChild(sw);
    const t = document.createElementNS(SVG_NS, 'text');
    t.setAttribute('x', legendX + 34); t.setAttribute('y', y); t.setAttribute('class', 'legend-label');
    const label = `${l.name}${l.code ? ' (' + l.code + ')' : ''}`;
    t.textContent = label; svg.appendChild(t);
    legendMaxW = Math.max(legendMaxW, 34 + estTextWidth(label, 13));
  });
  if (lines.length) obstacles.push({ x: legendX - 8, y: legendY - 20, w: legendMaxW + 16, h: lines.length * 24 + 8 });
  // Station dots (drawn under the labels), each reserved as an obstacle.
  usedIds.forEach(id => {
    const p = project(id); const interchange = usage[id] > 1;
    const rr = (interchange ? 6 : 3.2) * o.dotScale;
    const dot = document.createElementNS(SVG_NS, 'circle');
    dot.setAttribute('cx', p.x.toFixed(1)); dot.setAttribute('cy', p.y.toFixed(1));
    dot.setAttribute('r', rr.toFixed(1));
    dot.setAttribute('fill', interchange ? '#ffffff' : '#0b1d2a');
    dot.setAttribute('stroke', interchange ? '#0b1d2a' : '#ffffff');
    dot.setAttribute('stroke-width', (interchange ? 2.4 : 1.2) * o.dotScale);
    svg.appendChild(dot);
    obstacles.push({ x: p.x - rr, y: p.y - rr, w: rr * 2, h: rr * 2 });
  });
  // Greedy label placement: important labels first, each tries several anchors
  // and takes the first that clears every other label + obstacle. Minor labels
  // that can't fit are dropped so the map stays readable instead of overlapping.
  const wantIds = usedIds.filter(id => allLabels || labelIds.has(id));
  const priority = id => (usage[id] > 1 ? 2 : (labelIds.has(id) ? 1 : 0));
  wantIds.sort((a, b) => priority(b) - priority(a));
  const placed = [];
  wantIds.forEach(id => {
    const p = project(id); const interchange = usage[id] > 1;
    const fs = interchange ? o.fontSize + 1 : o.fontSize;
    const name = stations[id].name;
    const w = estTextWidth(name, fs), h = fs * 1.2;
    const off = (interchange ? 9 : 6) * o.dotScale;
    // [dx, dy(baseline), anchor]; ordered by visual preference.
    const cands = [
      [off, -off, 'start'], [-off, -off, 'end'],
      [off, off + h * 0.5, 'start'], [-off, off + h * 0.5, 'end'],
      [0, -off - 2, 'middle'], [0, off + h * 0.7, 'middle'],
      [off + 3, fs * 0.35, 'start'], [-off - 3, fs * 0.35, 'end'],
    ];
    const boxFor = (dx, dy, anchor) => {
      const left = anchor === 'start' ? p.x + dx : anchor === 'end' ? p.x + dx - w : p.x + dx - w / 2;
      return { x: left, y: p.y + dy - fs * 0.8, w, h };
    };
    let chosen = null;
    for (const [dx, dy, anchor] of cands) {
      const box = boxFor(dx, dy, anchor);
      if (!placed.some(q => rectsOverlap(box, q)) && !obstacles.some(q => rectsOverlap(box, q))) {
        chosen = { dx, dy, anchor, box }; break;
      }
    }
    if (!chosen) {
      if (priority(id) === 0) return; // drop only unimportant labels
      const dx = off, dy = -off, anchor = 'start';
      chosen = { dx, dy, anchor, box: boxFor(dx, dy, anchor) };
    }
    placed.push(chosen.box);
    const t = document.createElementNS(SVG_NS, 'text');
    t.setAttribute('x', (p.x + chosen.dx).toFixed(1)); t.setAttribute('y', (p.y + chosen.dy).toFixed(1));
    t.setAttribute('text-anchor', chosen.anchor);
    t.setAttribute('class', interchange ? 'st-label major' : 'st-label');
    t.setAttribute('style', `font-size:${fs.toFixed(1)}px`); // inline wins over CSS class
    t.textContent = name;
    svg.appendChild(t);
  });
  canvas.innerHTML = '';
  canvas.appendChild(svg);
  state.mapSvg = svg;
  applyMapZoom();
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
  if (!rows.length) { canvas.innerHTML = "<div class=\"placeholder\">Selected lines have stations without coordinates.</div>"; return; }
  const maxStops = Math.max(...rows.map(r => r.stops.length));
  const o = mapOpts();
  const FONT = '"Microsoft YaHei UI","Segoe UI",sans-serif';
  const gap = o.gap, dotR = 8 * o.dotScale, stripLW = o.lineWidth * 2, dotSW = 3 * o.dotScale;
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
  const lineFS = o.fontSize, badgeFS = Math.max(9, o.fontSize - 3), nameFS = o.fontSize;
  const dot = (cx, cy, term, inter, color) => {
    svg.appendChild(svgEl('circle', { cx: cx.toFixed(1), cy: cy.toFixed(1), r: (term ? dotR + 2 : (inter ? dotR : 5.5 * o.dotScale)).toFixed(1), fill: term ? color : '#ffffff', stroke: color, 'stroke-width': dotSW.toFixed(1) }));
    if (inter) svg.appendChild(svgEl('circle', { cx: cx.toFixed(1), cy: cy.toFixed(1), r: (2.6 * o.dotScale).toFixed(1), fill: color }));
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
      svg.appendChild(svgEl('line', { x1: leftPad, y1: yMid, x2: x1, y2: yMid, stroke: color, 'stroke-width': stripLW, 'stroke-linecap': 'round' }));
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
      svg.appendChild(svgEl('line', { x1: xMid, y1: topPad, x2: xMid, y2: y1, stroke: color, 'stroke-width': stripLW, 'stroke-linecap': 'round' }));
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
  clone.removeAttribute('style'); // Preview zoom is not part of exported artwork.
  const css = 'text.st-label{font:11px "Segoe UI",sans-serif;fill:#0b1d2a;paint-order:stroke;stroke:#fff;stroke-width:3px;}text.st-label.major{font-weight:700;font-size:12px;}text.legend-label{font:13px "Segoe UI",sans-serif;fill:#0b1d2a;}';
  const style = document.createElementNS(SVG_NS, 'style'); style.textContent = css; clone.insertBefore(style, clone.firstChild);
  return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(clone);
}
async function exportMapSvg() {
  if (!state.mapSvg) { toast("Draw a route map first", true); return; }
  const data = buildMapSvgData();
  const filename = `Route maps_${timestamp()}.svg`;
  // Save through the local service so it reliably lands on disk in the desktop
  // window (WebView2 often ignores JS blob downloads); show the full path.
  try {
    const res = await api('/api/map/export', { method: 'POST', body: JSON.stringify({ svg: data, filename, format: 'svg' }) });
    $('#map-export-status').textContent = `Saved: ${res.path}`;
    toast(`Saved: ${res.path}`);
    return;
  } catch (e) {
    toast(`Export failed: ${e.message}`, true);
  }
}
function buildMapJsonData() {
  const lines = selectedMapLines();
  if (!lines.length) throw Error("Load the network and select lines to export first");
  const ids = new Set(lines.flatMap(line => line.stops || []));
  const stations = Object.fromEntries(Object.entries(state.network.stations).filter(([id]) => ids.has(id)));
  return {schema:'nimby-toolkit-line-map.v1', exported_at:new Date().toISOString(),
    schematic_layout: mapStyle() === 'metro' ? state.metroLayout || null : null,
    toolkit_version:state.bootstrap?.app_version || '', lines, stations,
    missing_station_ids:[...ids].filter(id=>!stations[id]),
    drawing:{style:mapStyle(), metro_theme:$('#map-metro-theme').value, metro_orientation:$('#map-metro-orientation').value, metro_layout:$('#map-metro-layout').value, merge_branches:$('#map-merge-branches').checked, branch_groups:{...state.mapBranchGroups}, transfer_style:$('#map-transfer-style').value, orientation:$('#map-orient').value,
      all_labels:$('#map-all-labels').checked, curved:$('#map-curved').checked, ...mapOpts()}};
}
async function exportMapJson() {
  try {
    const res = await api('/api/map/export', {method:'POST', body:JSON.stringify({
      format:'json', filename:`Route maps_${timestamp()}.json`, data:buildMapJsonData()})});
    $('#map-export-status').textContent = `Saved: ${res.path}`;
    toast(`Saved: ${res.path}`);
  } catch(e) { toast(`Export failed: ${e.message}`,true); }
}
async function saveMapExportFolder(reset=false) {
  try {
    const res = await api('/api/settings',{method:'POST',body:JSON.stringify({
      map_export_dir:reset ? '' : $('#map-export-dir').value.trim()})});
    const folder = res.settings.map_export_dir;
    if (folder) $('#map-export-dir').value = folder;
    else { const data=await api('/api/bootstrap'); $('#map-export-dir').value=data.map_export_dir; }
    $('#map-export-status').textContent = `Export folder saved: ${$('#map-export-dir').value}`;
    toast("Route-map export folder saved; applies only to this page's SVG and map JSON exports");
  } catch(e) { toast(`Folder not saved: ${e.message}`,true); }
}
function renderNetworkDiff(r) {
  const grid = `<div class="metric-grid"><div class="metric-card"><small>Line changes</small><b>${r.line_change_count}</b><em>items</em></div><div class="metric-card"><small>Station changes</small><b>${r.station_change_count}</b><em>items</em></div><div class="metric-card"><small>Older network</small><b>${r.before_summary.lines}/${r.before_summary.stations}</b><em>Lines / stations</em></div><div class="metric-card"><small>Newer network</small><b>${r.after_summary.lines}/${r.after_summary.stations}</b><em>Lines / stations</em></div></div>`;
  const tag = { added: 'added', removed: 'removed', modified: 'modified', renamed: 'modified', moved: 'modified' };
  const label = { added: "Added", removed: "Remove", modified: "Edit", renamed: "Rename", moved: "Move" };
  const row = c => `<div class="cleanup-item"><div><strong>${escapeHtml(c.name)}</strong><small>${escapeHtml(c.detail || '—')}</small></div><span class="change-tag ${tag[c.change]}">${label[c.change]}</span></div>`;
  const block = (title, list) => list.length ? `<div class="plan-section-title">${title}</div>` + list.map(row).join('') : '';
  const body = block("Line changes", r.line_changes) + block("Station changes", r.station_changes)
    || "<div class=\"placeholder\">Both exports have identical lines and stations.</div>";
  $('#netdiff-result').innerHTML = grid + body;
  toast(`Network comparison complete: ${r.line_change_count} lines, ${r.station_change_count} stations changed`);
}
// ---- Real-world reference map (Leaflet + OpenRailwayMap overlay) ----------
const REALNET = { map: null, ready: false, gameLayer: null, ormLayer: null, baseLayers: {}, pinLayer: null, pins: [], loader: null, trackLayer: null, trackRenderer: null };
function loadJson(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; } }
function saveJson(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {} }
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (REALNET.loader) return REALNET.loader;
  REALNET.loader = new Promise((resolve, reject) => {
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'; document.head.appendChild(css);
    const js = document.createElement('script'); js.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    js.onload = () => resolve(); js.onerror = () => reject(new Error("Leaflet could not load. Check your connection and retry")); document.head.appendChild(js);
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
function realnetDrawSignals() {
  if (!REALNET.ready || !REALNET.map) return;
  if (!REALNET.signalLayer) REALNET.signalLayer = L.layerGroup().addTo(REALNET.map);
  REALNET.signalLayer.clearLayers();
  const show = $('#realnet-show-signals')?.checked;
  if (!show || !state.signals || !state.signals.length) return;
  state.signals.forEach(s => {
    L.circleMarker([s.lat, s.lon], { radius: 2, color: '#c0392b', weight: 1, fillColor: '#e74c3c', fillOpacity: 0.8 })
      .addTo(REALNET.signalLayer);
  });
}
function realnetDrawTracks() {
  if (!REALNET.ready || !REALNET.map) return;
  // Canvas renderer keeps a complete, developed save's ~20k edges smooth.
  if (!REALNET.trackRenderer) REALNET.trackRenderer = L.canvas({ padding: 0.5 });
  if (!REALNET.trackLayer) REALNET.trackLayer = L.layerGroup().addTo(REALNET.map);
  REALNET.trackLayer.clearLayers();
  const show = $('#realnet-show-tracks')?.checked;
  const segs = state.trackSegments;
  if (!show || !segs || !segs.length) return;
  segs.forEach(s => {
    L.polyline([[s[1], s[0]], [s[3], s[2]]], {
      color: '#6b7a83', weight: 1.4, opacity: 0.7, renderer: REALNET.trackRenderer, interactive: false,
    }).addTo(REALNET.trackLayer);
  });
}
function onTrackGeometry(result) {
  state.trackSegments = result.segments || [];
  state.trackDiagnostics = result;
  const levels = Object.entries(result.level_counts || {})
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([level, count]) => `L${level}:${count}`)
    .join(' / ');
  const el = $('#realnet-read-count');
  if (el) {
    el.textContent = `Actual tracks: ${result.node_count} Nodes · ${result.segment_count} sections · ${result.total_length_km} km`
      + (levels ? ` · Level ${levels}` : '')
      + (result.long_segment_count ? ` · Persistent connections ${result.long_segment_count}` : '');
  }
  const box = $('#realnet-show-tracks'); if (box && !box.checked) box.checked = true;
  if (REALNET.ready) realnetDrawTracks();
  const issues = (result.unresolved_connection_count || 0)
    + (result.nonreciprocal_connection_count || 0)
    + (result.distance_filtered_segment_count || 0)
    + (result.duplicate_record_count || 0);
  toast(`Read complete track geometry: ${result.node_count} Nodes / ${result.segment_count} sections / ${result.total_length_km} km`
    + (issues ? `(Checks ${issues}）` : "(Topology check passed)"), !!issues);
}
function calcHeadwayPlan() {
  const targetMin = +$('#headway-target').value;
  if (!(targetMin > 0)) { toast("Enter a valid target headway (min)", true); return; }
  const targetSec = targetMin * 60;
  const onlyService = $('#headway-only-service').checked;
  const rows = [];
  const a = state.analysis;
  if (a && (a.health_schedules || []).length) {
    // Preferred: JSON deep-check gives a measured headway per schedule.
    for (const s of a.health_schedules) {
      const N = s.train_count || 0;
      const h = (s.operations || {}).headway_median_seconds;
      if (!N || !h) continue;
      if (onlyService && !(s.operations || {}).service_line) continue;
      const T = h * N;                      // cycle time is invariant of N
      const need = Math.max(1, Math.ceil(T / targetSec));
      rows.push({ name: s.name, N, h, T, need, delta: need - N });
    }
  } else if (state.saveHealth && (state.saveHealth.ops_routes || []).length) {
    // JSON-free: cycle time T and train count N read straight from the save.
    for (const r of state.saveHealth.ops_routes) {
      const N = r.train_count || 0, T = r.cycle_seconds || 0;
      if (!N || !T) continue;
      const h = r.headway_estimate_seconds || Math.round(T / N);
      const need = Math.max(1, Math.ceil(T / targetSec));
      rows.push({ name: r.name, N, h, T, need, delta: need - N });
    }
  } else { toast("Run a health check in Overview & health first; the no-JSON check is sufficient)", true); return; }
  rows.sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta) || y.N - x.N);
  state.headwayPlan = { targetMin, rows };
  const add = rows.filter(r => r.delta > 0).reduce((s, r) => s + r.delta, 0);
  const rem = rows.filter(r => r.delta < 0).reduce((s, r) => s - r.delta, 0);
  $('#headway-summary').innerHTML = rows.length
    ? `<span>Target headway <strong>${targetMin} min</strong></span> · <span>${rows.length} lines</span> · <span class="hw-add">Add ${add} trains</span> · <span class="hw-rem">Reduce by ${rem} trains</span>`
    : "<span class=\"placeholder\">No passenger timetables available for planning; assigned fleets and measurable headways are required).</span>";
  const fmt = sec => sec >= 3600 ? `${(sec / 3600).toFixed(1)}h` : `${Math.round(sec / 60)} min`;
  $('#headway-rows').innerHTML = rows.map(r => {
    const cls = r.delta > 0 ? 'hw-add' : (r.delta < 0 ? 'hw-rem' : 'hw-ok');
    const txt = r.delta > 0 ? `+${r.delta}` : (r.delta < 0 ? `${r.delta}` : '±0');
    return `<tr><td>${escapeHtml(r.name)}</td><td>${r.N}</td><td>${fmt(r.h)}</td><td>${fmt(r.T)}</td><td>${$('#headway-target').value} min</td><td>${r.need}</td><td class="${cls}">${txt}</td></tr>`;
  }).join('');
  $('#headway-table').hidden = rows.length === 0;
  $('#headway-export').hidden = rows.length === 0;
  if (rows.length) toast(`Using target headway ${targetMin} min planned ${rows.length} lines`);
}
function exportHeadwayPlan() {
  const p = state.headwayPlan; if (!p || !p.rows.length) return;
  const head = ['schedule', 'current_trains', 'current_headway_s', 'cycle_time_s', 'target_headway_s', 'required_trains', 'delta'];
  const lines = [head.join(',')].concat(p.rows.map(r =>
    [`"${r.name.replace(/"/g, '""')}"`, r.N, r.h, r.T, p.targetMin * 60, r.need, r.delta].join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = `Headway planning_${p.targetMin} min.csv`;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Headway plan exported CSV");
}
function renderSaveOverview(r) {
  state.saveOverview = r;
  const c = r.counts || {};
  const metrics = [
    ["Stations", c.stations, `including ${c.named_stations} Named`],
    ["Lines", c.routes, "Includes track paths"],
    ["Timetable", c.schedules, `${c.active_schedules ?? 0} Has shifts`],
    ["Trains", c.trains, `${c.assigned_trains ?? 0} Assigned`],
    ["Shifts", c.total_shifts ?? 0, "items"],
    ["Signals / points", c.signals, "items"],
    ["Tags", c.tags ?? 0, "Category"],
  ];
  const mg = $('#overview-metrics');
  mg.innerHTML = metrics.map(x => `<div class="metric-card"><small>${x[0]}</small><b>${(x[1] ?? 0).toLocaleString()}</b><em>${x[2]}</em></div>`).join('');
  mg.hidden = false;
  renderOverviewHealth(r.health, c);
  const ver = (r.save_format_version_hint || []).join('.');
  const when = r.modified_utc ? new Date(r.modified_utc).toLocaleString() : '';
  $('#overview-meta').innerHTML = `<span>Save: <strong>${escapeHtml(r.save_name || '')}</strong></span> · <span>${formatBytes(r.file_size || 0)}</span>${ver ? ` · <span>Format marker ${escapeHtml(ver)}</span>` : ''}${when ? ` · <span>Modified ${escapeHtml(when)}</span>` : ''}`;
  const routes = r.routes || [], containers = r.containers || [];
  const swatch = col => `<i class="ov-swatch" style="background:${lineColor(col)}"></i>`;
  const tbadge = x => x.train_count ? `<span>${x.train_count} trains</span>` : '';
  const cbadge = x => x.cycle_seconds ? `<span title="Line-template duration (follow the stop sequence; it may not be a full round trip)">${durText(x.cycle_seconds)}</span>` : '';
  const sbadge = x => x.is_service ? `<span class="ov-svc" title="via route↔service links identify operating timetables serving ${x.served_lines} lines">Operations·${x.served_lines} lines</span>` : '';
  $('#overview-routes').innerHTML = routes.length ? routes.map(x => `<div class="ov-row">${swatch(x.color)}<strong>${escapeHtml(x.name)}</strong>${sbadge(x)}${tbadge(x)}${cbadge(x)}<span>${x.stop_count} stops</span></div>`).join('') : "<div class=\"placeholder\">None</div>";
  $('#overview-containers').innerHTML = containers.length ? containers.map(x => `<div class="ov-row">${swatch(x.color)}<strong>${escapeHtml(x.name)}</strong>${sbadge(x)}${tbadge(x)}</div>`).join('') : "<div class=\"placeholder\">None</div>";
  $('#overview-route-count').textContent = routes.length;
  $('#overview-container-count').textContent = containers.length;
  $('#overview-lists').hidden = false;
  toast(`Structure loaded: ${c.stations} stops / ${c.routes} lines / ${c.schedules} Timetable / ${c.trains} trains / ${c.signals} Signals`);
}
function renderOverviewHealth(h, c) {
  const box = $('#overview-health'); if (!box) return;
  if (!h) { box.hidden = true; return; }
  const sc = h.health_score ?? 100;
  const cls = sc >= 90 ? 'good' : sc >= 70 ? 'warn' : 'bad';
  const sev = h.severity_counts || {};
  const findings = h.findings || [];
  const items = findings.length
    ? findings.map(f => `<div class="ovh-item ovh-${f.severity}"><span class="ovh-dot"></span><div><strong>${escapeHtml(f.title)}</strong><small>${escapeHtml(f.detail || '')}</small></div></div>`).join('')
    : "<div class=\"ovh-item ovh-ok\"><span class=\"ovh-dot\"></span><div><strong>No structural issues</strong><small>No reliably detectable issues found in the direct-save check.</small></div></div>";
  box.innerHTML = `<div class="ovh-head">
      <div class="health-ring ovh-ring ${cls}" style="--score:${sc}"><div><b>${sc}</b><small>/ 100</small></div></div>
      <div class="ovh-meta">
        <strong>Direct-save health check · No JSON</strong>
        <p>${c.active_schedules ?? 0} active timetables (via route↔service link analysis), serving ${h.schedules_with_trains ?? 0} items · Critical ${sev.critical || 0} · Warning ${sev.warning || 0} · Note ${sev.info || 0}</p>
        <em>${escapeHtml(h.note || '')}</em>
      </div>
    </div>
    <div class="ovh-list">${items}</div>`;
  box.hidden = false;
}
function renderSaveHealth(r) {
  state.saveHealth = r;
  state.gameVersion = r.game_version || null;
  const gv = r.game_version || {};
  const c = r.counts || {};
  const h = r.health || {};
  const sc = h.health_score ?? 100;
  const cls = sc >= 90 ? 'ok' : sc >= 70 ? 'warn' : 'bad';
  const sev = h.severity_counts || {};
  const opsMed = (r.ops_summary || {}).headway_estimate_median_seconds;
  $('#health-summary').innerHTML = `<div class="health-wrap">`
    + `<div class="health-ring ${cls}" style="--score:${sc}"><div><b>${sc}</b><small>/ 100</small></div></div>`
    + `<div class="health-copy"><strong>Direct-save health check · No JSON</strong>`
    + `<p>${c.routes ?? 0} lines / ${c.schedules ?? 0} Timetable / ${c.trains ?? 0} trains(${c.assigned_trains ?? 0} Assigned)<br>Critical ${sev.critical || 0} · Warning ${sev.warning || 0} · Note ${sev.info || 0}</p>`
    + `<span class="ver-chip ${gv.safe_to_write ? 'ok' : 'warn'}" title="${escapeHtml(gv.note || "Version not checked")}">${escapeHtml(gv.save_release || "Unknown version")} · ${gv.safe_to_write ? "Save format verified" : "Read-only checks"}</span></div></div>`;
  const metrics = [
    ["Stations", c.stations, `${c.named_stations ?? 0} Named`],
    ["Lines", c.routes, "Includes track paths"],
    ["Timetable", c.schedules, `${c.active_schedules ?? 0} Has shifts`],
    ["Trains", c.trains, `${c.idle_trains ?? 0} Idle`],
    ["Signals / points", c.signals, "items"],
    ["Median headway(Estimate)", headwayText(opsMed || 0), 'h≈T/N'],
  ];
  $('#metric-grid').innerHTML = metrics.map(x => `<div class="metric-card"><small>${x[0]}</small><b>${typeof x[1]==='number' ? (x[1] ?? 0).toLocaleString() : x[1]}</b><em>${x[2]}</em></div>`).join('');
  $('#metric-grid').hidden = false;
  const findings = h.findings || [];
  $('#finding-count').textContent = findings.length;
  $('#findings-panel').hidden = false;
  $('#finding-list').innerHTML = renderFindingGroups(findings);
  // Re-use the existing detailed renderers: save-health is a superset of both.
  renderSaveOverview(r);
  renderOpsAnalyze({ action: 'ops-analyze', routes: r.ops_routes || [], summary: r.ops_summary || {} });
  const unnamed = Math.max(0, (c.stations ?? 0) - (c.named_stations ?? 0));
  const snc = $('#stationname-count');
  if (snc) snc.textContent = `Unnamed station: ${unnamed}`;
  toast(`Direct-save health check complete: ${c.routes ?? 0} lines / ${c.trains ?? 0} trains · Health ${sc}`);
}
function onStationNamesDone(result) {
  if(window.stationNamesResult)return window.stationNamesResult(result);
  const box = $('#stationname-result');
  if (!box) return;
  const changed = result.changed_count || 0;
  const skipped = result.skipped_count || 0;
  const out = (result.output_save || '').split(/[\\/]/).pop();
  const sample = (result.changes || []).slice(0, 8)
    .map(c => `${escapeHtml(c.new_name)}`).join('、');
  box.hidden = false;
  box.innerHTML = `<strong>Written ${changed} real station names</strong>(Skip ${skipped} named)`
    + `<p>New save: <code>${escapeHtml(out || '')}</code></p>`
    + (sample ? `<p class="save-dir-hint">Example: ${sample}${changed > 8 ? ' …' : ''}</p>` : '')
    + `<p class="save-dir-hint">Load the new save in game and confirm stations show names rather than numeric IDs.</p>`;
  toast(`Station names written: ${changed} stations`);
}
function syncStationNameExport(followSource=false) {
  const src = $('#export-select'), dst = $('#stationname-export');
  if (src && dst) { const old=dst.value; dst.innerHTML = src.innerHTML; dst.value = !followSource&&[...dst.options].some(o=>o.value===old)?old:src.value; }
}
function onNetworkRead(result) {
  state.network = { lines: result.lines || [], stations: result.stations || {} };
  state.allStations = result.all_stations || result.stations || {};
  state.signals = result.signals || [];
  const c = result;
  state.savereaderTrains = result.trains || [];
  const el = $('#realnet-read-count');
  const trainTxt = c.train_count != null ? ` · ${c.train_count} trains` : '';
  const schedTxt = c.schedule_count != null ? ` · ${c.schedule_count} Timetable` : '';
  if (el) el.textContent = `Direct read: ${c.line_count} lines · ${c.station_count} stops · ${c.signal_count} Signals ${trainTxt}${schedTxt}`;
  renderBinderLines();
  populateAlignStations();
  if (REALNET.ready) { realnetDrawGame(); realnetDrawSignals(); }
  toast(`Read directly from save: ${c.line_count} lines / ${c.station_count} stops / ${c.signal_count} Signals ${c.train_count != null ? ' / ' + c.train_count + " trains" : ''}${c.schedule_count != null ? ' / ' + c.schedule_count + " Timetable" : ''}`);
}
function populateAlignStations() {
  const sel = $('#align-station'); if (!sel) return;
  const st = state.allStations || {};
  const ids = Object.keys(st).sort((a, b) => (st[a].name || '').localeCompare(st[b].name || ''));
  if (!ids.length) { sel.innerHTML = "<option value=\"\">Read the network first…</option>"; return; }
  sel.innerHTML = ids.map(id => `<option value="${escapeHtml(id)}">${escapeHtml(st[id].name)} (${st[id].lon.toFixed(4)}, ${st[id].lat.toFixed(4)})</option>`).join('');
}
function renderAlignList() {
  const box = $('#align-list'); if (!box) return;
  const list = state.alignList || [];
  box.innerHTML = list.length
    ? list.map((a, i) => `<div class="realnet-pin-row"><div><strong>${escapeHtml(a.name)}</strong><small>→ ${a.lon}, ${a.lat}</small></div><div class="realnet-pin-acts"><button class="text-button danger-text" data-align-del="${i}">Remove</button></div></div>`).join('')
    : "<div class=\"placeholder\">No stations queued for alignment.</div>";
  const has = list.length > 0;
  $('#align-generate').disabled = !has;
  $('#align-clear').disabled = !has;
}
function alignAdd() {
  const sel = $('#align-station'); const id = sel?.value;
  if (!id) { toast("Read the network and select a station first", true); return; }
  const m = ($('#align-lonlat').value || '').match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (!m) { toast("Enter lon,lat(e.g. -79.38,43.64)", true); return; }
  const lon = +m[1], lat = +m[2];
  if (lon < -180 || lon > 180 || lat < -85 || lat > 85) { toast("Coordinates outside valid range", true); return; }
  const name = (state.allStations?.[id]?.name) || id;
  state.alignList = (state.alignList || []).filter(a => a.id !== id);
  state.alignList.push({ id, name, lon, lat });
  renderAlignList();
  toast(`Added: ${name} → ${lon}, ${lat}`);
}
function alignGenerate() {
  const list = state.alignList || [];
  if (!list.length) { toast("Alignment list is empty", true); return; }
  const save = $('#save-select')?.value;
  if (!save) { toast("Select a save in Overview & health first", true); return; }
  let base = ($('#align-output').value || '').trim().replace(/[\\/:*?"<>|]/g, '').replace(/\.nimbyrails5$/i, '');
  if (!base) base = `Coordinate alignment_${timestamp()}`;
  const saveName = save.split(/[\\/]/).pop().replace(/\.nimbyrails5$/i, '');
  const output = save.replace(/[^\\/]+$/, '') + base + '.nimbyrails5';
  const updates = list.map(a => `${a.id}=${a.lon},${a.lat}`);
  startTask('align-coords', { save, output, updates });
}
async function onAlignDone(result) {
  state.alignList = [];
  renderAlignList();
  const name = result.output_save?.split(/[\\/]/).pop() || "New save";
  toast(`New aligned save generated: ${name}(Rewrite ${result.changed_count} stops)`);
  await refreshFileLists();
  if (typeof refreshOutputNames === 'function') refreshOutputNames();
}
function realnetEnsureData() {
  if (state.network) { realnetDrawGame(); return; }
  const exp = $('#export-select')?.value;
  if (exp) startTask('map-data', { export: exp });
  else toast("Export timetable data in game, then refresh and select the generated JSON in Overview & health", true);
}
function realnetFitGame() {
  if (!state.network) { realnetEnsureData(); return; }
  const st = state.network.stations || {}; const pts = [];
  (state.network.lines || []).forEach(l => (l.stops || []).forEach(id => { if (st[id]) pts.push([st[id].lat, st[id].lon]); }));
  if (!pts.length) { toast("The game network has no coordinates to locate", true); return; }
  REALNET.map.fitBounds(pts, { padding: [40, 40] });
}
function addRealnetPin(lat, lng, name) {
  const p = { lat: +(+lat).toFixed(6), lng: +(+lng).toFixed(6), name: name || `Planning points ${REALNET.pins.length + 1}`, note: '' };
  REALNET.pins.push(p); saveJson('nimby_realnet_pins', REALNET.pins); renderRealnetPins();
}
function renderRealnetPins() {
  if (REALNET.pinLayer) {
    REALNET.pinLayer.clearLayers();
    REALNET.pins.forEach(p => L.marker([p.lat, p.lng]).addTo(REALNET.pinLayer).bindPopup(`<b>${escapeHtml(p.name)}</b><br>${p.lat}, ${p.lng}`));
  }
  const count = REALNET.pins.length;
  $('#realnet-pin-count').textContent = `Planning pins ${count} items`;
  $('#realnet-pin-panel').hidden = count === 0;
  $('#realnet-pin-list').innerHTML = REALNET.pins.map((p, i) =>
    `<div class="realnet-pin-row"><div><strong>${escapeHtml(p.name)}</strong><small>${p.lat}, ${p.lng}</small></div><div class="realnet-pin-acts"><button class="text-button" data-pin-go="${i}">Locate</button><button class="text-button" data-pin-rename="${i}">Rename</button><button class="text-button danger-text" data-pin-del="${i}">Remove</button></div></div>`
  ).join('');
}
function exportPins(kind) {
  if (!REALNET.pins.length) { toast("No planning pins yet", true); return; }
  const stamp = timestamp(); let blob, filename;
  if (kind === 'geojson') {
    const gj = { type: 'FeatureCollection', features: REALNET.pins.map(p => ({ type: 'Feature', properties: { name: p.name, note: p.note || '' }, geometry: { type: 'Point', coordinates: [p.lng, p.lat] } })) };
    blob = new Blob([JSON.stringify(gj, null, 2)], { type: 'application/geo+json' }); filename = `Planning pins_${stamp}.geojson`;
  } else {
    const esc = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = '\ufeff' + [['name', 'lat', 'lon', 'note'], ...REALNET.pins.map(p => [p.name, p.lat, p.lng, p.note || ''])].map(r => r.map(esc).join(',')).join('\r\n');
    blob = new Blob([csv], { type: 'text/csv;charset=utf-8' }); filename = `Planning pins_${stamp}.csv`;
  }
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 500);
  toast(`Exported ${filename}`);
}
async function realnetSearch() {
  const q = ($('#realnet-search').value || '').trim(); if (!q) return;
  const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (m) { REALNET.map.setView([+m[1], +m[2]], 13); return; }
  try {
    const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`, { headers: { Accept: 'application/json' } });
    const data = await r.json();
    if (!data.length) { toast("Place not found", true); return; }
    REALNET.map.setView([+data[0].lat, +data[0].lon], 13);
  } catch (e) { toast("Place search failed; check your connection", true); }
}
function renderImported() {
  if (!REALNET.importLayer) REALNET.importLayer = L.layerGroup().addTo(REALNET.map);
  REALNET.importLayer.clearLayers();
  (REALNET.imported || []).forEach(s => {
    L.circleMarker([s.lat, s.lon], { radius: 4, color: '#b5530f', weight: 1.5, fillColor: '#e67e22', fillOpacity: 0.9 })
      .bindTooltip(`${s.name}(Real-world)`).addTo(REALNET.importLayer);
  });
  const has = (REALNET.imported || []).length;
  $('#realnet-import-to-pins').disabled = !has;
  $('#realnet-import-clear').disabled = !has;
  $('#realnet-import-count').textContent = has ? `Imported ${has} real-world stations` : '';
}
const OVERPASS_ENDPOINTS = [
  'https://overpass-api.de/api/interpreter',
  'https://overpass.kumi.systems/api/interpreter',
  'https://overpass.private.coffee/api/interpreter',
];
async function importRealStations() {
  if (!REALNET.map) { toast("Map not ready", true); return; }
  if (REALNET.map.getZoom() < 8) { toast("Area too large; zoom to city level before fetching", true); return; }
  const b = REALNET.map.getBounds();
  const bbox = `${b.getSouth().toFixed(5)},${b.getWest().toFixed(5)},${b.getNorth().toFixed(5)},${b.getEast().toFixed(5)}`;
  const q = `[out:json][timeout:60];node["railway"~"^(station|halt)$"](${bbox});out body 800;`;
  const btn = $('#realnet-import-stations'); btn.disabled = true;
  let lastErr = '';
  for (let i = 0; i < OVERPASS_ENDPOINTS.length; i++) {
    toast(`Fetching real-world stations from OpenStreetMap… (source ${i + 1}/${OVERPASS_ENDPOINTS.length}）`);
    try {
      const r = await fetch(OVERPASS_ENDPOINTS[i], { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: q });
      if (!r.ok) { lastErr = 'HTTP ' + r.status; continue; }
      const data = await r.json();
      const items = (data.elements || []).map(e => {
        const lat = e.lat ?? e.center?.lat, lon = e.lon ?? e.center?.lon;
        return (lat && lon) ? { lat, lon, name: (e.tags && (e.tags.name || e.tags['name:en'])) || "Unnamed station" } : null;
      }).filter(Boolean);
      REALNET.imported = items; renderImported();
      toast(items.length ? `Fetched ${items.length} real-world stations available as planning pins` : "No stations found here. Try another area or zoom in", !items.length);
      btn.disabled = false; return;
    } catch (e) { lastErr = e.message; }
  }
  btn.disabled = false;
  toast(`Fetch failed: ${lastErr}. Overpass The public server may be busy. Reduce the area or retry later`, true);
}
function importedToPins() {
  const items = REALNET.imported || [];
  if (!items.length) { toast("Fetch real-world stations first", true); return; }
  items.forEach(s => REALNET.pins.push({ lat: +(+s.lat).toFixed(6), lng: +(+s.lon).toFixed(6), name: s.name, note: "OSM Import" }));
  saveJson('nimby_realnet_pins', REALNET.pins); renderRealnetPins();
  toast(`Applied to ${items.length} real-world stations added to planning pins`);
}
function haversineKm(a, b) {
  const R = 6371, toRad = d => d * Math.PI / 180;
  const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lon - a.lon);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}
const OSM_ROUTE_LABELS = { subway: "Metro", light_rail: "Light rail", tram: "Tram", train: "Railway", monorail: "Monorail" };
const FALLBACK_PALETTE = ['#e6194B', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990', '#dcbeff', '#9A6324', '#800000', '#808000', '#000075'];
function osmColor(raw, idx) {
  const v = String(raw || '').trim();
  if (/^#?[0-9a-fA-F]{6}$/.test(v)) return v.startsWith('#') ? v : '#' + v;
  return FALLBACK_PALETTE[idx % FALLBACK_PALETTE.length];
}
async function importRealLines() {
  if (!REALNET.map) { toast("Map not ready", true); return; }
  if (REALNET.map.getZoom() < 9) { toast("Area too large; zoom to city or line level before fetching", true); return; }
  const b = REALNET.map.getBounds();
  const bbox = `${b.getSouth().toFixed(5)},${b.getWest().toFixed(5)},${b.getNorth().toFixed(5)},${b.getEast().toFixed(5)}`;
  const q = `[out:json][timeout:90];rel["route"~"^(subway|light_rail|tram|train|monorail)$"](${bbox});out body;node(r);out body;`;
  const btn = $('#realnet-import-lines'); btn.disabled = true;
  let lastErr = '';
  for (let i = 0; i < OVERPASS_ENDPOINTS.length; i++) {
    toast(`Fetching real-world lines from OpenStreetMap… (source ${i + 1}/${OVERPASS_ENDPOINTS.length}）`);
    try {
      const r = await fetch(OVERPASS_ENDPOINTS[i], { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: q });
      if (!r.ok) { lastErr = 'HTTP ' + r.status; continue; }
      const data = await r.json();
      const nodes = {};
      (data.elements || []).forEach(e => { if (e.type === 'node') nodes[e.id] = e; });
      const rels = (data.elements || []).filter(e => e.type === 'relation' && e.tags && /^(subway|light_rail|tram|train|monorail)$/.test(e.tags.route));
      const lines = [];
      rels.forEach((rel, idx) => {
        const t = rel.tags;
        let stopMembers = (rel.members || []).filter(m => m.type === 'node' && /stop/.test(m.role || ''));
        if (!stopMembers.length) stopMembers = (rel.members || []).filter(m => { const n = nodes[m.ref]; return n && n.tags && (/^(station|halt|stop)$/.test(n.tags.railway || '') || /(station|stop_position)/.test(n.tags.public_transport || '')); });
        const stops = [];
        stopMembers.forEach(m => {
          const n = nodes[m.ref]; if (!n || n.lat == null) return;
          const name = (n.tags && (n.tags.name || n.tags['name:en'])) || "Unnamed station";
          if (stops.length && stops[stops.length - 1].name === name) return;
          stops.push({ name, lat: n.lat, lon: n.lon });
        });
        if (stops.length < 2) return;
        let km = 0; for (let j = 1; j < stops.length; j++) km += haversineKm(stops[j - 1], stops[j]);
        lines.push({ name: (t.name || t.ref || "Unnamed line").trim(), ref: (t.ref || '').trim(), route: t.route, color: osmColor(t.colour, idx), stops, lengthKm: km });
      });
      lines.sort((a, b2) => a.name.localeCompare(b2.name));
      REALNET.importedLines = lines.slice(0, 80);
      renderImportedLines();
      toast(lines.length ? `Fetched ${REALNET.importedLines.length} real-world lines; reference checklist generated` : "No route relations found here. Try another area or zoom in", !lines.length);
      btn.disabled = false; return;
    } catch (e) { lastErr = e.message; }
  }
  btn.disabled = false;
  toast(`Fetch failed: ${lastErr}. Overpass The public server may be busy. Reduce the area or retry later`, true);
}
function renderImportedLines() {
  if (!REALNET.importLinesLayer) REALNET.importLinesLayer = L.layerGroup().addTo(REALNET.map);
  REALNET.importLinesLayer.clearLayers();
  const lines = REALNET.importedLines || [];
  lines.forEach(l => {
    const pts = l.stops.map(s => [s.lat, s.lon]);
    L.polyline(pts, { color: l.color, weight: 4, opacity: 0.9 }).bindTooltip(`${l.name}(Real-world · ${l.stops.length} stops)`).addTo(REALNET.importLinesLayer);
    l.stops.forEach(s => L.circleMarker([s.lat, s.lon], { radius: 3, color: '#fff', weight: 1, fillColor: l.color, fillOpacity: 1 }).bindTooltip(`${s.name}（${l.name}）`).addTo(REALNET.importLinesLayer));
  });
  const panel = $('#realnet-lines-panel'); if (panel) panel.hidden = false;
  const list = $('#realnet-lines-list');
  if (!lines.length) { list.innerHTML = "<div class=\"placeholder\">No route relations found in this area.</div>"; }
  else {
    list.innerHTML = lines.map((l, i) => `<div class="realnet-line-row"><div class="rl-head"><span class="rl-swatch" style="background:${l.color}"></span><strong>${escapeHtml(l.name)}</strong>${l.ref ? `<span class="rl-ref">${escapeHtml(l.ref)}</span>` : ''}<span class="rl-tag">${OSM_ROUTE_LABELS[l.route] || l.route}</span><span class="rl-meta">${l.stops.length} stops · ≈${l.lengthKm.toFixed(1)} km</span><button class="text-button mini" data-line-focus="${i}">Highlight</button><button class="text-button mini" data-line-pins="${i}">stops→pins</button></div><div class="rl-stops">${l.stops.map(s => escapeHtml(s.name)).join(' → ')}</div></div>`).join('');
    list.querySelectorAll('[data-line-focus]').forEach(b => b.addEventListener('click', () => { const l = lines[+b.dataset.lineFocus]; REALNET.map.fitBounds(l.stops.map(s => [s.lat, s.lon]), { padding: [40, 40] }); }));
    list.querySelectorAll('[data-line-pins]').forEach(b => b.addEventListener('click', () => lineStopsToPins(+b.dataset.linePins)));
  }
  const has = lines.length > 0;
  ['#realnet-lines-json', '#realnet-lines-csv', '#realnet-lines-clear'].forEach(sel => { const el = $(sel); if (el) el.disabled = !has; });
}
function lineStopsToPins(idx) {
  const l = (REALNET.importedLines || [])[idx]; if (!l) return;
  l.stops.forEach(s => REALNET.pins.push({ lat: +(+s.lat).toFixed(6), lng: +(+s.lon).toFixed(6), name: s.name, note: `OSM Lines: ${l.name}` }));
  saveJson('nimby_realnet_pins', REALNET.pins); renderRealnetPins();
  toast(`Applied to「${l.name}」of ${l.stops.length} stations added as planning pins`);
}
function clearRealLines() {
  REALNET.importedLines = [];
  if (REALNET.importLinesLayer) REALNET.importLinesLayer.clearLayers();
  renderImportedLines();
  toast("Imported real-world lines cleared");
}
function exportRealLines(kind) {
  const lines = REALNET.importedLines || [];
  if (!lines.length) { toast("No lines imported", true); return; }
  const stamp = timestamp(); let blob, filename;
  if (kind === 'json') {
    blob = new Blob([JSON.stringify({ generated: new Date().toISOString(), source: 'OpenStreetMap (Overpass)', line_count: lines.length, lines }, null, 2)], { type: 'application/json' });
    filename = `Real-world line checklist_${stamp}.json`;
  } else {
    const esc = v => `"${String(v).replace(/"/g, '""')}"`;
    const rows = [['line', 'ref', 'type', 'color', 'stop_count', 'length_km', 'stops_in_order']];
    lines.forEach(l => rows.push([l.name, l.ref, l.route, l.color, l.stops.length, l.lengthKm.toFixed(2), l.stops.map(s => s.name).join(' > ')]));
    blob = new Blob(['\ufeff' + rows.map(r => r.map(esc).join(',')).join('\r\n')], { type: 'text/csv' });
    filename = `Real-world line checklist_${stamp}.csv`;
  }
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 500);
  toast(`Exported ${filename}`);
}
async function initRealnet() {
  if(window.workspaceMapReady) await window.workspaceMapReady;
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
  map.on('click', e => {
    if ($('#align-pick')?.checked) {
      $('#align-lonlat').value = `${e.latlng.lng.toFixed(6)},${e.latlng.lat.toFixed(6)}`;
      toast("Coordinates captured; select Add to alignment list”");
      return;
    }
    if ($('#realnet-pin-mode').checked) addRealnetPin(e.latlng.lat, e.latlng.lng);
  });
  REALNET.ready = true;
  if (!state.alignList) state.alignList = [];
  renderAlignList();
  populateAlignStations();
  if (state.network) { realnetDrawGame(); realnetDrawSignals(); } else realnetEnsureData();
  if ((state.trackSegments || []).length) realnetDrawTracks();
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
const WRITE_ACTIONS = new Set(['batch-migrate', 'fix-tasks', 'extension', 'recover-template', 'align-coords', 'timetable-write', 'station-name-write', 'operating-rule-write']);
async function startTask(action, payload, context = null) {
  if(state.cleanupBusy){toast("Files are being verified or cleaned up. Wait before starting another task.",true);return false;}
  // Reserve the single task slot before any await; a second click must not
  // reset the first task's polling state or its preview context.
  if (state.taskActive) { toast("A task is running; wait for completion or cancel it first.", true); return false; }
  if (WRITE_ACTIONS.has(action) && state.gameVersion && state.gameVersion.safe_to_write === false) {
    if (!confirm(`${state.gameVersion.note || "Writing has not been fully verified for this game version."}

The toolkit still creates only a new save and never overwrites the original. Continue?`)) return;
  }
  try {
    state.taskAction = action; state.taskContext = context; state.pollFailures = 0; state.pollBusy = false; state.taskActive = true;
    if(['operating-rules','line-timetable','station-name-write','workspace'].includes(action)||(action==='autotrack'&&payload.operation!=='catalog'))window.holdLiveInputs?.();
    await api('/api/task/start', { method:'POST', body:JSON.stringify({ action, ...payload }) });
    $('#task-dock').hidden = false; $('#task-progress').style.width = '2%'; $('#task-message').textContent = "Preparing task…";
    const worker = ensureTicker();
    if (worker) worker.postMessage('start'); else fallbackLoop();
    pollOnce();
    return true;
  } catch (e) { finishTask(); if(action === 'autotrack') window.autotrackFailure?.(e.message); window.workspaceFailure?.(e.message); toast(e.message, true); return false; }
}
async function pollOnce() {
  if (state.pollBusy || !state.taskActive) return;
  state.pollBusy = true;
  const taskContext = state.taskContext;
  try {
    const s = await api(`/api/task/status?_=${Date.now()}`, { timeoutMs: 12000 });
    state.pollFailures = 0;
    if (s.state === 'running') {
      const p = s.progress || {}; $('#task-message').textContent = p.message || "Processing in background…"; $('#task-progress').style.width = `${p.percent || 3}%`; return;
    }
    if (s.state === 'complete') {
      finishTask();
      if (s.action === 'autotrack') { await window.autotrackResult?.(s.result, taskContext); }
      else if (s.action === 'workspace') { await window.workspaceResult?.(s.result, taskContext); }
      else if (s.action === 'analyze') renderAnalysis(s.result);
      else if (s.action === 'inventory') renderInventory(s.result);
      else if (s.action === 'compare') renderCompare(s.result);
      else if (s.action === 'find-reference') renderReference(s.result);
      else if (s.action === 'map-data') { renderMapData(s.result); renderBinderLines(); if (REALNET.ready) realnetDrawGame(); }
      else if (s.action === 'save-health') { renderSaveHealth(s.result); }
      else if (s.action === 'save-overview') { renderSaveOverview(s.result); }
      else if (s.action === 'line-timetable') { renderLineTimetable(s.result); }
      else if (s.action === 'operating-rules') { renderOperatingRules(s.result); }
      else if (s.action === 'ops-analyze') { renderOpsAnalyze(s.result); }
      else if (s.action === 'network-read') { onNetworkRead(s.result); }
      else if (s.action === 'track-geometry') { onTrackGeometry(s.result); }
      else if (s.action === 'align-coords') { await onAlignDone(s.result); }
      else if (s.action === 'timetable-write') { onTimetableWriteDone(s.result); await refreshFileLists(); refreshOutputNames(); }
      else if (s.action === 'operating-rule-write') { onOperatingRuleWriteDone(s.result); await refreshFileLists(); refreshOutputNames(); }
      else if (s.action === 'station-name-write') { onStationNamesDone(s.result); await refreshFileLists(); refreshOutputNames(); }
      else if (s.action === 'network-diff') renderNetworkDiff(s.result);
      else { toast(`New save created: ${s.result.output_save?.split(/[\\/]/).pop() || "Operation complete"}`); await refreshFileLists(); refreshOutputNames(); }
      return;
    }
    if (s.state === 'failed') { finishTask(); if(s.action === 'autotrack') window.autotrackFailure?.(s.result?.error || "Background operation failed"); window.workspaceFailure?.(s.result?.error || "Background operation failed"); toast(s.result?.error || "Background operation failed", true); return; }
  } catch (e) {
    state.pollFailures = (state.pollFailures || 0) + 1;
    if (state.pollFailures <= 10) { $('#task-message').textContent = `Connection lost; retrying…(${state.pollFailures})`; return; }
    finishTask(); toast(`Cannot retrieve task status: ${e.message}`, true);
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
  const options=cleanupOptions(),signature=JSON.stringify(options),sequence=(state.cleanupSequence||0)+1;
  state.cleanupSequence=sequence;invalidateCleanup();state.cleanupBusy=true;
  $('#cleanup-explanation').textContent="Checking files and retention rules. Preview does not move any files…";
  try {
    const data = await api('/api/cleanup/preview', { method:'POST', body:signature });
    if(sequence!==state.cleanupSequence||signature!==JSON.stringify(cleanupOptions()))return;
    state.cleanup=data.cleanup;state.cleanupSignature=signature;renderCleanup();
  } catch(e) { toast(e.message,true); }
  finally{if(sequence===state.cleanupSequence){state.cleanupBusy=false;syncCleanupSelection();}}
}
// ---- #10 批量扩展绑定器 ----
function renderBinderLines() {
  const box = $('#binder-line-list'); if (!box) return;
  const lines = state.network?.lines || [];
  if (!lines.length) { box.innerHTML = "<div class=\"placeholder\">Select game-generated timetable data in Overview & health, then Load lines from game timetable data”.</div>"; return; }
  box.innerHTML = lines.map(l => {
    const c = lineColor(l.color); const service = l.stop_count > 1;
    return `<label class="map-line-option"><input class="binder-line-check" type="checkbox" value="${escapeHtml(l.id)}" data-name="${escapeHtml(l.name)}" data-code="${escapeHtml(l.code || '')}" ${service ? 'checked' : ''}><span class="line-swatch" style="background:${c}"></span><span><strong>${escapeHtml(l.name)}</strong><small>${escapeHtml(l.code || '')}${l.code ? ' · ' : ''}${l.stop_count} stops</small></span></label>`;
  }).join('');
}
function binderLoadLines() {
  if (state.network) { renderBinderLines(); toast("Lines loaded"); return; }
  if (!$('#export-select').value) { toast("Export timetable data in game, then refresh and select the generated JSON in Overview & health", true); return; }
  startTask('map-data', { export: $('#export-select').value });
}
function binderAnalysisCurrent() {
  return !!state.analysis && state.analysis.save === $('#save-select').value && state.analysis.export === $('#export-select').value;
}
function loadBinderFleets() {
  if (!binderAnalysisCurrent()) {
    switchView('dashboard');
    $('#adv-json-box').open = true;
    $('#deep-scan-button').focus();
    toast("Fleet binding requires a verified save/export pair. Export timetable data in game first; a basic save health check does not contain this information.", true);
    return;
  }
  renderBinderFleets(); toast("Fleets loaded from the verified save/export results");
}
function renderBinderFleets() {
  const box = $('#binder-fleet-list'); if (!box) return;
  const schedules = (binderAnalysisCurrent() ? state.analysis.health_schedules || [] : []).filter(s => s.train_count > 0);
  box.innerHTML = schedules.length
    ? schedules.map(s => `<label class="schedule-option"><input class="binder-fleet-check" type="checkbox" value="${escapeHtml(s.name)}"><span><strong>${escapeHtml(s.name)}</strong><small>${s.train_count} trains · Enabled ${s.garage_enabled}</small></span></label>`).join('')
    : "<div class=\"placeholder\">Select the save and game-generated timetable data in the overview. Verify the pair before loading fleets.</div>";
}
function selectedBinderLines() { return $$('.binder-line-check:checked').map(x => ({ id: x.value, name: x.dataset.name, code: x.dataset.code })); }
async function generateBinderMod() {
  const rules = { garage_join: $('#binder-garage').checked, arrival_hold: $('#binder-hold').checked, hold_seconds: +$('#binder-hold-s').value || 0, signal_speed_limit: $('#binder-speed').checked, speed_kmh: +$('#binder-speed-kmh').value || 40, speed_distance_m: +$('#binder-speed-distance').value || 800 };
  if (!rules.garage_join && !rules.arrival_hold && !rules.signal_speed_limit) { toast("Select at least one rule", true); return; }
  const lines = selectedBinderLines();
  if ((rules.arrival_hold) && !lines.length) { toast("Select at least one line for additional arrival waits", true); return; }
  const payload = { name: $('#binder-name').value || "Batch operating extension pack", id: $('#binder-id').value || '', ...rules };
  const btn = $('#binder-generate'); btn.disabled = true;
  try {
    const res = await api('/api/script/generate', { method: 'POST', body: JSON.stringify(payload) });
    state.binderChecklist = buildBinderChecklist(rules, lines, res.meta);
    state.binderBinding = res.meta.binding;
    renderBinderResult(res, rules, lines);
    toast("Binding mod and activation checklist generated");
  } catch (e) { toast(e.message, true); } finally { btn.disabled = false; }
}
function buildBinderChecklist(rules, lines, meta) {
  const sections = [];
  if (rules.garage_join) sections.push({ rule: 'Timetable garage join', apply_to: "Trains", how: "Enable it on the relevant trains in game, or use Batch depot joins below to bind them in a new save.", targets: [] });
  if (rules.arrival_hold) sections.push({ rule: `Arrival hold (+${rules.hold_seconds}s)`, apply_to: "Line stops (Line::Stop)", how: "Open each line in game and enable Arrival hold on the stops that need it.", targets: lines.map(l => l.name + (l.code ? ` (${l.code})` : '')) });
  if (rules.signal_speed_limit) sections.push({ rule: `Signal speed limit (${rules.speed_kmh} km/h · ${rules.speed_distance_m} m within)`, apply_to: "Signals (Signal)", how: "Select the target signals in game and enable Signal speed limit; adjust its limit and activation distance as needed.", targets: [] });
  return { mod_id: meta?.script_id, mod_name: meta?.display_name, generated: new Date().toISOString(), sections };
}
function renderBinderResult(res, rules, lines) {
  const el = $('#binder-result'); el.hidden = false;
  const cl = state.binderChecklist;
  const secHtml = cl.sections.map(s => `<div class="bind-sec"><div class="bind-sec-head"><strong>${escapeHtml(s.rule)}</strong><span>Target objects: ${escapeHtml(s.apply_to)}</span></div><p>${escapeHtml(s.how)}</p>${s.targets.length ? `<div class="bind-targets">${s.targets.map(t => `<span>${escapeHtml(t)}</span>`).join('')}</div>` : ''}</div>`).join('');
  const binding=res.meta.binding||{};
  el.innerHTML = `<div class="binder-dl"><a class="primary-button" href="${res.download_url}" download>Download mod ZIP(${escapeHtml(res.meta.script_id)})</a><button class="text-button" id="binder-export-json">Export manifest JSON</button><button class="text-button" id="binder-export-csv">Export manifest CSV</button></div><p class="plan-note">Extract into the NIMBY Rails private mods directory and enable the mod in game. Then activate extensions per object using the checklist below.</p><div class="script-safety"><strong>${binding.binary_write_supported?"Batch write supported":"Bind in game only"}</strong><p>${escapeHtml(binding.binary_write_supported?"This package contains only the fixed-ID depot-join rule. Save once in game before using step 3.":binding.reason||'')}</p></div><div class="bind-list">${secHtml}</div>`;
  $('#binder-export-json').addEventListener('click', () => exportBinderChecklist('json'));
  $('#binder-export-csv').addEventListener('click', () => exportBinderChecklist('csv'));
}
function exportBinderChecklist(kind) {
  const cl = state.binderChecklist; if (!cl) { toast("Generate a checklist first", true); return; }
  const stamp = timestamp(); let blob, filename;
  if (kind === 'json') { blob = new Blob([JSON.stringify(cl, null, 2)], { type: 'application/json' }); filename = `Binding checklist_${stamp}.json`; }
  else {
    const esc = v => `"${String(v).replace(/"/g, '""')}"`;
    const rows = [['rule', 'apply_to', 'how', 'targets']];
    cl.sections.forEach(s => rows.push([s.rule, s.apply_to, s.how, s.targets.join(' | ')]));
    blob = new Blob(['\ufeff' + rows.map(r => r.map(esc).join(',')).join('\r\n')], { type: 'text/csv' }); filename = `Binding checklist_${stamp}.csv`;
  }
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 500);
  toast(`Exported ${filename}`);
}
function binderWriteGarage() {
  if (!binderAnalysisCurrent()) { loadBinderFleets(); return; }
  const schedules = $$('.binder-fleet-check:checked').map(x => x.value);
  if (!schedules.length) { toast("Select at least one fleet", true); return; }
  if (!$('#save-select').value || !$('#export-select').value) { toast("Select a save and export in Overview & health and complete the check", true); return; }
  if (state.binderBinding && !state.binderBinding.binary_write_supported) { toast(state.binderBinding.reason || "This mod does not support binary batch binding", true); return; }
  startTask('extension', { save: $('#save-select').value, export: $('#export-select').value, output: $('#binder-output').value, schedules, mode: 'add', script_id: 'stm_timetable_garage_join_1' });
}

$('#main-nav').addEventListener('click', e => { const b=e.target.closest('[data-view]'); if(b) switchView(b.dataset.view); });

/* ---- Command palette (Ctrl/Cmd+K) + keyboard view switching ---- */
const CMDK = { open:false, items:[], filtered:[], cursor:0 };
function cmdkBuild() {
  const iconOf = {}; $$('.nav-item').forEach(b => { iconOf[b.dataset.view] = (b.querySelector('span')?.innerHTML || '›'); });
  CMDK.items = Object.keys(viewMeta).map((k, i) => ({ view:k, icon:iconOf[k]||'›', title:viewMeta[k][1], sub:viewMeta[k][0], idx:i+1 }));
}
function cmdkRender() {
  const list = $('#cmdk-list');
  list.innerHTML = CMDK.filtered.length ? CMDK.filtered.map((it, i) =>
    `<button class="cmdk-item${i===CMDK.cursor?' on':''}" data-view="${it.view}"><span class="cmdk-ic">${it.icon}</span><span class="cmdk-tt">${escapeHtml(it.title)}</span><small>${escapeHtml(it.sub)}</small>${it.idx<=9?`<kbd>Alt+${it.idx}</kbd>`:''}</button>`
  ).join('') : "<div class=\"cmdk-empty\">No matching commands</div>";
}
function cmdkFilter(q) {
  q = (q||'').trim().toLowerCase();
  CMDK.filtered = !q ? CMDK.items.slice() : CMDK.items.filter(it => (it.title+it.sub+it.view).toLowerCase().includes(q));
  CMDK.cursor = 0; cmdkRender();
}
function cmdkOpen() { if(!CMDK.items.length) cmdkBuild(); CMDK.open=true; $('#cmdk').hidden=false; const inp=$('#cmdk-input'); inp.value=''; cmdkFilter(''); setTimeout(()=>inp.focus(),0); }
function cmdkClose() { CMDK.open=false; $('#cmdk').hidden=true; }
function cmdkChoose(view) { if(view){ switchView(view); document.querySelector(`.nav-item[data-view="${view}"]`)?.scrollIntoView({block:'nearest'}); } cmdkClose(); }
$('#cmdk-input')?.addEventListener('input', e => cmdkFilter(e.target.value));
$('#cmdk-list')?.addEventListener('click', e => { const b=e.target.closest('[data-view]'); if(b) cmdkChoose(b.dataset.view); });
$('#cmdk')?.addEventListener('mousedown', e => { if(e.target.id==='cmdk') cmdkClose(); });
document.addEventListener('keydown', e => {
  const k = e.key.toLowerCase();
  if ((e.ctrlKey||e.metaKey) && k==='k') { e.preventDefault(); CMDK.open?cmdkClose():cmdkOpen(); return; }
  if (CMDK.open) {
    if (k==='escape') { e.preventDefault(); cmdkClose(); }
    else if (k==='arrowdown') { e.preventDefault(); CMDK.cursor=Math.min(CMDK.cursor+1,CMDK.filtered.length-1); cmdkRender(); }
    else if (k==='arrowup') { e.preventDefault(); CMDK.cursor=Math.max(CMDK.cursor-1,0); cmdkRender(); }
    else if (k==='enter') { e.preventDefault(); cmdkChoose(CMDK.filtered[CMDK.cursor]?.view); }
    return;
  }
  if (e.altKey && !e.ctrlKey && !e.metaKey && /^[1-9]$/.test(e.key)) {
    const keys = Object.keys(viewMeta); const target = keys[parseInt(e.key,10)-1];
    if (target) { e.preventDefault(); switchView(target); }
  }
});
$('#refresh-files').addEventListener('click', async()=>{if(window.checkLiveFiles)await window.checkLiveFiles();else await refreshFileLists(); toast("File list refreshed");});
$('#select-latest').addEventListener('click',()=>window.followLatestNow?.());
$('#overview-read')?.addEventListener('click',()=>{ const save=$('#save-select')?.value; if(!save)return toast("Select a save first",true); startTask('save-overview',{save}); });
$('#stationname-write')?.addEventListener('click',()=>{
  window.writeStationNames?.();
});
$('#timetable-read')?.addEventListener('click', () => { const save = $('#save-select')?.value; if (!save) return toast("Select a save first", true); startTask('line-timetable', { save }); });
$('#ops-read')?.addEventListener('click', () => {
  const save = $('#save-select')?.value; if (!save) return toast("Select a save first", true);
  const payload = { save };
  if ($('#ops-use-export')?.checked && $('#export-select')?.value) payload.export = $('#export-select').value;
  const t = parseInt($('#ops-target')?.value, 10);
  if (t > 0) payload.target_headway = t;
  startTask('ops-analyze', payload);
});
$('#headway-calc')?.addEventListener('click', calcHeadwayPlan);
$('#headway-export')?.addEventListener('click', exportHeadwayPlan);
$('#save-select').addEventListener('change', refreshOutputNames);
$('#save-dir-box')?.addEventListener('toggle', e => { e.target.dataset.userToggled = '1'; });
$('#save-dir-apply')?.addEventListener('click', () => applySaveDir($('#save-dir-input').value));
$('#save-dir-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); applySaveDir($('#save-dir-input').value); } });
$('#save-dir-detect')?.addEventListener('click', async () => {
  try {
    const res = await api('/api/config/save-dir', { method: 'POST', body: JSON.stringify({ detect: true }) });
    setOptions($('#save-select'), res.files.saves); setOptions($('#export-select'), res.files.exports); setCompareOptions(res.files.exports); refreshOutputNames();
    renderSaveDir(res.save_status);
    toast(res.save_status.has_saves ? `Scan complete; found ${res.save_status.save_count} saves` : "Scan complete; no save directory found", !res.save_status.has_saves);
    window.resetLiveFiles?.(res.files);
  } catch (e) { toast(e.message, true); }
});
$('#scan-button').addEventListener('click',()=>{
  const save=$('#save-select')?.value; if(!save) return toast("Select a save first",true);
  const payload={save}; const t=parseInt($('#ops-target')?.value,10); if(t>0) payload.target_headway=t;
  startTask('save-health',payload);
});
$('#deep-scan-button')?.addEventListener('click',()=>{
  const save=$('#save-select')?.value, exp=$('#export-select')?.value;
  if(!save) return toast("Select a save first",true);
  if(!exp) return toast("Pause and save in game, then export timetable data. Refresh files here and select the generated Timetable Export JSON",true);
  startTask('analyze',{save,export:exp});
});
$('#migrate-button').addEventListener('click',()=>{ const pairs=$$('.pair-check:checked').map(x=>x.dataset.pair); if(!pairs.length)return toast("Select at least one migration plan",true); startTask('batch-migrate',{save:$('#save-select').value,export:$('#export-select').value,output:$('#migration-output').value,pairs,garage_join:$('#garage-join').checked}); });
$('#toggle-schedules').addEventListener('click',()=>{const boxes=$$('.schedule-check'); const all=boxes.length&&boxes.every(x=>x.checked); boxes.forEach(x=>x.checked=!all); $('#toggle-schedules').textContent=all?"Select all":"Clear";});
$('#fix-button').addEventListener('click',()=>{
  const checked=$$('.repair-check:checked');
  if(!checked.length)return toast("Select at least one repairable task",true);
  const pairs=checked.filter(x=>x.dataset.repairType==='retire_overlap').map(x=>x.dataset.repairValue);
  const depot_schedules=checked.filter(x=>x.dataset.repairType==='depot_x1').map(x=>x.dataset.repairValue);
  startTask('fix-tasks',{save:$('#save-select').value,export:$('#export-select').value,output:$('#fix-output').value,pairs,depot_schedules});
});
$('#load-lines').addEventListener('click',()=>{ if(!$('#export-select').value)return toast("Export timetable data in game, then refresh and select the generated JSON in Overview & health",true); startTask('map-data',{export:$('#export-select').value}); });
$('#draw-map').addEventListener('click',drawTransitMap);
$('#export-map-svg').addEventListener('click',exportMapSvg);
$('#export-map-json').addEventListener('click',exportMapJson);
$('#map-export-save').addEventListener('click',()=>saveMapExportFolder());
$('#map-export-default').addEventListener('click',()=>saveMapExportFolder(true));
$('#map-all-labels').addEventListener('change',drawTransitMap);
$('#map-curved').addEventListener('change',drawTransitMap);
function updateMapStyleControls() {
  $('#map-orient-wrap').hidden=mapStyle()!=='strip';
  $('#map-metro-theme-wrap').hidden=mapStyle()!=='metro';
  $('#map-transfer-wrap').hidden=mapStyle()!=='metro';
  $('#map-layout-wrap').hidden=mapStyle()!=='metro';
  $('#map-merge-wrap').hidden=mapStyle()!=='metro';
  $('#map-curved').disabled=['schematic','metro','strip'].includes(mapStyle());
  if(mapStyle()==='metro'){$('#map-all-labels').checked=true;if(+$('#map-fontsize').value===11)$('#map-fontsize').value=16;}
}
$('#map-style').addEventListener('change',()=>{updateMapStyleControls();drawTransitMap();});
function applyMapZoom() {
  if(!state.mapSvg)return;
  const zoom=$('#map-zoom').value,box=state.mapSvg.getAttribute('viewBox').split(/\s+/).map(Number),width=box[2],height=box[3];
  const canvas=$('#map-canvas');
  // Fit both dimensions: a tall rail atlas must not push its network below
  // the viewport. Explicit width avoids the intrinsic SVG aspect-ratio trap.
  const fit=Math.min(Math.max(200,canvas.clientWidth-2)/width,Math.max(300,Math.min(820,window.innerHeight*0.72))/height);
  state.mapSvg.style.width=`${width*(zoom==='fit'?fit:Number(zoom))}px`;
  state.mapSvg.style.maxWidth='none';
  canvas.scrollTop=0;canvas.scrollLeft=0;
}
$('#map-zoom').addEventListener('change',applyMapZoom);
window.addEventListener('resize',()=>{if($('#map-zoom').value==='fit'&&$('#view-map').classList.contains('active'))applyMapZoom();});
$('#map-orient').addEventListener('change',drawTransitMap);
['#map-fontsize','#map-width','#map-height','#map-linewidth','#map-dotscale','#map-gap'].forEach(sel=>{ const el=$(sel); if(el) el.addEventListener('input',()=>{ if(state.network) drawTransitMap(); }); });
$('#map-reset-adv')?.addEventListener('click',()=>{ const d={'map-fontsize':11,'map-width':1400,'map-height':940,'map-linewidth':6,'map-dotscale':1,'map-gap':66}; Object.entries(d).forEach(([k,v])=>{ const el=$('#'+k); if(el) el.value=v; }); if(state.network) drawTransitMap(); toast("Default layout restored"); });
$('#map-select-all').addEventListener('click',()=>selectVisibleMapLines('all'));
$('#map-clear').addEventListener('click',()=>selectVisibleMapLines('none'));
$('#map-select-service').addEventListener('click',()=>selectVisibleMapLines('service'));
$('#map-clear-all').addEventListener('click',()=>{state.mapSelected?.clear();renderMapLineList();drawTransitMap();});
$('#map-line-search').addEventListener('input',renderMapLineList);
$('#map-line-sort').addEventListener('change',renderMapLineList);
$('#map-only-selected').addEventListener('change',renderMapLineList);
$('#map-metro-theme').addEventListener('change',()=>{ $('#map-style').value='metro';updateMapStyleControls();$('#map-metro-orientation').value=$('#map-metro-theme').value==='atlas'?'v':'h';$('#map-zoom').value='fit';drawTransitMap(); });
$('#map-metro-orientation').addEventListener('change',drawTransitMap);
$('#map-transfer-style').addEventListener('change',drawTransitMap);
$('#map-metro-layout').addEventListener('change',drawTransitMap);
$('#map-merge-branches').addEventListener('change',drawTransitMap);
$('#map-branch-group').addEventListener('click',()=>setMapBranchGroup('group'));
$('#map-branch-independent').addEventListener('click',()=>setMapBranchGroup('independent'));
$('#map-branch-auto').addEventListener('click',()=>setMapBranchGroup('auto'));
$('#map-line-list').addEventListener('change',e=>{
  if(!e.target.classList.contains('map-line-check'))return;
  const id=e.target.value; if(e.target.checked)state.mapSelected.add(id);else state.mapSelected.delete(id);
  renderMapLineList();drawTransitMap();
});
$('#realnet-base').addEventListener('change',()=>realnetSetBase($('#realnet-base').value));
$('#realnet-overlay').addEventListener('change',()=>realnetSetOverlay($('#realnet-overlay').value));
$('#realnet-show-game').addEventListener('change',realnetDrawGame);
$('#realnet-show-signals')?.addEventListener('change',realnetDrawSignals);
$('#realnet-show-tracks')?.addEventListener('change',()=>{ if($('#realnet-show-tracks').checked && !(state.trackSegments||[]).length){ const save=$('#save-select')?.value; if(!save)return toast("Select a save in Overview & health first",true); return startTask('track-geometry',{save}); } realnetDrawTracks(); });
$('#realnet-read-save')?.addEventListener('click',()=>{ const save=$('#save-select')?.value; if(!save)return toast("Select a save in Overview & health first",true); startTask('network-read',{save}); });
$('#realnet-read-tracks')?.addEventListener('click',()=>{ const save=$('#save-select')?.value; if(!save)return toast("Select a save in Overview & health first",true); startTask('track-geometry',{save}); });
$('#align-add')?.addEventListener('click',alignAdd);
$('#align-generate')?.addEventListener('click',alignGenerate);
$('#align-clear')?.addEventListener('click',()=>{ state.alignList=[]; renderAlignList(); });
$('#align-list')?.addEventListener('click',e=>{ const del=e.target.closest('[data-align-del]'); if(del){ state.alignList.splice(+del.dataset.alignDel,1); renderAlignList(); } });
$('#realnet-go').addEventListener('click',realnetSearch);
$('#realnet-search').addEventListener('keydown',e=>{ if(e.key==='Enter') realnetSearch(); });
$('#realnet-fit-game').addEventListener('click',realnetFitGame);
$('#realnet-export-geojson').addEventListener('click',()=>exportPins('geojson'));
$('#realnet-export-csv').addEventListener('click',()=>exportPins('csv'));
$('#realnet-clear-pins').addEventListener('click',()=>{ if(!REALNET.pins.length)return; if(!confirm("Clear all planning pins? This cannot be undone."))return; REALNET.pins=[]; saveJson('nimby_realnet_pins',REALNET.pins); renderRealnetPins(); });
$('#realnet-import-stations').addEventListener('click',importRealStations);
$('#realnet-import-lines').addEventListener('click',importRealLines);
$('#realnet-import-to-pins').addEventListener('click',importedToPins);
$('#realnet-import-clear').addEventListener('click',()=>{ REALNET.imported=[]; renderImported(); });
$('#realnet-lines-json')?.addEventListener('click',()=>exportRealLines('json'));
$('#realnet-lines-csv')?.addEventListener('click',()=>exportRealLines('csv'));
$('#realnet-lines-clear')?.addEventListener('click',clearRealLines);
$('#realnet-pin-list').addEventListener('click',e=>{
  const go=e.target.closest('[data-pin-go]'), rn=e.target.closest('[data-pin-rename]'), del=e.target.closest('[data-pin-del]');
  if(go){ const p=REALNET.pins[+go.dataset.pinGo]; if(p) REALNET.map.setView([p.lat,p.lng],14); }
  else if(rn){ const i=+rn.dataset.pinRename; const p=REALNET.pins[i]; const name=prompt("Planning-point name",p.name); if(name!==null){ p.name=name.trim()||p.name; saveJson('nimby_realnet_pins',REALNET.pins); renderRealnetPins(); } }
  else if(del){ const i=+del.dataset.pinDel; REALNET.pins.splice(i,1); saveJson('nimby_realnet_pins',REALNET.pins); renderRealnetPins(); }
});
$('#run-netdiff').addEventListener('click',()=>{ const before=$('#netdiff-before').value, after=$('#netdiff-after').value; if(!before||!after)return toast("Refresh files in Overview & health, then select two timetable exports from the game",true); if(before===after)return toast("Select two different exports",true); startTask('network-diff',{before,after}); });
$('#analytics-search').addEventListener('input', drawAnalyticsList);
$('#analytics-filter').addEventListener('change', drawAnalyticsList);
$('#export-report-csv').addEventListener('click', () => exportReport('csv'));
$('#export-report-json').addEventListener('click', () => exportReport('json'));
$('#run-inventory').addEventListener('click',()=>startTask('inventory',{limit:12}));
$('#run-compare').addEventListener('click',()=>{
  const before=$('#compare-before').value, after=$('#compare-after').value;
  if(!before||!after)return toast("Run a health check to load the export list",true);
  if(before===after)return toast("Select two different exports",true);
  startTask('compare',{before,after});
});
function extensionTask(mode){const schedules=$$('.schedule-check:checked').map(x=>x.value); if(!schedules.length)return toast("Select at least one timetable",true); startTask('extension',{save:$('#save-select').value,export:$('#export-select').value,output:$('#extension-output').value,schedules,mode});}
$('#add-extension').addEventListener('click',()=>extensionTask('add')); $('#remove-extension').addEventListener('click',()=>extensionTask('remove'));
$('#binder-load-lines')?.addEventListener('click',binderLoadLines);
$('#binder-lines-all')?.addEventListener('click',()=>$$('.binder-line-check').forEach(x=>x.checked=true));
$('#binder-lines-none')?.addEventListener('click',()=>$$('.binder-line-check').forEach(x=>x.checked=false));
$('#binder-generate')?.addEventListener('click',generateBinderMod);
$('#binder-load-fleets')?.addEventListener('click',loadBinderFleets);
$('#binder-fleets-all')?.addEventListener('click',()=>$$('.binder-fleet-check').forEach(x=>x.checked=true));
$('#binder-fleets-none')?.addEventListener('click',()=>$$('.binder-fleet-check').forEach(x=>x.checked=false));
$('#binder-write-garage')?.addEventListener('click',binderWriteGarage);
$('#save-cleanup-settings').addEventListener('click',async()=>{try{await api('/api/settings',{method:'POST',body:JSON.stringify({enabled:$('#cleanup-enabled').checked,days:+$('#cleanup-days').value,keep:+$('#cleanup-keep').value})}); await updateCleanupPreview(); toast("Automatic cleanup rules saved");}catch(e){toast(e.message,true);}});
$$('[data-clean-mode]').forEach(b=>b.addEventListener('click',()=>{$$('[data-clean-mode]').forEach(x=>x.classList.toggle('active',x===b));state.cleanMode=b.dataset.cleanMode;updateCleanupPreview();}));
$('#refresh-cleanup').addEventListener('click',updateCleanupPreview);
['#cleanup-days','#cleanup-keep','#cleanup-maps','#cleanup-timetables','#save-select','#export-select','#compare-before','#compare-after','#netdiff-before','#netdiff-after'].forEach(id=>$(id).addEventListener('change',invalidateCleanup));
$('#execute-cleanup').addEventListener('click',async()=>{
  const c=state.cleanup,chosen=cleanupChosen(),options=cleanupOptions();
  if(state.cleanupBusy||state.taskActive)return toast("Wait for the current task before cleaning up",true);
  if(state.cleanupSignature!==JSON.stringify(options))return toast("Refresh the cleanup preview",true);
  if(!chosen.length)return;
  if(!confirm(`Only selected ${chosen.length} file groups moved to Windows Recycle Bin; total ${formatBytes(chosen.reduce((sum,x)=>sum+x.bytes,0))}. Older exports may still be useful. Are you sure these are no longer needed?`))return;
  state.cleanupBusy=true;syncCleanupSelection();
  try{
    const d=await api('/api/cleanup/execute',{method:'POST',body:JSON.stringify({...options,token:c.token,selected:chosen.map(x=>x.path)})});
    toast(`Applied to ${d.result.moved_group_count} file groups moved to Recycle Bin; recover them there`);
    await refreshFileLists();await updateCleanupPreview();
  }catch(e){invalidateCleanup();toast(e.message,true);}
  finally{state.cleanupBusy=false;syncCleanupSelection();}
});
$('#find-reference-btn').addEventListener('click',()=>{
  const target=$('#recover-target').value;
  if(!target)return toast("No blank templates available for recovery",true);
  if(!$('#export-select').value)return toast("Select an export in Overview & health and complete the check",true);
  startTask('find-reference',{export:$('#export-select').value,target,limit:15});
});
$('#recover-btn').addEventListener('click',()=>{
  const target=$('#recover-target').value;
  if(!state.reference)return toast("Select a historical fleet first",true);
  if(!target)return toast("Select a target template",true);
  startTask('recover-template',{save:$('#save-select').value,export:$('#export-select').value,output:$('#recover-output').value,reference_export:state.reference.export,reference_source:state.reference.source,target,garage_join:$('#recover-garage').checked});
});
$('#calculate-plan').addEventListener('click',calculatePlan);
$('#planner-results').addEventListener('click',async e=>{const btn=e.target.closest('[data-copy]');if(!btn||!state.planCopy)return;const text=state.planCopy[btn.dataset.copy]||'';try{await navigator.clipboard.writeText(text);toast("Copied to clipboard");}catch(err){const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');toast("Copied to clipboard");}catch(_){toast("Copy failed; select and copy manually",true);}ta.remove();}});
$('#export-plan').addEventListener('click',()=>{if(!state.plan)calculatePlan();if(!state.plan)return;const blob=new Blob([JSON.stringify(state.plan,null,2)],{type:'application/json'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${state.plan.name.replace(/[\\/:*?"<>|]/g,'_')}_plan.json`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),500);});
function vehiclePayload(){
  const num=(id)=>Number($(id).value);
  const payload = {
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
  if ($('#veh-advanced-enabled').checked) {
    let advanced;
    try { advanced = JSON.parse($('#veh-advanced-json').value || '{}'); }
    catch (e) { throw new Error(`Cannot parse advanced-structure JSON: ${e.message}`); }
    if (!Array.isArray(advanced.units) || !advanced.units.length) throw new Error("Advanced structure requires at least one units entry");
    payload.units = advanced.units;
    payload.compositions = advanced.compositions;
    if (advanced.tags) payload.tags = advanced.tags;
  }
  return payload;
}
function cleanVehicleId(value, fallback='custom_train') {
  let id=String(value||'').trim().replace(/[^a-zA-Z0-9_]+/g,'_').replace(/^_+|_+$/g,'').toLowerCase() || fallback;
  if (/^\d/.test(id)) id='t_'+id; return id.slice(0,48);
}
function currentAdvancedVehicle(){
  const advanced=$('#veh-advanced-enabled').checked;$('#veh-advanced-enabled').checked=false;
  let p;try{p={...vehiclePayload()};}finally{$('#veh-advanced-enabled').checked=advanced;}
  const base=cleanVehicleId(p.model_id), cab=`${base}_cab`, car=`${base}_car`;
  const common=(prefix,id,name,tags,cabEnds)=>({
    id,name_en:name,category:p.model_name,tags,length:p[`${prefix}_length`],width:p[`${prefix}_width`],max_speed:p[`${prefix}_max_speed`],
    max_acceleration:1,max_regular_braking:1,max_emergency_braking:1.4,max_tractive_effort:0,power:p[`${prefix}_power`],empty_mass:p[`${prefix}_empty_mass`],
    price:p[`${prefix}_price`],max_pax:p[`${prefix}_max_pax`],standing_pax:p[`${prefix}_standing_pax`],pax_doors_per_side:2,
    allow_player_composition:true,cost_per_km:0,cost_per_km_per_pax:.02,cost_per_day:prefix==='head'?400:300,
    front_coupler:true,back_coupler:true,cab_ends:cabEnds
  });
  const units=[common('head',cab,`${p.model_name} cab car`,['control','sitting',p.power_type,p.gauge],'both')];
  const parts=[{unit_id:cab}];
  if(p.middle_enabled){units.push(common('middle',car,`${p.model_name} car`,['coach','sitting',p.gauge],'none'));parts.push({unit_id:car,min:p.middle_min,default:p.middle_def,max:p.middle_max});}
  if(p.two_cabs)parts.push({unit_id:cab,flip:true});
  return {units,compositions:[{id:`${base}_compo`,name:p.model_name,parts}]};
}
$('#veh-build-advanced').addEventListener('click',()=>{
  try{$('#veh-advanced-json').value=JSON.stringify(currentAdvancedVehicle(),null,2);$('#veh-advanced-enabled').checked=true;toast("Converted; you can now add or remove units and formations");}catch(e){toast(e.message,true);}
});
async function scanVehicleCatalog(){
  const button=$('#veh-scan-mods');button.disabled=true;
  try{
    const data=await api('/api/vehicle/catalog',{timeoutMs:60000});state.vehicleCatalog=data.catalog;
    const t=data.catalog.totals;
    $('#veh-catalog-summary').innerHTML=`Found <strong>${t.mods}</strong> vehicle mods · ${t.units} items TrainUnit · ${t.models} vehicle types · ${t.compositions} trainsets · ${t.duplicate_ids} cross-mod duplicates ID · <span class="${t.errors?'risk-critical':''}">${t.errors} errors</span> · ${t.warnings} warnings`;
    $('#veh-catalog').innerHTML="<option value=\"\">Select a mod</option>"+data.catalog.mods.map(m=>`<option value="${m.token}">[${escapeHtml(m.kind)}] ${escapeHtml(m.name)} · ${m.model_count} Vehicle type / ${m.unit_count} Units ${m.issues.length?` · ${m.issues.length} Warning`:''}</option>`).join('');
    $('#veh-catalog-model').innerHTML="<option value=\"\">Load a mod first</option>";toast(`Vehicle catalog scan complete: ${t.mods} mods`);
  }catch(e){toast(e.message,true);}finally{button.disabled=false;}
}
async function loadVehicleCatalogMod(){
  const token=$('#veh-catalog').value;if(!token){state.vehicleMod=null;return;}
  try{const data=await api('/api/vehicle/import',{method:'POST',body:JSON.stringify({token}),timeoutMs:60000});state.vehicleMod=data.mod;
    $('#veh-catalog-model').innerHTML="<option value=\"\">Select vehicle type</option>"+data.mod.models.map((m,i)=>`<option value="${i}">${escapeHtml(m.name)} · ${m.compositions.length} Formations</option>`).join('');
    const errors=data.mod.issues.filter(x=>x.level==='error').length,warnings=data.mod.issues.length-errors;
    $('#veh-catalog-summary').innerHTML=`<strong>${escapeHtml(data.mod.meta.name)}</strong> · ${data.mod.units.length} Units · ${data.mod.models.length} Vehicle type · ${errors} Error / ${warnings} Warning`;
  }catch(e){toast(e.message,true);}
}
function importVehicleModel(){
  const mod=state.vehicleMod,index=Number($('#veh-catalog-model').value);if(!mod||!Number.isInteger(index)||!mod.models[index])return toast("Select a vehicle type to import",true);
  const model=mod.models[index],used=new Set(model.compositions.flatMap(c=>c.parts.map(p=>p.unit_id)));
  const units=mod.units.filter(u=>used.has(u.id)).map(u=>{const copy={...u};delete copy.textures;return copy;});
  $('#veh-mod-name').value=mod.meta.name;$('#veh-author').value=mod.meta.author||'Unknown';$('#veh-version').value=mod.meta.version||'1.0.0';
  $('#veh-model-name').value=model.name;$('#veh-model-id').value=model.id;$('#veh-year').value=model.year_introduced||2000;$('#veh-country').value=(model.countries_operated||'').split(',')[0].toUpperCase();
  const role=model.tags.find(t=>[...$('#veh-role').options].some(o=>o.value===t));if(role)$('#veh-role').value=role;
  const power=model.tags.find(t=>[...$('#veh-power-type').options].some(o=>o.value===t));if(power)$('#veh-power-type').value=power;
  const gauge=model.tags.find(t=>[...$('#veh-gauge').options].some(o=>o.value===t));if(gauge)$('#veh-gauge').value=gauge;
  $('#veh-advanced-json').value=JSON.stringify({tags:model.tags,units,compositions:model.compositions},null,2);$('#veh-advanced-enabled').checked=true;
  toast(`Imported ${model.name}, Original mod remains read-only`);
}
$('#veh-scan-mods').addEventListener('click',scanVehicleCatalog);$('#veh-catalog').addEventListener('change',loadVehicleCatalogMod);$('#veh-import-model').addEventListener('click',importVehicleModel);
$('#generate-vehicle').addEventListener('click',async()=>{
  try{
    const data=await api('/api/vehicle/generate',{method:'POST',body:JSON.stringify(vehiclePayload())});
    const link=document.createElement('a');link.href=data.download_url;link.download=`${data.meta.mod_id}.zip`;document.body.appendChild(link);link.click();link.remove();
    const m=data.meta;
    const physics=m.physics.map(p=>`<div class="bind-sec"><div class="bind-sec-head"><strong>${escapeHtml(p.name)}</strong><span>${p.cars} cars · ${p.length_m} m · ${p.max_pax} passengers</span></div><p>${p.empty_mass_kg.toLocaleString()} kg Empty · ${p.power_kw.toLocaleString()} kW · ${p.max_speed_kmh} km/h · ${p.max_acceleration_mps2} m/s²</p><small>Acceleration curve: ${p.acceleration_curve.map(x=>`${x.speed_kmh} km/h=${x.acceleration_mps2}`).join(' · ')}</small></div>`).join('');
    const issues=m.issues.length?`<div class="script-safety"><strong>Check warnings(${m.issues.length}）</strong><p>${m.issues.map(x=>escapeHtml(x.message)).join('<br>')}</p></div>`:"<span class=\"verified-chip\">Structural checks passed</span>";
    $('#veh-preview').innerHTML=`<div class="veh-preview-head"><strong>${escapeHtml(m.model_name)}</strong><span class="verified-chip">${escapeHtml(m.tags)}</span></div><div class="veh-preview-meta">${m.unit_definitions} vehicle-unit types · ${m.compositions.length} trainsets</div>${physics}${issues}<details><summary>View generated mod.txt</summary><pre class="veh-modtext">${escapeHtml(m.mod_text)}</pre></details>`;
    toast(`Vehicle mod generated: ${m.model_name}`);
  }catch(e){toast(e.message,true);}
});
$('#generate-script').addEventListener('click',async()=>{try{
  const data=await api('/api/script/generate',{method:'POST',body:JSON.stringify({name:$('#script-name').value,id:$('#script-id').value,garage_join:$('#rule-garage').checked,arrival_hold:$('#rule-hold').checked,hold_seconds:+$('#rule-hold-seconds').value,signal_speed_limit:$('#rule-speed').checked,speed_kmh:+$('#rule-speed-kmh').value,speed_distance_m:+$('#rule-speed-distance').value})});
  const link=document.createElement('a');link.href=data.download_url;link.download=`${data.meta.script_id}.zip`;document.body.appendChild(link);link.click();link.remove();
  $('#script-expert-source').value=data.meta.source;renderScriptValidation(data.meta.validation,data.meta.source);
  toast(`Rule pack generated: ${data.meta.enabled_rules.join('、')}`);
}catch(e){toast(e.message,true);}});
function renderScriptValidation(v,source=''){
  const events=Object.entries(v.events||{}).map(([name,count])=>`${escapeHtml(name)} × ${count}`).join(' · ');
  const diagnostics=[...(v.errors||[]),...(v.warnings||[])].map(x=>`<p>${escapeHtml(x.line?`No. ${x.line} rows: ${x.message}`:x.message)}</p>`).join('');
  $('#script-validation').innerHTML=`<div class="veh-preview-head"><strong>${v.valid?"Static validation passed":"Validation failed"}</strong><span class="verified-chip">${v.errors.length} Error · ${v.warnings.length} Warning</span></div><p>${events||"Unrecognized event"}</p>${diagnostics||"<p>No known risks found.</p>"}${source?`<details><summary>View complete NimbyScript source</summary><pre class="veh-modtext">${escapeHtml(source)}</pre></details>`:''}`;
}
$('#validate-script-source').addEventListener('click',async()=>{const source=$('#script-expert-source').value;if(!source.trim())return toast("Paste NimbyScript source first",true);try{const data=await api('/api/script/validate',{method:'POST',body:JSON.stringify({source})});renderScriptValidation(data.validation,source);toast(data.validation.valid?"Static source validation passed":"Source validation found issues",!data.validation.valid);}catch(e){toast(e.message,true);}});
$('#cancel-task').addEventListener('click',async()=>{try{await api('/api/task/cancel',{method:'POST',body:'{}'});finishTask();toast("Task cancelled");}catch(e){toast(e.message,true);}});

/* ===== Timetable Designer (自定义时刻表设计器) ===== */
const TTD = { routes: [], plan: null };
function ttdPopulateLines(routes){
  TTD.routes = (routes||[]).filter(r=>r.stops && r.stops.length>=2);
  const sel = $('#ttd-line'); if(!sel) return;
  if(!TTD.routes.length){ sel.innerHTML="<option value=\"\">No timed lines</option>"; }
  else sel.innerHTML = TTD.routes.map((r,i)=>`<option value="${i}">${escapeHtml(r.name)} · ${r.stop_count} stops · ${durText(r.cycle_seconds)}</option>`).join('');
  const wsel = $('#ttd-w-line');
  if(wsel){
    wsel.innerHTML = TTD.routes.length
      ? TTD.routes.map((r,i)=>`<option value="${i}">${escapeHtml(r.name)} · ${r.stop_count} stops</option>`).join('')
      : "<option value=\"\">No timed lines</option>";
  }
  ttdSyncRun();
  ttdSyncWriteLine();
}
// The stop-time write card follows the designer's line selector (single source
// of truth) so the user never picks the same line twice.
function ttdSyncWriteLine(){
  const src=$('#ttd-line'), dst=$('#ttd-w-line'); if(!dst) return;
  const i = src ? src.value : '';
  if(i!=='' && dst.querySelector(`option[value="${i}"]`)) dst.value=i;
  const r=ttdWriteRoute();
  const nm=$('#ttd-w-linename'); if(nm) nm.textContent = r ? `${r.name} · ${r.stop_count} stops` : "(Read lines first)";
  ttdWriteRenderStops();
  ttdWriteRefreshOutput();
}
function ttdWriteRoute(){ const i=+($('#ttd-w-line')?.value); return Number.isInteger(i)?TTD.routes[i]:null; }
function ttdWriteMode(){ return $('#ttd-w-mode')?.value || 'uniform'; }
function ttdWriteRefreshOutput(){
  const el=$('#ttd-w-output'); if(!el) return;
  const r=ttdWriteRoute();
  const tag = (ttdWriteMode()==='perstop') ? 'StopTimes' : ('StopTime'+(Math.round(+$('#ttd-w-stop')?.value||0))+'s');
  el.value = (typeof outputPath==='function' && $('#save-select')?.value) ? outputPath(r?tag:'StopTime') : '';
}
// De-duplicate leg-anchored stops into the game's stop list (a loop repeats the origin).
function ttdWriteStops(r){ return (r && Array.isArray(r.stops)) ? r.stops : []; }
function ttdWriteRenderStops(){
  const wrap=$('#ttd-w-perstop'), list=$('#ttd-w-stoplist'); if(!wrap||!list) return;
  const per = ttdWriteMode()==='perstop';
  wrap.hidden=!per;
  const stopWrap=$('#ttd-w-stop-wrap'); if(stopWrap) stopWrap.style.display = per?'none':'';
  if(!per) return;
  const r=ttdWriteRoute();
  const stops=ttdWriteStops(r);
  if(!stops.length){ list.innerHTML="<div class=\"placeholder\">Select a line first.</div>"; return; }
  list.innerHTML = stops.map((s,i)=>{
    const name = escapeHtml(s.station || s.station_id || ("stops "+(i+1)));
    const cur = Math.round((s.dwell!=null? s.dwell : (s.departure-s.arrival))||0);
    return `<div class="ttd-w-stoprow"><span class="idx">${i+1}</span><span class="nm" title="${name}">${name}</span>`
      +`<input type="number" min="1" max="600" step="1" data-i="${i}" placeholder="Inherit(${cur}s)" aria-label="${name} Dwell time (s)"></div>`;
  }).join('');
}
function ttdWriteCollectList(){
  const inputs=[...document.querySelectorAll('#ttd-w-stoplist input[data-i]')];
  return inputs.map(inp=>{ const v=inp.value.trim(); return v===''? null : Number(v); });
}
function ttdCurrentRoute(){ const i=+($('#ttd-line')?.value); return Number.isInteger(i)?TTD.routes[i]:null; }
function ttdSyncRun(){ const r=ttdCurrentRoute(); const el=$('#ttd-run'); if(!r){ if(el) el.value='0'; return; } const dwellStr=($('#ttd-dwell')?.value||'').trim(); const stops=(dwellStr!=='' && +dwellStr>=0)?ttdApplyUniformDwell(r.stops,+dwellStr):r.stops; const run=stops[stops.length-1].arrival - stops[0].departure; if(el) el.value=(run/60).toFixed(1); }
function ttdTime(str){ const m=/^(\d{1,2}):(\d{2})$/.exec((str||'').trim()); if(!m || +m[2]>59 || +m[1]>47) return null; return (+m[1])*3600+(+m[2])*60; }
function ttdWindows(str){
  const out=[];
  for(const part of (str||'').split(/[,，]/).map(s=>s.trim()).filter(Boolean)) {
    const pair=part.split('-'); if(pair.length!==2)return null;
    let a=ttdTime(pair[0]),b=ttdTime(pair[1]); if(a===null||b===null)return null;
    if(b<=a)b+=86400; out.push([a,b]);
  }
  return out;
}
function ttdInPeak(t, wins){ return wins.some(([a,b])=> (t>=a&&t<b) || (t+86400>=a && t+86400<b)); }
function ttdReverse(stops){
  const n=stops.length, base=stops[0].departure;
  const rel=stops.map(s=>({station:s.station, arr:s.arrival-base, dep:s.departure-base}));
  const run=rel[n-1].arr;
  const out=[];
  for(let k=0;k<n;k++){ const o=n-1-k; out.push({station:rel[o].station, arrival:run-rel[o].dep, departure:run-rel[o].arr}); }
  const b2=out[0].departure;
  return out.map(s=>({station:s.station, arrival:s.arrival-b2, departure:s.departure-b2}));
}
function ttdBuildTrip(tmpl, D){ const base=tmpl[0].departure; return tmpl.map(s=>({station:s.station, arr:D+s.arrival-base, dep:D+s.departure-base})); }
// Rebuild cumulative arr/dep applying a uniform dwell d at every stop while
// preserving each leg's travel time (arrival[i] - departure[i-1]).
function ttdApplyUniformDwell(stops, d){
  const out=[]; let prevDep=0;
  stops.forEach((s,i)=>{
    if(i===0){ out.push({station:s.station, arrival:0, departure:d, dwell:d}); prevDep=d; }
    else { const leg=Math.max(0, s.arrival - stops[i-1].departure); const arr=prevDep+leg; const dep=arr+d; out.push({station:s.station, arrival:arr, departure:dep, dwell:d}); prevDep=dep; }
  });
  return out;
}
function ttdBackfill(){
  const r=ttdCurrentRoute(); if(!r) return toast("Select a line first",true);
  ttdSyncWriteLine();
  const dwellStr=($('#ttd-dwell')?.value||'').trim();
  const mode=$('#ttd-w-mode');
  if(dwellStr!=='' && +dwellStr>=1){
    if(mode) mode.value='uniform';
    ttdWriteRenderStops();
    const st=$('#ttd-w-stop'); if(st) st.value=Math.round(+dwellStr);
    toast(`Uniform dwell time applied to the editor ${Math.round(+dwellStr)}s to the write table, then confirm with Write a new save”.`);
  } else {
    if(mode) mode.value='perstop';
    ttdWriteRenderStops();
    document.querySelectorAll('#ttd-w-stoplist input[data-i]').forEach((inp,i)=>{ const s=r.stops[i]; inp.value=Math.round((s?.dwell!=null?s.dwell:(s.departure-s.arrival))||0); });
    toast("Template dwell times copied into the per-stop editor; adjust before writing if needed.");
  }
  ttdWriteRefreshOutput();
  $('#ttd-write')?.scrollIntoView({behavior:'smooth', block:'start'});
}
function ttdCompute(){
  const r=ttdCurrentRoute(); if(!r) return toast("Select a line first",true);
  const first=ttdTime($('#ttd-first').value); let last=ttdTime($('#ttd-last').value);
  if(first==null||last==null) return toast("Check the first/last departure time format(HH:MM, Last available departure 24:30 means the next day)",true);
  if(last<=first) last+=86400;
  const peakH=Math.max(0.5,+$('#ttd-peak').value)*60, offH=Math.max(0.5,+$('#ttd-offpeak').value)*60;
  const wins=ttdWindows($('#ttd-windows').value), layover=Math.max(0,+$('#ttd-layover').value)*60;
  if(wins===null) return toast("Incorrect peak-window format. Example: 07:00-09:30,16:00-19:00; Separate time windows with commas; minutes must be within 00–59.",true);
  const round=$('#ttd-dir').value==='round';
  if (round && r.stops.length > 2 && r.stops[0].station === r.stops[r.stops.length-1].station) return toast("The template already returns to its origin. Do not add another return leg; choose Run complete template without adding a return)”.", true);
  const dwellStr=($('#ttd-dwell')?.value||'').trim();
  const dwell = dwellStr!=='' ? Math.max(0,+dwellStr) : null;
  const srcStops = (dwell!=null && Number.isFinite(dwell)) ? ttdApplyUniformDwell(r.stops, dwell) : r.stops;
  const outT=srcStops.map(s=>({station:s.station, arrival:s.arrival, departure:s.departure}));
  const base=outT[0].departure, run=outT[outT.length-1].arrival-base;
  const retT=ttdReverse(srcStops);
  const deps=[]; let D=first, guard=0;
  while(D<=last && guard++<5000){ deps.push({t:D, peak:ttdInPeak(D,wins)}); D += (ttdInPeak(D,wins)?peakH:offH); }
  const vehCycle = round ? (2*run+2*layover) : (run+layover);
  const trains=[]; const trips=[];
  deps.forEach((d,idx)=>{
    let ti=trains.findIndex(f=>f<=d.t);
    if(ti<0){ ti=trains.length; trains.push(0); }
    trains[ti]=d.t+vehCycle;
    trips.push({dir:'out', train:ti+1, peak:d.peak, run:idx+1, stops:ttdBuildTrip(outT,d.t)});
    if(round){ trips.push({dir:'ret', train:ti+1, peak:d.peak, run:idx+1, stops:ttdBuildTrip(retT, d.t+run+layover)}); }
  });
  const stationY={}; outT.forEach(s=>{ stationY[s.station]=s.arrival-base; });
  const board={}; outT.forEach(s=>board[s.station]=[]);
  trips.forEach(tp=>tp.stops.forEach(s=>{ if(board[s.station]==null) board[s.station]=[]; board[s.station].push({t:s.dep, dir:tp.dir, peak:tp.peak}); }));
  Object.values(board).forEach(a=>a.sort((x,y)=>x.t-y.t));
  const spans=deps.map((d,i)=> i? d.t-deps[i-1].t:null).filter(x=>x!=null);
  TTD.plan={ line:r.name, color:r.color, round, run, layover, fleet:trains.length,
    trips, board, stationY, stations:outT.map(s=>s.station),
    deps, first, last, peakH, offH, wins,
    tripsPerDay: trips.length, minGap: spans.length?Math.min(...spans):0, maxGap: spans.length?Math.max(...spans):0 };
  ttdRender();
  toast(`Generated: ${r.name} · ${trips.length} departures · Required ${trains.length} Trains`);
}
function ttdRender(){
  const p=TTD.plan, box=$('#ttd-results'); if(!p||!box) return;
  const svg=ttdMarey(p);
  const metrics=`<div class="ttd-metrics">
    <div class="metric-card"><small>Theoretical train count</small><b>${p.fleet}</b><em>trains (including turnaround ${(p.layover/60).toFixed(1)} min)</em></div>
    <div class="metric-card"><small>Daily departures</small><b>${p.tripsPerDay}</b><em>${p.round?"Round trip":"One-way"}</em></div>
    <div class="metric-card"><small>Headway</small><b>${(p.peakH/60)}/${(p.offH/60)}</b><em>Peak / off-peak minutes</em></div>
    <div class="metric-card"><small>Template run</small><b>${durText(p.run)}</b><em>Loop ${durText(p.round?2*p.run+2*p.layover:p.run+p.layover)}</em></div>
  </div>`;
  const boards=ttdBoards(p);
  box.innerHTML = metrics + `<div class="ttd-diagram-wrap">${svg}</div>` + boards + ttdChecklist(p);
  $('#ttd-exports').hidden=false;
}
function ttdChecklist(p){
  const wins = p.wins.length ? p.wins.map(w=>`${secToClock(w[0])}–${secToClock(w[1]%86400)}`).join('、') : "(No peak windows)";
  const steps = [
    `Confirm first <b>${escapeHtml(p.line)}</b> already includes a return or loop in its stop sequence. Current plan ${p.round?"A symmetric return leg was added; the actual return route may differ":"Run the template as written; do not automatically add a path back to the origin"}。`,
    `Target first departure <b>${secToClock(p.first)}</b>, Last-departure limit <b>${secToClock(p.last%86400)}</b>${p.last>=86400?"(Next day)":''}; Peak ${p.peakH/60} min headway(${wins}), Off-peak ${p.offH/60} min. The final departure may be earlier than the service end limit.`,
    `Assumed wait after each turnaround / template completion ${(p.layover/60).toFixed(1)} min; theoretical fleet ${p.fleet} trains; excludes spares, depot moves and line conflicts.`,
    `This is a plan only, not a game write. Its JSON is not a game timetable export. To configure the game, use the custom operating-timetable editor below for lines, dates, entry times, per-train offsets and depot-return orders, then preview and write a new copy.`,
    `Load the copy in game. Check first/last departures, peak transitions, actual return trips and next-day connections. The depot-join extension cannot replace depot paths, signals or return orders.`,
  ];
  return `<details class="ttd-board ttd-check" open><summary>Plan assumptions and next steps</summary><div class="ttd-check-body"><ol>${steps.map(s=>`<li>${s}</li>`).join('')}</ol><p class="repair-note">Theoretical train graph ≠ in-game operating results. Passenger activity, routes, signals, pathfinding and shift conditions also affect actual operation.</p></div></details>`;
}
function ttdMarey(p){
  const W=980, padL=150, padR=24, padT=28, padB=42, rowH=26;
  const stns=p.stations, H=padT+padB+Math.max(1,stns.length-1)*rowH + rowH;
  const yMax=Math.max(1,...stns.map(s=>p.stationY[s]));
  const t0=p.first, t1=Math.max(...p.trips.flatMap(tp=>tp.stops.map(s=>s.dep)));
  const span=Math.max(600,t1-t0);
  const xOf=t=>padL+(t-t0)/span*(W-padL-padR);
  const yOf=s=>padT+(p.stationY[s]/yMax)*((stns.length-1)*rowH);
  const col=lineColor(p.color);
  let g='';
  for(let s=stns.length,hh=Math.floor(t0/3600); hh*3600<=t1; hh++){ const x=xOf(hh*3600); if(x<padL-1)continue; g+=`<line x1="${x.toFixed(1)}" y1="${padT}" x2="${x.toFixed(1)}" y2="${padT+(stns.length-1)*rowH}" class="ttd-grid-v"/><text x="${x.toFixed(1)}" y="${padT+(stns.length-1)*rowH+16}" class="ttd-xlab">${String(hh%24).padStart(2,'0')}</text>`; }
  stns.forEach(s=>{ const y=yOf(s); g+=`<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W-padR}" y2="${y.toFixed(1)}" class="ttd-grid-h"/><text x="${padL-8}" y="${(y+3).toFixed(1)}" class="ttd-ylab">${escapeHtml(s.length>18?s.slice(0,17)+'…':s)}</text>`; });
  let lines='';
  p.trips.forEach(tp=>{ const pts=tp.stops.map(s=>`${xOf(s.dep).toFixed(1)},${yOf(s.station).toFixed(1)}`).join(' '); lines+=`<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="${tp.peak?1.8:1.1}" opacity="${tp.dir==='ret'?0.5:0.9}"/>`; });
  return `<svg id="ttd-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="ttd-svg"><rect width="${W}" height="${H}" fill="var(--surface)"/><text x="${padL}" y="18" class="ttd-title">${escapeHtml(p.line)} · Train graph(Marey)</text>${g}${lines}</svg>`;
}
function ttdBoards(p){
  const rows=p.stations.map(s=>{ const list=(p.board[s]||[]).map(e=>`<span class="ttd-dep ${e.dir==='ret'?'ret':''} ${e.peak?'peak':''}">${secToClock(e.t)}</span>`).join(''); return `<tr><th>${escapeHtml(s)}</th><td>${list||'—'}</td></tr>`; }).join('');
  return `<details class="ttd-board"><summary>Stop-by-stop departure board(${p.round?"Including return trip":"One-way"}）</summary><div class="ttd-board-scroll"><table><tbody>${rows}</tbody></table></div></details>`;
}
function ttdExportCsv(){ const p=TTD.plan; if(!p) return toast("Generate a timetable first",true);
  let csv='trip,train,direction,band,station,arrival,departure\n';
  p.trips.forEach(tp=>tp.stops.forEach(s=>{ csv+=`${tp.run},${tp.train},${tp.dir},${tp.peak?'peak':'offpeak'},"${(s.station||'').replace(/"/g,'""')}",${secToClock(s.arr)},${secToClock(s.dep)}\n`; }));
  ttdDownload(csv,`${p.line.replace(/[\\/:*?"<>|]/g,'_')}_timetable.csv`,'text/csv');
}
function ttdExportJson(){ const p=TTD.plan; if(!p) return toast("Generate a timetable first",true);
  const out={ line:p.line, direction:p.round?'round':'single', fleet_required:p.fleet, trips_per_day:p.tripsPerDay, run_seconds:p.run, layover_seconds:p.layover, peak_headway_min:p.peakH/60, offpeak_headway_min:p.offH/60, peak_windows:p.wins.map(w=>`${secToClock(w[0])}-${secToClock(w[1]%86400)}`), stations:p.stations, trips:p.trips.map(t=>({run:t.run,train:t.train,dir:t.dir,band:t.peak?'peak':'offpeak',stops:t.stops.map(s=>({station:s.station,arrival:secToClock(s.arr),departure:secToClock(s.dep)}))})) };
  ttdDownload(JSON.stringify(out,null,2),`${p.line.replace(/[\\/:*?"<>|]/g,'_')}_timetable.json`,'application/json');
}
function ttdExportSvg(){ const svg=$('#ttd-svg'); if(!svg) return toast("Generate a train graph first",true); const s=new XMLSerializer().serializeToString(svg); ttdDownload(s,`${(TTD.plan?.line||'line').replace(/[\\/:*?"<>|]/g,'_')}_stringline.svg`,'image/svg+xml'); }
function ttdDownload(text,name,type){ const blob=new Blob([text],{type}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),500); }
$('#ttd-read')?.addEventListener('click',()=>{ const save=$('#save-select')?.value; if(!save) return toast("Select a save first",true); startTask('line-timetable',{save}); });
$('#ttd-line')?.addEventListener('change',()=>{ ttdSyncRun(); ttdSyncWriteLine(); });
$('#ttd-generate')?.addEventListener('click',ttdCompute);
$('#ttd-export-csv')?.addEventListener('click',ttdExportCsv);
$('#ttd-export-json')?.addEventListener('click',ttdExportJson);
$('#ttd-export-svg')?.addEventListener('click',ttdExportSvg);
$('#ttd-backfill')?.addEventListener('click',ttdBackfill);
$('#ttd-dwell')?.addEventListener('input',()=>{ ttdSyncRun(); });
$('#ttd-w-line')?.addEventListener('change',()=>{ ttdWriteRenderStops(); ttdWriteRefreshOutput(); });
$('#ttd-w-mode')?.addEventListener('change',()=>{ ttdWriteRenderStops(); ttdWriteRefreshOutput(); });
$('#ttd-w-stop')?.addEventListener('input',ttdWriteRefreshOutput);
$('#save-select')?.addEventListener('change',ttdWriteRefreshOutput);
$('#ttd-w-write')?.addEventListener('click',ttdWrite);
$('#ttd-w-perstop')?.addEventListener('click',(e)=>{
  const btn=e.target.closest('[data-fill]'); if(!btn) return;
  const r=ttdWriteRoute(); const stops=ttdWriteStops(r);
  document.querySelectorAll('#ttd-w-stoplist input[data-i]').forEach((inp,i)=>{
    if(btn.dataset.fill==='clear') inp.value='';
    else { const s=stops[i]; inp.value=Math.round((s?.dwell!=null? s.dwell : (s.departure-s.arrival))||0); }
  });
});
function onTimetableWriteDone(res){
  const box=$('#ttd-w-result');
  const file=(res.output_save||'').split(/[\\/]/).pop()||"New save";
  toast(`Written to a new save: ${file}`);
  if(!box) return;
  box.hidden=false; box.className='ttd-write-result ok';
  let head;
  if(res.mode==='per-stop' && Array.isArray(res.per_stop_seconds)){
    const man=res.after?.manual||[];
    const parts=res.per_stop_seconds.map((s,i)=> man[i]===false? `<span class="inh">stops ${i+1}:Inherit</span>` : `<span>stops ${i+1}:${s}s</span>`);
    head=`<b>✓ Per-stop changes written</b><br>Lines「${escapeHtml(res.line_name||'')}」：<span class="ttd-w-chips">${parts.join('')}</span>`;
  } else {
    const secs=res.stop_time_seconds; const b=res.before?.default_seconds;
    head=`<b>✓ Write completed</b><br>Lines「${escapeHtml(res.line_name||'')}」Dwell time ${b??'?'}s → <b>${secs}s</b>(Default value + ${res.stops_edited} per-stop copies; total ${res.fields_written} fields).`;
  }
  box.innerHTML=head
    +`<br>Byte-for-byte round-trip verification✓ · Other lines unchanged✓ · Compression readback✓`
    +`<br>New save: <code>${escapeHtml(file)}</code>`
    +`<br><small>Effective after loading; actual dwell ≈ configured dwell plus boarding/alighting time. Only a new save was created; the original is unchanged.</small>`;
}
async function ttdWrite(){
  const save=$('#save-select')?.value; if(!save) return toast("Select a save first",true);
  const r=ttdWriteRoute(); if(!r) return toast("Read lines from the save and select a line first",true);
  ttdWriteRefreshOutput();
  const output=$('#ttd-w-output')?.value; if(!output) return toast("Cannot generate output filename",true);
  const payload={ save, output, route: (r.id||r.name) };
  if(ttdWriteMode()==='perstop'){
    const list=ttdWriteCollectList();
    if(!list.length) return toast("This line has no configurable stops",true);
    if(list.every(v=>v===null)) return toast("Enter seconds for at least one stop (leave the rest blank＝Inherit)",true);
    for(const v of list){ if(v!==null && !(v>=1 && v<=600)) return toast("Per-stop dwell times must be between 1 and 600 seconds",true); }
    payload.dwell_list=list.map(v=>v===null?'':v);
  } else {
    const stop=+$('#ttd-w-stop')?.value;
    if(!(stop>=1 && stop<=600)) return toast("Dwell time must be between 1 and 600 seconds",true);
    payload.dwell=stop;
  }
  const box=$('#ttd-w-result'); if(box){ box.hidden=false; box.className='ttd-write-result'; box.textContent="Writing new save…"; }
  await startTask('timetable-write',payload);
}

/* ===== Custom persisted timetable editor ===== */
const OPR = { groups:[], selected:null, original:null, draft:null, activeGroup:0, copiedGroup:null, lines:[], dirty:false, baseSave:null };
const OPR_DAYS = [["Mon",1],["Tue",2],["Wed",4],["Thu",8],["Fri",16],["Sat",32],["Sun",64]];
function opruleClone(value){ return JSON.parse(JSON.stringify(value)); }
function opruleCurrent(){
  const id=$('#oprule-schedule')?.value;
  return OPR.groups.find(g=>g.schedule_id===id) || null;
}
function opruleFormatTime(seconds){
  if(seconds==null || !Number.isFinite(+seconds)) return '';
  const half=Math.round(+seconds*2), total=half/2, h=Math.floor(total/3600), m=Math.floor((total%3600)/60), s=total%60;
  const base=`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
  if(!s) return base;
  return `${base}:${String(Math.floor(s)).padStart(2,'0')}${s%1?'.5':''}`;
}
function opruleParseTime(value){
  const m=/^(\d{1,2}):([0-5]\d)(?::([0-5]\d)(?:\.(5))?)?$/.exec((value||'').trim());
  if(!m) return null;
  const seconds=(+m[1])*3600+(+m[2])*60+(+(m[3]||0))+(m[4]?0.5:0);
  return seconds<=172800 ? seconds : null;
}
function opruleDayText(mask){
  if(mask===127) return "Every day"; if(mask===31) return "Weekdays"; if(mask===96) return "Weekend";
  return OPR_DAYS.filter(([,bit])=>mask&bit).map(([name])=>name).join('') || "Not selected";
}
function opruleRefreshOutput(){
  const el=$('#oprule-output'); if(!el) return;
  const save=OPR.baseSave||$('#save-select')?.value;
  if(!save){el.value='';return;}
  const slash=Math.max(save.lastIndexOf('\\'),save.lastIndexOf('/')), dir=save.slice(0,slash+1), base=save.slice(slash+1).replace(/\.nimbyrails5$/i,'');
  el.value=`${dir}${base}_CustomTimetable_${timestamp()}.nimbyrails5`;
}
function opruleSetDirty(value=true){
  OPR.dirty=!!value;
  const label=$('#oprule-dirty');
  if(label){ label.textContent=OPR.dirty?"Unsaved changes":"Unchanged"; label.classList.toggle('dirty',OPR.dirty); }
  const reset=$('#oprule-reset'); if(reset) reset.disabled=!OPR.dirty;
  if (value) window.workspaceDraftChanged?.();
}
function opruleEntryEditable(entry,index){
  const p=entry.order_parameters||{};
  const out={ order_id:entry.order_id??null, line_id:entry.line_id, time_seconds:entry.time_seconds, days_mask:entry.days_mask,
    offset_group_index:entry.offset_group_index, repeat_is_max:!!entry.repeat_is_max,
    repeat_count:entry.repeat_is_max?null:Number(entry.repeat_count||1), continue_into_next:!!entry.continue_into_next,
    timing_event:Number(entry.timing_event??p.timing_event??2), enter_selector:Number(entry.enter_selector??p.enter_selector??1),
    exit_selector:Number(entry.exit_selector??p.exit_selector??1), timing_selector:Number(entry.timing_selector??p.timing_selector??1),
    timing_loop_bias:Number(entry.timing_loop_bias??p.timing_loop_bias??0),
    stacked_entries:(entry.stacked_entries||[]).map(child=>opruleEntryEditable(child)) };
  if(index!=null) out.index=index;
  return out;
}
function opruleDistributionEditable(group,index){
  return { group_index:index, mode:group.mode, fixed_interval_seconds:Number(group.fixed_interval_seconds||0),
    manual_duration_seconds:Number(group.manual_duration_seconds||0), duration_line_id:group.duration_line_id||null };
}
function opruleSyncEntries(){
  if(!OPR.draft) return [];
  $$('#oprule-entry-list [data-record-path]').forEach(row=>{
    const entry=opruleRecordAt(row.dataset.recordPath); if(!entry)return;
    let days=0; row.querySelectorAll('[data-day]:checked').forEach(ch=>{days|=+ch.dataset.day;});
    const repeatMax=!!row.querySelector('[data-repeat-max]')?.checked;
    const lineId=row.querySelector('[data-line]')?.value||entry.line_id;
    Object.assign(entry,{ line_id:lineId, line_name:OPR.lines.find(line=>line.id===lineId)?.name||lineId,
      time_seconds:opruleParseTime(row.querySelector('[data-time]')?.value), days_mask:days,
      offset_group_index:+row.querySelector('[data-offset-group]')?.value,
      offset_group_number:(+row.querySelector('[data-offset-group]')?.value)+1,
      repeat_is_max:repeatMax, repeat_count:repeatMax?null:+row.querySelector('[data-repeat-count]')?.value,
      continue_into_next:!!row.querySelector('[data-continue]')?.checked,
      timing_event:+row.querySelector('[data-timing-event]')?.value,
      enter_selector:+row.querySelector('[data-enter-selector]')?.value,
      exit_selector:+row.querySelector('[data-exit-selector]')?.value,
      timing_selector:+row.querySelector('[data-timing-selector]')?.value });
  });
  return OPR.draft.entries.map((entry,index)=>opruleEntryEditable(entry,index));
}
function opruleRecordAt(path){
  if(!OPR.draft||path==null)return null;
  const parts=String(path).split(':').map(Number), top=OPR.draft.entries[parts[0]];
  return parts.length===1?top:top?.stacked_entries?.[parts[1]]||null;
}
function opruleLine(selected){ return OPR.lines.find(line=>line.id===selected)||null; }
function opruleEntryLineOptions(selected){
  const lines=[...OPR.lines]; if(selected&&!lines.some(line=>line.id===selected))lines.push({id:selected,name:selected,selectors:[]});
  return lines.map(line=>`<option value="${escapeHtml(line.id)}" ${line.id===selected?'selected':''}>${escapeHtml(line.name||line.id)} · ${line.stop_count??'?'} stops</option>`).join('');
}
function opruleSelectorOptions(entry,kind){
  const line=opruleLine(entry.line_id), selected=Number(entry[`${kind}_selector`]??entry.order_parameters?.[`${kind}_selector`]??1);
  const sentinel={enter:"〈Line origin〉",exit:"〈Line destination〉",timing:"〈Same as entry stop〉"}[kind];
  let html=`<option value="1" ${selected===1?'selected':''}>${sentinel}</option>`;
  for(const option of line?.selectors||[]){
    html+=`<option value="${option.selector}" ${selected===option.selector?'selected':''}>${option.route_index+1}. ${escapeHtml(option.station_name||option.station_id||option.selector)}</option>`;
  }
  if(selected!==1&&!(line?.selectors||[]).some(option=>option.selector===selected)){
    html+=`<option value="${selected}" selected>⚠ Previous selection ${selected}(Keep)</option>`;
  }
  return html;
}
function opruleRenderRecord(entry,path,{stacked=false}={}){
  const p=entry.order_parameters||{}, topIndex=+String(path).split(':')[0];
  const checks=OPR_DAYS.map(([label,bit])=>`<label title="Days ${label}"><input type="checkbox" data-day="${bit}" ${(entry.days_mask&bit)?'checked':''}>${label}</label>`).join('');
  const groups=Array.from({length:10},(_,i)=>`<option value="${i}" ${entry.offset_group_index===i?'selected':''}>groups ${i+1}</option>`).join('');
  const timing=Number(entry.timing_event??p.timing_event??2), isNew=entry.order_id==null;
  return `<div class="oprule-entry ${stacked?'stacked':''}" data-record-path="${path}" data-entry="${topIndex}">`
    +(stacked?`<span class="oprule-stack-glyph" title="Stacking sub-order">↳</span>`:`<label class="oprule-rowpick" title="Add to batch"><input type="checkbox" data-row-select checked></label>`)
    +`<label class="oprule-field oprule-line">Lines / Line<select data-line>${opruleEntryLineOptions(entry.line_id)}</select><small>${stacked?"Stacking":''} Orders · Order ${isNew?"Assign automatically":escapeHtml(entry.order_id)} · ${escapeHtml(entry.line_id)}</small></label>`
    +`<label class="oprule-field">Time<input type="text" data-time value="${opruleFormatTime(entry.time_seconds)}" placeholder="HH:MM[:SS.5]"></label>`
    +`<div class="oprule-dayblock"><span class="oprule-days">${checks}</span><span class="oprule-day-presets"><button type="button" data-row-days="127">Every day</button><button type="button" data-row-days="31">Weekdays</button><button type="button" data-row-days="96">Weekend</button></span></div>`
    +`<label class="oprule-field">Offset groups<select data-offset-group>${groups}</select></label>`
    +`<div class="oprule-field oprule-repeat">Repeat<div class="oprule-repeat-controls"><label><input type="checkbox" data-repeat-max ${entry.repeat_is_max?'checked':''}>∞</label><input type="number" min="1" max="100" step="1" data-repeat-count value="${entry.repeat_count||1}" ${entry.repeat_is_max?'disabled':''}></div></div>`
    +`<label class="oprule-continue"><input type="checkbox" data-continue ${entry.continue_into_next?'checked':''}>Continue to next order</label>`
    +`<div class="oprule-routing">`
    +`<label class="oprule-field">Timing mode<select data-timing-event><option value="0" ${timing===0?'selected':''}>Exact arrival</option><option value="2" ${timing===2?'selected':''}>Exact departure</option><option value="4" ${timing===4?'selected':''}>Arrive no later than</option></select></label>`
    +`<label class="oprule-field">Entry stop<select data-enter-selector>${opruleSelectorOptions(entry,'enter')}</select></label>`
    +`<label class="oprule-field">Exit stop<select data-exit-selector>${opruleSelectorOptions(entry,'exit')}</select></label>`
    +`<label class="oprule-field">Timing stop<select data-timing-selector>${opruleSelectorOptions(entry,'timing')}</select></label>`
    +`</div><div class="oprule-entry-actions">`
    +(!stacked?`<button type="button" class="text-button" data-entry-insert="${path}">Insert after</button><button type="button" class="text-button" data-entry-stack="${path}">Add stacking order</button>`:'')
    +(isNew?`<button type="button" class="text-button danger" data-entry-remove="${path}">Remove added item</button>`:'')
    +`</div><details class="oprule-advanced"><summary>Structure details · ${isNew?"Order ID Assigned automatically when writing":`Order ${escapeHtml(entry.order_id)}`}</summary><div class="oprule-raw-grid">`
    +`<span>Line ID<b>${escapeHtml(entry.line_id)}</b></span><span>Loop bias<b>${escapeHtml(entry.timing_loop_bias??p.timing_loop_bias??0)}</b></span><span>Stack count<b>${(entry.stacked_entries||[]).length}</b></span><span>Original parameters<b>${escapeHtml(entry.order_parameters_hex||"Added")}</b></span>`
    +`</div></details></div>`;
}
function opruleRenderEntries(){
  const list=$('#oprule-entry-list'); if(!list||!OPR.draft) return;
  list.innerHTML=OPR.draft.entries.map((entry,index)=>`<div class="oprule-entry-block" data-entry-block="${index}">${opruleRenderRecord(entry,String(index))}<div class="oprule-stack-list">${(entry.stacked_entries||[]).map((child,childIndex)=>opruleRenderRecord(child,`${index}:${childIndex}`,{stacked:true})).join('')}</div></div>`).join('');
}
function opruleRenderSummary(){
  const box=$('#oprule-summary'); if(!box||!OPR.draft) return;
  const entries=OPR.draft.entries, all=entries.flatMap(entry=>[entry,...(entry.stacked_entries||[])]), valid=all.filter(e=>e.time_seconds!=null), times=valid.map(e=>e.time_seconds);
  const used=new Set(entries.map(e=>e.offset_group_index)).size, dayTypes=new Set(entries.map(e=>e.days_mask)).size;
  const audit=opruleAudit(all), status=audit.errors.length?`${audit.errors.length} errors`:audit.warnings.length?`${audit.warnings.length} warnings`:"All passed";
  box.innerHTML=[["Top-level / stacked",`${entries.length} / ${all.length-entries.length}`,''],["Time range",times.length?`${opruleFormatTime(Math.min(...times))}–${opruleFormatTime(Math.max(...times))}`:"Needs correction",''],["Days / offset group",`${dayTypes} / ${used}`,''],["Validation",status,'']]
    .map(([label,value,unit])=>`<div><small>${label}</small><b>${escapeHtml(value)}${unit||''}</b></div>`).join('');
  const auditBox=$('#oprule-audit'); if(auditBox){
    const messages=[...audit.errors.map(text=>`<span class="error">${escapeHtml(text)}</span>`),...audit.warnings.map(text=>`<span>${escapeHtml(text)}</span>`)];
    auditBox.classList.toggle('has-error',!!audit.errors.length);
    auditBox.innerHTML=messages.length?messages.join(''):"<span class=\"ok\">No missing fields or simultaneous-order conflicts found. Deadhead connections, track occupancy and actual dispatching are not yet verified.</span>";
  }
}
function opruleAudit(entries){
  const errors=[],warnings=[],slots=new Map();
  for(const entry of entries){
    if(entry.time_seconds==null)errors.push("Unrecognized time value");
    if(!entry.days_mask)errors.push("An order has no days selected");
    if(!entry.line_id)errors.push("An order has no Line selected");
    const line=opruleLine(entry.line_id), selectors=line?.selectors||[];
    for(const [label,value] of [['Enter',entry.enter_selector],['Exit',entry.exit_selector],['Timing',entry.timing_selector]]){
      if(value!==1&&!selectors.some(option=>option.selector===Number(value)))warnings.push(`${label} ${value} is the previous stop selection for this Line; it is retained unchanged unless the Line changes`);
    }
    if(entry.time_seconds!=null){
      const key=`${entry.time_seconds}`;
      for(const other of slots.get(key)||[]){if(other.days_mask&entry.days_mask)warnings.push(`${opruleFormatTime(entry.time_seconds)} Concurrent orders have overlapping days`);}
      slots.set(key,[...(slots.get(key)||[]),entry]);
    }
  }
  return {errors:[...new Set(errors)],warnings:[...new Set(warnings)]};
}
function opruleRenderTimeline(){
  const box=$('#oprule-timeline'); if(!box||!OPR.draft) return;
  const records=OPR.draft.entries.flatMap((entry,index)=>[{entry,path:String(index),stacked:false},...(entry.stacked_entries||[]).map((child,childIndex)=>({entry:child,path:`${index}:${childIndex}`,stacked:true}))]);
  const markers=records.map(({entry,path,stacked})=>{
    if(entry.time_seconds==null) return '';
    const day=Math.floor(entry.time_seconds/86400), left=Math.max(1,Math.min(99,((entry.time_seconds%86400)/86400)*100));
    return `<button type="button" class="oprule-time-marker ${stacked?'stacked':''}" data-jump-record="${path}" data-position="${left}" style="left:${left}%" title="${escapeHtml(entry.line_name||entry.line_id)}"><b>${opruleFormatTime(entry.time_seconds)}</b><em>${stacked?"Stacking · ":''}${day?`+${day} Sun · `:''}${escapeHtml(entry.line_name||entry.line_id)}</em></button>`;
  }).join('');
  box.innerHTML='<div class="oprule-time-axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div><div class="oprule-time-track">'+markers+'</div>';
  requestAnimationFrame(opruleLayoutTimeline);
}
function opruleLayoutTimeline(){
  const box=$('#oprule-timeline'),track=box?.querySelector('.oprule-time-track'); if(!box||!track)return;
  const markers=[...track.querySelectorAll('.oprule-time-marker')], width=track.clientWidth; if(!width)return;
  const laneEnds=[];
  const measured=markers.map(marker=>{
    marker.style.left='0px'; marker.style.top='8px';
    const markerWidth=Math.min(width-8,marker.offsetWidth||120), position=(+marker.dataset.position||0)/100*width;
    return {marker,markerWidth,position};
  }).sort((a,b)=>a.position-b.position);
  for(const item of measured){
    const half=item.markerWidth/2, center=Math.max(half+4,Math.min(width-half-4,item.position));
    const start=center-half, end=center+half; let lane=laneEnds.findIndex(right=>start>=right+10);
    if(lane<0){lane=laneEnds.length;laneEnds.push(end);}else laneEnds[lane]=end;
    item.marker.style.left=`${center}px`; item.marker.style.top=`${8+lane*48}px`; item.marker.style.setProperty('--stem',`${8+lane*48}px`);
    item.marker.dataset.lane=String(lane);
  }
  box.style.minHeight=`${Math.max(112,58+Math.max(1,laneEnds.length)*48)}px`;
}
function opruleModeSummary(group){
  if(group.mode==='fixed') return group.fixed_interval_seconds?`${group.fixed_interval_seconds/60} min`:"0 min";
  if(group.mode==='manual-duration') return group.manual_duration_seconds?`${group.manual_duration_seconds/60} min total duration`:"0 min total duration";
  return "Line duration";
}
function opruleRenderGroupTabs(){
  const box=$('#oprule-group-tabs'); if(!box||!OPR.draft) return;
  const used=Array(10).fill(0); OPR.draft.entries.flatMap(e=>[e,...(e.stacked_entries||[])]).forEach(e=>{if(e.offset_group_index>=0&&e.offset_group_index<10)used[e.offset_group_index]++;});
  const button=(group,index)=>`<button type="button" class="oprule-group-tab ${used[index]?'used':''} ${OPR.activeGroup===index?'active':''}" data-offset-tab="${index}"><b>groups ${index+1}</b><small>${used[index]} items · ${escapeHtml(opruleModeSummary(group))}</small></button>`;
  const shown=[],unused=[];OPR.draft.offset_distributions.forEach((group,index)=>{(used[index]||OPR.activeGroup===index?shown:unused).push(button(group,index));});
  box.innerHTML=shown.join('')+(unused.length?`<details><summary>Unused ${unused.length} offset groups</summary>${unused.join('')}</details>`:'');
}
function opruleLineOptions(selected){
  const lines=[...OPR.lines];
  if(selected&&!lines.some(x=>x.id===selected)) lines.push({id:selected,name:selected});
  return "<option value=\"\">Not set</option>"+lines.map(line=>`<option value="${escapeHtml(line.id)}" ${line.id===selected?'selected':''}>${escapeHtml(line.name||line.id)}</option>`).join('');
}
function opruleRenderGroupEditor(){
  const box=$('#oprule-group-editor'); if(!box||!OPR.draft) return;
  const group=OPR.draft.offset_distributions[OPR.activeGroup]; if(!group) return;
  const mins=value=>(Number(value||0)/60).toFixed(2).replace(/\.00$/,'').replace(/(\.\d)0$/,'$1');
  box.innerHTML=`<label class="oprule-field">Distribution<select data-group-mode><option value="fixed" ${group.mode==='fixed'?'selected':''}>Fixed interval</option><option value="manual-duration" ${group.mode==='manual-duration'?'selected':''}>Distribute over manual total duration</option><option value="line-duration" ${group.mode==='line-duration'?'selected':''}>Distribute over line running time</option></select></label>`
    +`<label class="oprule-field">Fixed interval (min)<input type="number" min="0" max="1440" step="0.5" data-group-fixed value="${mins(group.fixed_interval_seconds)}"><small>${group.mode==='fixed'?"Active value":"Stored value"}</small></label>`
    +`<label class="oprule-field">Manual total duration (min)<input type="number" min="0" max="1440" step="0.5" data-group-manual value="${mins(group.manual_duration_seconds)}"><small>${group.mode==='manual-duration'?"Active value":"Stored value"}</small></label>`
    +`<label class="oprule-field">Duration source line<select data-group-line>${opruleLineOptions(group.duration_line_id)}</select><small>${group.mode==='line-duration'?"This mode requires a selection":"Not used in fixed/manual mode"}</small></label>`
    +`<div class="oprule-quick-intervals">Quick fixed interval: ${[1,2,5,7,10,15,30].map(x=>`<button type="button" class="text-button" data-fixed-min="${x}">${x} min</button>`).join('')}</div>`
    +`<div class="oprule-group-note">All three inputs are stored separately; changing modes retains inactive values. A fixed interval offsets individual trains on the same order. It is not the running time between stations.</div>`;
}
function opruleRenderDerived(){ opruleRenderSummary(); opruleRenderTimeline(); opruleRenderGroupTabs(); }
function opruleRenderAll(){
  const editor=$('#oprule-editor'); if(!editor) return;
  editor.hidden=!OPR.draft;
  if(!OPR.draft) return;
  const smartLine=$('#oprule-smart-line'); if(smartLine){const selected=smartLine.value||OPR.draft.entries.at(-1)?.line_id;smartLine.innerHTML=opruleEntryLineOptions(selected);}
  opruleRenderEntries(); opruleRenderDerived(); opruleRenderGroupEditor(); opruleRefreshOutput();
  const result=$('#oprule-result'); if(result) result.hidden=true;
}
function opruleLoadGroup(group){
  OPR.selected=group?.schedule_id||null; OPR.original=group?opruleClone(group):null; OPR.draft=group?opruleClone(group):null; OPR.activeGroup=0; OPR.copiedGroup=null;
  opruleSetDirty(false); const paste=$('#oprule-paste-group'); if(paste) paste.disabled=true; opruleRenderAll();
  window.workspaceDraftLoad?.();
}
function renderOperatingRules(res){
  OPR.fingerprint=res.fingerprint||null;
  OPR.groups=(res.groups||[]).filter(g=>g.editable);
  OPR.lines=res.lines||[];
  OPR.baseSave=res.save||$('#save-select')?.value||null;
  if(!OPR.lines.length){
    const map=new Map(); OPR.groups.forEach(g=>g.entries.forEach(e=>map.set(e.line_id,e.line_name||e.line_id)));
    OPR.lines=[...map].map(([id,name])=>({id,name}));
  }
  OPR.groups.sort((a,b)=>(a.entries.length>1?0:1)-(b.entries.length>1?0:1)||a.schedule_name.localeCompare(b.schedule_name,globalThis.document?.documentElement?.lang || 'en'));
  const sel=$('#oprule-schedule'); if(!sel) return;
  sel.disabled=!OPR.groups.length;
  sel.innerHTML=OPR.groups.length?OPR.groups.map(g=>`<option value="${escapeHtml(g.schedule_id)}">${escapeHtml(g.schedule_name)} · ${escapeHtml(g.entries.map(e=>e.line_name||e.line_id).join(' → '))}</option>`).join(''):"<option value=\"\">No operating rules eligible for safe editing</option>";
  const airport=OPR.groups.findIndex(g=>g.schedule_name==='OT Line 4 Daily'); if(airport>=0) sel.selectedIndex=airport;
  ['#oprule-export','#oprule-import'].forEach(id=>{const el=$(id);if(el)el.disabled=!OPR.groups.length;});
  opruleLoadGroup(opruleCurrent());
  toast(`Loaded ${OPR.groups.length} operating-rule objects (including line templates) and ${OPR.lines.length} lines`);
}
function opruleSelectedRows(){ return $$('#oprule-entry-list [data-record-path]:not(.stacked)').filter(row=>row.querySelector('[data-row-select]')?.checked); }
function opruleApplyDays(rows,mask){
  rows.forEach(row=>row.querySelectorAll('[data-day]').forEach(ch=>{ch.checked=!!(mask&+ch.dataset.day);}));
  opruleSyncEntries(); opruleSetDirty(); opruleRenderDerived();
}
function opruleApplyShift(direction){
  const amount=+$('#oprule-shift')?.value;
  if(!(amount>=0.5&&amount<=1440)) return toast("The time shift must be between 0.5 and 1440 minutes",true);
  const rows=opruleSelectedRows(); if(!rows.length) return toast("Select the orders to shift first",true);
  for(const row of rows){
    const input=row.querySelector('[data-time]'), current=opruleParseTime(input?.value); if(current==null) return toast("Correct the selected orders' times first",true);
    let next=current+direction*amount*60; while(next<0)next+=86400; while(next>172800)next-=86400; input.value=opruleFormatTime(next);
  }
  opruleSyncEntries(); opruleSetDirty(); opruleRenderDerived();
}
function opruleNewRecord(source,timeSeconds){
  const record=opruleEntryEditable(source);
  record.order_id=null; record.time_seconds=Math.min(172800,Math.max(0,timeSeconds)); record.stacked_entries=[];
  record.enter_selector=1; record.exit_selector=1; record.timing_selector=1;
  record.repeat_is_max=false; record.repeat_count=1;
  record.line_name=opruleLine(record.line_id)?.name||record.line_id;
  return record;
}
function opruleInsertAfter(path){
  opruleSyncEntries(); const index=+String(path).split(':')[0], source=OPR.draft?.entries[index]; if(!source)return;
  if(OPR.draft.entries.length>=32)return toast("Top-level orders reached the safety limit of 32",true);
  const next=OPR.draft.entries[index+1], current=Number(source.time_seconds||0);
  const suggested=next?.time_seconds>current+1?(current+next.time_seconds)/2:current+1800;
  OPR.draft.entries.splice(index+1,0,opruleNewRecord(source,Math.round(suggested*2)/2));
  opruleSetDirty(); opruleRenderAll();
}
function opruleAddStack(path){
  opruleSyncEntries(); const index=+String(path).split(':')[0], parent=OPR.draft?.entries[index]; if(!parent)return;
  parent.stacked_entries=parent.stacked_entries||[]; if(parent.stacked_entries.length>=32)return toast("This order reached the limit of 32 stacked orders",true);
  const source=parent.stacked_entries.at(-1)||parent;
  let interval=420;
  if(parent.stacked_entries.length>=2){
    const a=parent.stacked_entries.at(-2).time_seconds,b=parent.stacked_entries.at(-1).time_seconds;
    if(b>a)interval=b-a;
  }else{
    const group=OPR.draft.offset_distributions?.[source.offset_group_index];
    if(group?.mode==='fixed'&&group.fixed_interval_seconds>0)interval=group.fixed_interval_seconds;
  }
  parent.stacked_entries.push(opruleNewRecord(source,Number(source.time_seconds||0)+interval));
  opruleSetDirty(); opruleRenderAll();
}
function opruleRemoveNew(path){
  opruleSyncEntries(); const parts=String(path).split(':').map(Number), record=opruleRecordAt(path); if(!record||record.order_id!=null)return toast("Orders already present in the save cannot be deleted in safe mode",true);
  if(parts.length===1){if(OPR.draft.entries.length<=1)return toast("A timetable needs at least one top-level order",true);OPR.draft.entries.splice(parts[0],1);}
  else OPR.draft.entries[parts[0]].stacked_entries.splice(parts[1],1);
  opruleSetDirty(); opruleRenderAll();
}
function opruleSortEntries(){
  opruleSyncEntries(); OPR.draft.entries=OPR.draft.entries.map((entry,index)=>({entry,index})).sort((a,b)=>(a.entry.time_seconds??Infinity)-(b.entry.time_seconds??Infinity)||a.index-b.index).map(item=>item.entry);
  opruleSetDirty(); opruleRenderAll(); toast("Top-level orders sorted by time; stacked orders remain with their parents");
}
function opruleGenerateSmart(){
  if(!OPR.draft)return; opruleSyncEntries();
  const lineId=$('#oprule-smart-line')?.value, start=opruleParseTime($('#oprule-smart-start')?.value), end=opruleParseTime($('#oprule-smart-end')?.value);
  const headway=(+$('#oprule-smart-headway')?.value)*60, days=+$('#oprule-smart-days')?.value, offset=+$('#oprule-smart-group')?.value;
  if(!lineId||start==null||end==null||end<start)return toast("Review the generated lines and start/end times",true);
  if(!(headway>=30&&headway<=86400))return toast("Departure intervals must be between 0.5 and 1440 minutes",true);
  const count=Math.floor((end-start)/headway)+1;
  if(count<1||OPR.draft.entries.length+count>32)return toast(`This will generate ${count} orders; the top-level count would exceed the safety limit 32`,true);
  const seed=OPR.draft.entries.find(entry=>entry.line_id===lineId)||OPR.draft.entries[0];
  for(let i=0;i<count;i++){
    const record=opruleNewRecord({...seed,line_id:lineId,days_mask:days,offset_group_index:offset,timing_event:2},start+i*headway);
    record.days_mask=days; record.offset_group_index=offset; record.timing_event=2;
    OPR.draft.entries.push(record);
  }
  OPR.draft.entries.sort((a,b)=>(a.time_seconds??Infinity)-(b.time_seconds??Infinity));
  opruleSetDirty(); opruleRenderAll(); toast(`Generated ${count} target departure orders; IDs are assigned when writing. Actual departures remain subject to the game's simulation`);
}
function opruleSyncGroupFromEditor(){
  const group=OPR.draft?.offset_distributions?.[OPR.activeGroup]; if(!group) return;
  group.mode=$('[data-group-mode]')?.value||group.mode;
  group.fixed_interval_seconds=Math.max(0,(+$('[data-group-fixed]')?.value||0)*60);
  group.manual_duration_seconds=Math.max(0,(+$('[data-group-manual]')?.value||0)*60);
  group.duration_line_id=$('[data-group-line]')?.value||null;
  opruleSetDirty(); opruleRenderGroupTabs();
}
function opruleDiff(){
  const entries=opruleSyncEntries(), all=entries.flatMap(entry=>[entry,...entry.stacked_entries]);
  if(all.some(e=>e.time_seconds==null)) throw new Error("Expected time format HH:MM, HH:MM:SS or HH:MM:SS.5");
  if(all.some(e=>!e.days_mask)) throw new Error("Select at least one day for each order");
  if(all.some(e=>!e.repeat_is_max&&!(e.repeat_count>=1&&e.repeat_count<=100))) throw new Error("Repeat count must be between 1 and 100, or choose ∞");
  if(all.some(e=>![0,2,4].includes(e.timing_event)))throw new Error("Invalid Timing event");
  if(all.some(e=>!OPR.lines.some(line=>line.id===e.line_id)))throw new Error("Contains objects not belonging to the current save Line ID");
  const distributions=OPR.draft.offset_distributions.map(opruleDistributionEditable);
  for(const group of distributions){
    if(group.fixed_interval_seconds<0||group.fixed_interval_seconds>86400||group.manual_duration_seconds<0||group.manual_duration_seconds>86400) throw new Error(`Offset groups ${group.group_index+1} has minutes outside the valid range`);
    if(group.group_index===0&&!group.duration_line_id) throw new Error("Offset group 1 must retain its duration source line");
    if(group.mode==='line-duration'&&!group.duration_line_id) throw new Error(`Offset groups ${group.group_index+1} Select a source line when using line duration`);
  }
  const beforeEntries=OPR.original.entries.map(opruleEntryEditable);
  const beforeGroups=OPR.original.offset_distributions.map(opruleDistributionEditable);
  const entryChanged=JSON.stringify(entries)!==JSON.stringify(beforeEntries);
  return { entry_plan:entryChanged?entries:null, entry_changes:entryChanged?all.length:0, distributions:distributions.filter((group,i)=>JSON.stringify(group)!==JSON.stringify(beforeGroups[i])) };
}
async function opruleWrite(){
  const save=OPR.baseSave||$('#save-select')?.value;
  if(!save) return toast("Select a save first",true); if(!OPR.draft) return toast("Load and select a timetable first",true);
  let changes; try{ changes=opruleDiff(); }catch(e){ return toast(e.message,true); }
  if(!changes.entry_plan&&!changes.distributions.length) return toast("The current plan makes no changes",true);
  opruleRefreshOutput(); const output=$('#oprule-output')?.value; if(!output) return toast("Cannot generate output filename",true);
  const newCount=(changes.entry_plan||[]).flatMap(entry=>[entry,...entry.stacked_entries]).filter(entry=>entry.order_id==null).length;
  if(!confirm(`Will write the complete order plan ${newCount?`(Added ${newCount} items Order ID)`:''}, Edit ${changes.distributions.length} offset groups and create a new save.
The original save will not be overwritten. Continue?`)) return;
  const box=$('#oprule-result'); if(box){box.hidden=false;box.className='ttd-write-result';box.textContent="Creating and verifying a custom-timetable save…";}
  await startTask('operating-rule-write',{save,output,fingerprint:OPR.fingerprint,schedule:OPR.draft.schedule_id,entry_plan:changes.entry_plan,distributions:changes.distributions});
}
function oprulePlan(){
  const diff=opruleDiff();
  return { format:'nimby-custom-timetable-v2', exported_at:new Date().toISOString(), schedule_id:OPR.draft.schedule_id, schedule_name:OPR.draft.schedule_name,
    entries:OPR.draft.entries.map(opruleEntryEditable), offset_distributions:OPR.draft.offset_distributions.map(opruleDistributionEditable), changed:diff };
}
function opruleExportPlan(){
  if(!OPR.draft) return;
  let plan; try{plan=oprulePlan();}catch(e){return toast(e.message,true);}
  const blob=new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}), url=URL.createObjectURL(blob), link=document.createElement('a');
  link.href=url; link.download=`${OPR.draft.schedule_name.replace(/[\\/:*?"<>|]/g,'_')}_Custom timetable.json`; link.click(); URL.revokeObjectURL(url); toast("Timetable-plan download started. Confirm the file was saved; it can be imported into this editor");
}
async function opruleImportPlan(file){
  if(!file||!OPR.draft) return;
  try{
    const plan=JSON.parse(await file.text());
    if(!['nimby-custom-timetable-v1','nimby-custom-timetable-v2'].includes(plan.format)||!Array.isArray(plan.entries)||!Array.isArray(plan.offset_distributions)) throw new Error("Not a timetable plan exported by this toolkit");
    if(plan.offset_distributions.length!==10) throw new Error("The plan must contain 10 offset groups");
    if(plan.format==='nimby-custom-timetable-v1'){
      if(plan.entries.length!==OPR.draft.entries.length)throw new Error("The older plan's order count does not match the current timetable");
      plan.entries.forEach((entry,index)=>Object.assign(OPR.draft.entries[index],opruleEntryEditable({...OPR.draft.entries[index],...entry},index)));
    }else{
      const persisted=new Set(OPR.original.entries.flatMap(entry=>[entry,...(entry.stacked_entries||[])]).map(entry=>entry.order_id).filter(id=>id!=null));
      const imported=plan.entries.flatMap(entry=>[entry,...(entry.stacked_entries||[])]);
      if(plan.entries.length<1||plan.entries.length>32||imported.length>128)throw new Error("The plan exceeds the safety limit of 32 top-level orders or 128 total records");
      const ids=new Set(imported.map(entry=>entry.order_id).filter(id=>id!=null));
      if([...persisted].some(id=>!ids.has(id))||[...ids].some(id=>!persisted.has(id)))throw new Error("The plan must retain all existing objects in this save Order ID");
      if(imported.some(entry=>!OPR.lines.some(line=>line.id===entry.line_id)))throw new Error("The plan references objects absent from this save Line ID");
      OPR.draft.entries=plan.entries.map((entry,index)=>opruleEntryEditable(entry,index));
    }
    plan.offset_distributions.forEach((group,index)=>Object.assign(OPR.draft.offset_distributions[index],opruleDistributionEditable(group,index)));
    opruleSetDirty(); opruleRenderAll(); toast(`Plan imported: ${plan.schedule_name||file.name}`);
  }catch(e){toast(`Import failed: ${e.message}`,true);}
  finally{const input=$('#oprule-import');if(input)input.value='';}
}
function onOperatingRuleWriteDone(res){
  OPR.fingerprint=res.output_file_sha256||null;
  const box=$('#oprule-result'), after=res.after||{}, file=(res.output_save||'').split(/[\\/]/).pop()||"New save";
  const index=OPR.groups.findIndex(g=>g.schedule_id===after.schedule_id); if(index>=0) OPR.groups[index]=after;
  OPR.baseSave=res.output_save||OPR.baseSave; OPR.original=opruleClone(after); OPR.draft=opruleClone(after); opruleSetDirty(false); opruleRenderEntries(); opruleRenderDerived(); opruleRenderGroupEditor(); opruleRefreshOutput();
  window.workspaceDraftLoad?.();
  toast(`Custom-timetable save created: ${file}`); if(!box)return;
  const rows=(after.entries||[]).map(e=>`${escapeHtml(e.line_name||e.line_id)} ${opruleFormatTime(e.time_seconds)} · ${opruleDayText(e.days_mask)} · groups ${e.offset_group_number} · ${e.repeat_is_max?'∞':`x${e.repeat_count}`}`).join('<br>');
  box.hidden=false; box.className='ttd-write-result ok'; box.innerHTML=`<b>✓ Custom timetable written</b><br>${rows}<br>Order-parameter readback✓ · Read back all ten offset groups✓ · Other timetables unchanged✓ · Compression readback✓<br>New save: <code>${escapeHtml(file)}</code><br><small>The original save was not changed. Further edits use the new save above. Load it while paused and check the Orders, Offsets and Timetable pages.</small>`;
}
$('#oprule-read')?.addEventListener('click',()=>{const save=$('#save-select')?.value;if(!save)return toast("Select a save first",true);startTask('operating-rules',{save});});
$('#oprule-schedule')?.addEventListener('change',event=>{if(OPR.dirty&&!confirm("Switch timetable? Successfully saved drafts can be restored for the same save. If draft saving failed, export the plan first.")){event.target.value=OPR.selected;return;}opruleLoadGroup(opruleCurrent());});
$('#oprule-entry-list')?.addEventListener('input',event=>{
  if(event.target.matches('[data-row-select]'))return; const row=event.target.closest('[data-record-path]'); if(!row)return;
  if(event.target.matches('[data-repeat-max]'))row.querySelector('[data-repeat-count]').disabled=event.target.checked;
  opruleSyncEntries();
  if(event.target.matches('[data-line]')){
    const record=opruleRecordAt(row.dataset.recordPath); if(record){record.enter_selector=1;record.exit_selector=1;record.timing_selector=1;record.line_name=opruleLine(record.line_id)?.name||record.line_id;}
    opruleRenderEntries();
  }
  opruleSetDirty();opruleRenderDerived();
});
$('#oprule-entry-list')?.addEventListener('click',event=>{
  const days=event.target.closest('[data-row-days]'); if(days)return opruleApplyDays([days.closest('[data-record-path]')],+days.dataset.rowDays);
  const insert=event.target.closest('[data-entry-insert]'); if(insert)return opruleInsertAfter(insert.dataset.entryInsert);
  const stack=event.target.closest('[data-entry-stack]'); if(stack)return opruleAddStack(stack.dataset.entryStack);
  const remove=event.target.closest('[data-entry-remove]'); if(remove)return opruleRemoveNew(remove.dataset.entryRemove);
});
$('#oprule-select-all')?.addEventListener('change',event=>$$('#oprule-entry-list [data-row-select]').forEach(ch=>{ch.checked=event.target.checked;}));
$$('[data-op-days]').forEach(button=>button.addEventListener('click',()=>{const rows=opruleSelectedRows();if(!rows.length)return toast("Select an order first",true);opruleApplyDays(rows,+button.dataset.opDays);}));
$$('[data-op-shift]').forEach(button=>button.addEventListener('click',()=>opruleApplyShift(+button.dataset.opShift)));
$('#oprule-timeline')?.addEventListener('click',event=>{const marker=event.target.closest('[data-jump-record]');if(marker)document.querySelector(`#oprule-entry-list [data-record-path="${marker.dataset.jumpRecord}"]`)?.scrollIntoView({behavior:'smooth',block:'center'});});
$('#oprule-sort')?.addEventListener('click',opruleSortEntries);
$('#oprule-smart-generate')?.addEventListener('click',opruleGenerateSmart);
$('#oprule-group-tabs')?.addEventListener('click',event=>{const tab=event.target.closest('[data-offset-tab]');if(!tab)return;OPR.activeGroup=+tab.dataset.offsetTab;opruleRenderGroupTabs();opruleRenderGroupEditor();});
$('#oprule-group-editor')?.addEventListener('input',opruleSyncGroupFromEditor);
$('#oprule-group-editor')?.addEventListener('click',event=>{const button=event.target.closest('[data-fixed-min]');if(!button)return;const input=$('[data-group-fixed]');input.value=button.dataset.fixedMin;opruleSyncGroupFromEditor();opruleRenderGroupEditor();});
$('#oprule-copy-group')?.addEventListener('click',()=>{if(!OPR.draft)return;OPR.copiedGroup=opruleClone(OPR.draft.offset_distributions[OPR.activeGroup]);$('#oprule-paste-group').disabled=false;toast(`Offset group duplicated ${OPR.activeGroup+1}`);});
$('#oprule-paste-group')?.addEventListener('click',()=>{if(!OPR.copiedGroup||!OPR.draft)return;const index=OPR.activeGroup,current=OPR.draft.offset_distributions[index],pasted=opruleClone(OPR.copiedGroup);if(index===0&&!pasted.duration_line_id)pasted.duration_line_id=current.duration_line_id;OPR.draft.offset_distributions[index]={...pasted,group_index:index,group_number:index+1};opruleSetDirty();opruleRenderGroupTabs();opruleRenderGroupEditor();});
$('#oprule-reset')?.addEventListener('click',()=>{if(!OPR.original||!confirm("Discard all unsaved changes to this timetable?"))return;OPR.draft=opruleClone(OPR.original);OPR.activeGroup=0;opruleSetDirty(false);opruleRenderAll();window.workspaceDraftChanged?.();});
$('#oprule-export')?.addEventListener('click',opruleExportPlan);
$('#oprule-import')?.addEventListener('change',event=>opruleImportPlan(event.target.files?.[0]));
$('#oprule-write')?.addEventListener('click',opruleWrite);
$('#save-select')?.addEventListener('change',()=>{OPR.groups=[];OPR.original=null;OPR.draft=null;OPR.dirty=false;OPR.baseSave=null;const sel=$('#oprule-schedule');if(sel){sel.disabled=true;sel.innerHTML="<option value=\"\">Reload the data</option>";}const ed=$('#oprule-editor');if(ed)ed.hidden=true;opruleRefreshOutput();});
window.addEventListener('resize',()=>requestAnimationFrame(opruleLayoutTimeline));

$('#update-check')?.addEventListener('click', () => checkToolkitUpdate(true));
$('#update-install')?.addEventListener('click', installToolkitUpdate);
$('#update-dismiss')?.addEventListener('click', () => { $('#update-banner').hidden = true; });
$('#update-auto-check')?.addEventListener('change', async event => {
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify({ auto_check_updates: event.target.checked }) });
    toast(event.target.checked ? "Automatic update checks enabled" : "Automatic checks disabled; you can still check manually");
  } catch (error) {
    event.target.checked = !event.target.checked;
    toast(error.message, true);
  }
});

setInterval(()=>fetch(`/api/ping?_=${Date.now()}`,{cache:'no-store'}).catch(()=>{}),5000);
loadBootstrap().catch(e=>{window.toolkitStartup?.fail(e.name==='AbortError'?"Startup data timed out; reload the interface.":e.message);toast(e.message,true);});
