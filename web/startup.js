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
    const message = String(reason || '未知启动错误').slice(0, 1200);
    if (errors.length < 10) errors.push(message);
    show('界面未完成启动：' + message);
  }
  window.toolkitStartup = {
    errors,
    ready() { ready = true; clearTimeout(timer); const box = document.getElementById('startup-error'); if (box) box.hidden = true; },
    fail: failed,
  };
  window.addEventListener('error', event => {
    if (ready) return;
    const target = event.target;
    if (target && target.tagName === 'SCRIPT') failed('未能加载界面组件 ' + (target.src || '').split('/').pop());
    else if (event.message) failed(event.message + (event.lineno ? '（第 ' + event.lineno + ' 行）' : ''));
  }, true);
  window.addEventListener('unhandledrejection', event => { if (!ready) failed(event.reason?.message || event.reason); });
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('startup-reload')?.addEventListener('click', () => {
      // Never reload automatically: preserve any partially entered form values.
      if (window.confirm('重新加载工具箱页面？未保存的界面填写会清空，游戏和存档不会被修改。')) window.location.reload();
    });
    if (errors.length) show('界面未完成启动：' + errors[errors.length - 1]);
    if (!ready) timer = setTimeout(() => show('界面加载超过 25 秒。可点击“重新加载界面”；如仍失败，请把这里的提示发给作者。'), 25000);
  });
})();
