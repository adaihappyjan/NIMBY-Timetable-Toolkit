/* Dedicated panel: no save selection, exports, or long-running task dock. */
(() => {
  viewMeta.tilecache = ['LOCAL TILE CACHE', "ORM Map cache"];
  let current = null, busy = false, dirty = false;
  const fields = ['directory', 'port', 'max', 'age', 'offline', 'auto'];
  function showURL() {
    $('#tc-url').value = current?.urls?.[$('#tc-style').value] || '';
  }
  function render(data) {
    current = data;
    $('#tc-state').textContent = !data.running ? "Stopped" : data.config.offline ? "Running · Read-only cache" : data.paused_seconds ? `Network paused · ${data.paused_seconds} s` : "Running · On-demand cache";
    $('#tc-stats').textContent = data.running ? `${data.count} tiles · Content ${formatBytes(data.bytes)} / ${data.config.max_mb} MB · Disk ${formatBytes(data.disk_bytes)} · Hits ${data.hits} · Download ${data.downloads} · Failed ${data.errors}` : "Start the service to view cached tiles, size and hit statistics.";
    $('#tc-performance').textContent = data.running ? `Pending ${data.pending ?? '—'} · Downloading ${data.active_downloads ?? '—'} · Merge duplicate requests ${data.coalesced ?? '—'} · Queue full ${data.queue_full ?? '—'} · Wait timed out ${data.wait_timeouts ?? '—'} · Average download ${data.average_fetch_ms ?? '—'} ms · Average wait ${data.average_wait_ms ?? '—'} ms` : '';
    $('#tc-error').textContent = data.last_error || '';
    const game = data.game_start || {};
    $('#tc-game-start').textContent = game.enabled ? "Disable launch with game" : "Enable launch with game";
    $('#tc-game-status').textContent = game.enabled ? `Launch with game: on · ${game.watcher_running ? "Watcher running" : "Watcher starting or waiting for login"}${game.error ? ' · ' + game.error : ''}` : "Launch with game: off";
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
    if (action === 'clear' && !confirm("Delete only ORM tiles in this cache database; saves are unchanged. Tiles will need downloading again. Clear the cache?")) return;
    if (action === 'stop' && !confirm("The game's local ORM layer will stop loading. Stop the background cache service?")) return;
    if (action === 'start' && dirty) { toast("Save settings before starting the cache.", true); return; }
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
      if (action !== 'status') toast(({start:"Cache started in the background and remains available after closing the toolkit.",stop:"Cache service stopped.",config:"Cache settings saved.",clear:"Tile cache cleared.",prune:"Cleaned according to size and retention limits.",'game-start':payload.enabled ? "Launch with game enabled; no need to open the toolkit first." : "Launch-with-game disabled and startup entry removed; the running cache service is unaffected."})[action]);
    } catch (error) {
      $('#tc-error').textContent = error.message;
      toast(`Map cache: ${error.message}`, true);
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
    try { await navigator.clipboard.writeText(input.value); toast("Map source URL copied."); }
    catch { input.focus(); input.select(); toast("URL selected; press Ctrl+C to copy."); }
  };
  window.refreshTileCache = () => perform('status');
})();
