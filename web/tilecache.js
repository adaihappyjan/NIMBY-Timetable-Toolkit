/* Dedicated panel: no save selection, exports, or long-running task dock. */
(() => {
  viewMeta.tilecache = ['LOCAL TILE CACHE', 'ORM 地图缓存'];
  let current = null, busy = false, dirty = false;
  const fields = ['directory', 'port', 'max', 'age', 'offline', 'auto'];
  function showURL() {
    $('#tc-url').value = current?.urls?.[$('#tc-style').value] || '';
  }
  function render(data) {
    current = data;
    $('#tc-state').textContent = !data.running ? '已停止' : data.config.offline ? '运行中 · 只读缓存' : data.paused_seconds ? `联网暂停 · ${data.paused_seconds} 秒` : '运行中 · 按需缓存';
    $('#tc-stats').textContent = data.running ? `${data.count} 块瓦片 · 内容 ${formatBytes(data.bytes)} / ${data.config.max_mb} MB · 磁盘 ${formatBytes(data.disk_bytes)} · 命中 ${data.hits} · 下载 ${data.downloads} · 失败 ${data.errors}` : '启动后可查看已有缓存、容量与命中统计。';
    $('#tc-performance').textContent = data.running ? `待完成 ${data.pending ?? '—'} · 正在下载 ${data.active_downloads ?? '—'} · 合并重复请求 ${data.coalesced ?? '—'} · 队列满 ${data.queue_full ?? '—'} · 等待超时 ${data.wait_timeouts ?? '—'} · 平均下载 ${data.average_fetch_ms ?? '—'} ms · 平均等待 ${data.average_wait_ms ?? '—'} ms` : '';
    $('#tc-error').textContent = data.last_error || '';
    const game = data.game_start || {};
    $('#tc-game-start').textContent = game.enabled ? '关闭随游戏启动' : '开启随游戏启动';
    $('#tc-game-status').textContent = game.enabled ? `游戏联动：已开启 · ${game.watcher_running ? '检测器运行中' : '检测器启动中或待登录'}${game.error ? ' · ' + game.error : ''}` : '游戏联动：已关闭';
    if (!dirty) {
      $('#tc-directory').value = data.config.directory;
      $('#tc-port').value = data.config.port;
      $('#tc-max').value = data.config.max_mb;
      $('#tc-age').value = data.config.max_age_days;
      $('#tc-offline').checked = data.config.offline;
      $('#tc-auto').checked = data.config.autostart;
    }
    for (const id of ['stop', 'prune', 'clear']) $(`#tc-${id}`).disabled = !data.running;
    $('#tc-start').disabled = !!data.running;
    $('#tc-directory').disabled = $('#tc-port').disabled = !!data.running;
    showURL();
  }
  async function perform(action) {
    if (busy) return;
    if (action === 'clear' && !confirm('只删除本缓存数据库中的 ORM 瓦片，不修改存档。删除后需要重新联网下载。确定清空？')) return;
    if (action === 'stop' && !confirm('停止后游戏的本机 ORM 图层将无法加载。确定停止后台缓存服务？')) return;
    if (action === 'start' && dirty) { toast('请先保存设置，再启动缓存。', true); return; }
    const payload = {action};
    if (action === 'game-start') payload.enabled = !current?.game_start?.enabled;
    if (action === 'config') payload.config = {
      directory: $('#tc-directory').value.trim(), port: Number($('#tc-port').value),
      max_mb: Number($('#tc-max').value), max_age_days: Number($('#tc-age').value),
      offline: $('#tc-offline').checked, autostart: $('#tc-auto').checked
    };
    busy = true;
    $('#view-tilecache').setAttribute('aria-busy', 'true');
    const buttons = [...$('#view-tilecache').querySelectorAll('button')];
    buttons.forEach(b => b.disabled = true);
    try {
      const result = action === 'status' ? await api('/api/tilecache/status') : await api('/api/tilecache/action', {method:'POST', body:JSON.stringify(payload), timeoutMs:60000});
      if (action === 'config') dirty = false;
      render(result.cache);
      if (action !== 'status') toast(({start:'缓存已在后台启动，关闭工具箱后仍可使用。',stop:'缓存服务已停止。',config:'缓存设置已保存。',clear:'瓦片缓存已清空。',prune:'已按容量和保留时间清理。','game-start':payload.enabled ? '已开启随游戏启动，无需先打开工具箱。' : '已关闭游戏联动并移除启动项；当前缓存服务不受影响。'})[action]);
    } catch (error) {
      $('#tc-error').textContent = error.message;
      toast(`地图缓存：${error.message}`, true);
    } finally {
      busy = false;
      $('#view-tilecache').setAttribute('aria-busy', 'false');
      buttons.forEach(b => b.disabled = false);
      if (current) {
        for (const id of ['stop','prune','clear']) $(`#tc-${id}`).disabled = !current.running;
        $('#tc-start').disabled = !!current.running;
      }
    }
  }
  for (const id of fields) $(`#tc-${id}`).addEventListener('input', () => {dirty = true;});
  for (const action of ['start','stop','prune','clear']) $(`#tc-${action}`).onclick = () => perform(action);
  $('#tc-refresh').onclick = () => perform('status');
  $('#tc-save').onclick = () => perform('config');
  $('#tc-game-start').onclick = () => perform('game-start');
  $('#tc-style').onchange = showURL;
  $('#tc-copy').onclick = async () => {
    const input = $('#tc-url');
    if (!input.value) return;
    try { await navigator.clipboard.writeText(input.value); toast('地图源地址已复制。'); }
    catch { input.focus(); input.select(); toast('地址已选中，请按 Ctrl+C 复制。'); }
  };
  window.refreshTileCache = () => perform('status');
})();
