/* Language changes reload presentation assets, never rewrite player data. */
(() => {
  const language = document.documentElement.lang === 'zh-CN' ? 'zh-CN' : 'en';
  window.NimbyLocale = {language};
  document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('language-select');
    if (!select) return;
    select.value = language;
    select.addEventListener('change', async () => {
      const next = select.value;
      select.value = language;
      if (next === language) return;
      const zh = language === 'zh-CN';
      const dock = document.getElementById('task-dock');
      if ((typeof state !== 'undefined' && state.taskActive) || (dock && !dock.hidden)) {
        alert(zh ? '请等待当前任务完成后再切换语言。' : 'Wait for the current task to finish before changing language.');
        return;
      }
      if (!confirm(zh ? '切换语言需要重新加载界面。尚未保存的输入和预览将丢失；游戏存档不会改变。继续吗？' :
        'Changing language reloads the interface. Unsaved inputs and previews will be lost; game saves will not change. Continue?')) return;
      try {
        const response = await fetch('/api/settings', {method:'POST',headers:{'Content-Type':'application/json','X-NIMBY-Language':language},body:JSON.stringify({language:next})});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Could not save language preference.');
        const url = new URL(location.href);url.searchParams.set('lang',next);location.replace(url.href);
      } catch (error) { alert(error.message); }
    });
  });
})();
