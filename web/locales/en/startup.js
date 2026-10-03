// Independent of app.js: a failed UI bundle must not leave a silent dead page.
(() => {
  'use strict';
  const errors = [];
  let ready = false, timer;
  function show(message) {
    if (ready) return;
    const box = document.getElementById('startup-error');
    if (!box) return;
    box.hidden = false;
    document.getElementById('startup-error-detail').textContent = message;
  }
  function failed(reason) {
    const message = String(reason || "Unknown startup error").slice(0, 1200);
    if (errors.length < 10) errors.push(message);
    show("Interface startup incomplete: " + message);
  }
  window.toolkitStartup = {
    errors,
    ready() { ready = true; clearTimeout(timer); const box = document.getElementById('startup-error'); if (box) box.hidden = true; },
    fail: failed,
  };
  window.addEventListener('error', event => {
    if (ready) return;
    const target = event.target;
    if (target && target.tagName === 'SCRIPT') failed("Interface component failed to load " + (target.src || '').split('/').pop());
    else if (event.message) failed(event.message + (event.lineno ? "(No. " + event.lineno + " rows)" : ''));
  }, true);
  window.addEventListener('unhandledrejection', event => { if (!ready) failed(event.reason?.message || event.reason); });
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('startup-reload')?.addEventListener('click', () => {
      // Never reload automatically: preserve any partially entered form values.
      if (window.confirm("Reload the toolkit page? Unsaved interface inputs will be cleared. The game and saves will not change.")) window.location.reload();
    });
    if (errors.length) show("Interface startup incomplete: " + errors[errors.length - 1]);
    if (!ready) timer = setTimeout(() => show("Loading took more than 25 seconds. Reload the interface. If it still fails, send this message to the project maintainer."), 25000);
  });
})();
