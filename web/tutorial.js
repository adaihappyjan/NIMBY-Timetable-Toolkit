/* Local, resumable tutorials. Reading a lesson never changes a save. */
(() => {
  const lessons = [
    ['start','01 / START','第一次使用：从体检开始','dashboard',[
      '在游戏保存完成后，回到工具箱，在总览选择对应存档；不确定时先刷新文件列表。',
      '点击「开始体检 · 免 JSON」。先处理严重问题，再查看提醒。健康分只衡量可检查的结构，不是运行保证。',
      '需要时刻表数据时：在游戏中暂停并保存，再保持暂停、执行时刻表数据导出。等待生成 Timetable Export JSON，回工具箱刷新文件，选择这对存档与数据，点击「核对存档与游戏导出」。工具箱不能代替游戏完成这次导出。']],
    ['batch','02 / PLAN','勾选多条线路，一次配置','workspace',[
      '读取所选存档，搜索表名、线路或车辆；勾选独立运营表。线路模板默认隐藏，避免误改。',
      '只填写需要修改的日期、首班、回库时间和逐车偏移。留空的时间保持原值；单站线路不一定是你的车库，请确认。',
      '先预览逐表差异，再创建新存档。逐车偏移不等于实际稳定班距；取消周末运营日也不会终止周五的无限循环，仍需回库 / 结束接续。复杂表请进入完整编排器。']],
    ['editor','03 / EDIT','编排器：修改、撤销与草稿','timetable',[
      '打开运营规则的完整编排器，选择时刻表。进入时间决定如何接入线路，校时点决定列车在哪里等待。',
      '修改后可撤销 / 重做最近 20 步。草稿按存档内容与表 ID 保存；不同内容的存档不会误套旧草稿。',
      '先检查工作日 / 周末、跨午夜时间、回库指令 x1，再写入副本。分时段预设只接受符合条件的简单表。']],
    ['accept','04 / VERIFY','游戏验收：不只看「写入成功」','workspace',[
      '保留原存档，回游戏加载工具箱生成的新文件；不要直接覆盖原档。',
      '检查首班出库、正常服务、高峰切换、末班回库和次日接班。留意计时停站、信号等待与「X 秒后启动」循环。',
      '完成运行检查后，在游戏中暂停、保存当前副本，再导出时刻表数据。回工具箱刷新文件，用「任务与验收」选择这对文件核对；「已加载 / 已运行」是你的确认，不是工具自动判断。']],
    ['diagnostic','05 / DIAGNOSE','无法调度、轨道繁忙怎么排查','workspace',[
      '先用七天接续检查重叠班次和未安排车辆，再对照实际进库路径、容量与车长。计划停库不等于实际进库。',
      '诊断助手可安装只读日志模组；在游戏启用模组后，仅给少量测试列车绑定 Toolkit read-only diagnostic，并开启脚本日志。',
      '运行后把 NIMBY_DIAG 记录粘贴到诊断助手。SIGNAL_WAIT 是等待信号，不自动证明死锁；测试结束关闭日志以减少开销。']],
    ['corridor','06 / ANALYSE','共线班距、车库容量与运营排行','workspace',[
      '共线协调选择同方向的相邻站 ID，填写支线到共线入口的运行时间；生成的是目标发车序列，可下载 CSV。',
      '容量分析先指定实际车库与容量，再看计划峰值和超限时段。未知空驶时长、寻路与实时占用需要游戏判断。',
      '运营排行使用游戏导出的会计统计表 Accounting TSV（非时刻表 JSON），放入存档目录后刷新列表并选择。只能比较相同统计周期与对象粒度；缺失数据不是零，满载发车比例不是平均载客率。']],
    ['cleanup','07 / HOUSEKEEPING','清理副本与永久保留','cleanup',[
      '先查看清理预览；在“副本保留管理”把要长期使用的副本勾选为永久保留，再设置保留份数与天数。缺少生成记录或内容已改变的副本会跳过。',
      '自动清理默认关闭。开启后启动时直接按规则移入回收站，不逐次确认；手动清理则需确认预览。永久保留通过同名 .keep 文件记录，移动存档时也请保留该文件。',
      '历史与项目设置保存在用户配置目录。更新工具箱不会迁移、修复或删除你的游戏存档。']],
    ['update','08 / UPDATE','自动检查，确认后安全更新','dashboard',[
      '右上角「检查更新」读取 GitHub 正式版本。打开「启动时自动检查」后，每次启动按缓存策略检查；不会静默安装。',
      '看到新版后选择「下载并重启更新」。更新器校验 ZIP 校验和与逐文件清单，等待当前窗口退出，再替换程序文件。',
      '建议使用解压后的便携版；Git 源码目录不支持覆盖更新。旧版没有更新按钮时，先手动下载一次新便携版。安装失败会尝试回滚；若提示恢复不完整，不要继续使用，请保留日志和备份并重新解压完整包。']],
    ['map','09 / MAP','制作地铁线网图','map',[
      '先在游戏暂停、保存并导出时刻表数据。在线路图页点击“从游戏时刻表数据载入线路”，勾选要展示的线路。',
      '线路可按名称、编号或沿线站名搜索，并按 A–Z / Z–A、编号、站数或已选优先排序。过滤不取消勾选；“当前结果”按钮只影响显示出的线路。选择“地铁线网图”：默认结合名称、编号、颜色和共用区间识别同线路分支，共用主干只画一次，普通站不算分支之间的换乘。识别不对时，展开“同线路分支分组”，可将勾选项设为同组、保持独立或恢复自动；此操作也包括搜索隐藏的已选项。真正换乘可选大圆或胶囊形。同名不同 ID 的车站不会合并；缺少坐标的区间不画虚构连线。',
      '版式可选都市地铁或铁路总览，布局另可选“网格布局”：站点对齐网格，连线走水平和垂直方向；方向可横向、纵向或大致地理方向。站名沿线排布；可用 100% / 150% / 200% 查看细节。调整画布、站间距及字号。导出 SVG 保存图像，线路图 JSON 保留原始运营线路和显示合并关系；两者使用本页设置的导出文件夹。示意图不是地理比例，也不会修改游戏轨道。']]
  ];
  const faq = [
    ['时刻表 JSON 从哪里来？','由 NIMBY Rails 游戏内的时刻表数据导出功能生成，不是工具箱自动抓取。先暂停并保存，再保持暂停导出；回工具箱刷新文件列表，选择名称含 Timetable Export 的 JSON。工具箱导出的线路图、报告或方案 JSON 不能替代它。'],
    ['刚导出的 JSON 为什么仍不匹配？','请确认游戏保存的是同一份状态，导出对应的正是该存档。工作台会检查最近候选并说明原因；不要改文件名或忽略 ID 差异来绕过保护。'],
    ['为什么列车每隔几秒重新开始调度？','可能是接班位置、时间、线路入口或计划接续不满足。先看游戏的具体原因和日志，再检查车库与客运指令。不要用自动运行掩盖错误。'],
    ['Timetable garage join 会自动造车库吗？','不会。它是对既有列车的接班扩展，不会创建轨道、修复断轨、增加容量或绕过信号。先确认车辆所在位置和时刻表条件。'],
    ['后台任务是不是越多核越快？','读取和配对可以在后台处理，配对最多两个进程以控制内存。写存档始终互斥，写入期间不能强制取消；否则会增加损坏风险。'],
    ['美术升级后能看得更清楚吗？','开启本页「舒适阅读」可增大密集编排字段。键盘 Tab 可导航；Ctrl+K 搜索功能。教程进度保存在本机，勾选已读不会执行任何操作。']
  ];
  const section = document.createElement('section'); section.id='view-learn'; section.className='view';
  section.innerHTML = `<div class="learn-hero"><div><p class="eyebrow aqua">NIMBY TOOLKIT / FIELD GUIDE</p><h2>让每一次修改，都有下一步。</h2><p>从一份存档开始，读懂计划、预览差异、再到游戏里验收。九个短教程，随时返回继续。</p><span class="learn-progress" id="learn-progress" role="status">0 / 9 已读</span></div><svg class="learn-network" viewBox="0 0 260 170" fill="none" aria-hidden="true"><path d="M8 25H74L152 105H248M8 85H80L147 25H248M8 145H110L180 75H248" stroke="#385765" stroke-width="12" stroke-linecap="round"/><path d="M8 25H74L152 105H248" stroke="#51ddc2" stroke-width="4"/><path d="M8 85H80L147 25H248" stroke="#7eacff" stroke-width="4"/><path d="M8 145H110L180 75H248" stroke="#efbc6d" stroke-width="4"/><g fill="#142531" stroke="#e3edf2" stroke-width="3"><circle cx="38" cy="25" r="6"/><circle cx="112" cy="64" r="9"/><circle cx="194" cy="105" r="6"/><circle cx="207" cy="25" r="6"/><circle cx="69" cy="145" r="6"/><circle cx="217" cy="75" r="6"/></g></svg></div>
    <div class="learn-warning">安全原则：先预览，再写副本。结构检查通过 ≠ 列车运行已通过；正式存档始终由你验收后决定是否替换。</div>
    <div class="learn-toolbar"><input type="search" id="learn-search" placeholder="搜索教程，例如：回库、更新、JSON…" aria-label="搜索教程"><label class="learn-density"><input type="checkbox" id="learn-readable">舒适阅读</label></div>
    <div class="learn-grid">${lessons.map(([id,num,title,view,steps])=>`<article class="learn-card" data-lesson="${id}"><span class="learn-number">${num}</span><h3>${escapeHtml(title)}</h3><ol>${steps.map(s=>`<li>${escapeHtml(s)}</li>`).join('')}</ol><div class="learn-actions"><button class="secondary-button" type="button" data-learn-view="${view}">前往${escapeHtml(viewMeta[view][1])} →</button><label><input type="checkbox" data-learn-done="${id}">我已读懂</label></div></article>`).join('')}</div>
    <p id="learn-empty" hidden role="status">没有找到相关教程，试试「车库」「存档」或「更新」。</p>
    <article class="panel learn-faq"><h3>遇到问题，先看这里</h3>${faq.map(([q,a])=>`<details><summary>${escapeHtml(q)}</summary><p>${escapeHtml(a)}</p></details>`).join('')}</article>`;
  document.querySelector('main').append(section);
  let prefs={done:[],readable:false}, changed=false, queue=Promise.resolve();
  function render(){
    section.querySelectorAll('[data-learn-done]').forEach(el=>{el.checked=prefs.done.includes(el.dataset.learnDone);el.closest('.learn-card').classList.toggle('done',el.checked);});
    $('#learn-progress').textContent=`${prefs.done.length} / ${lessons.length} 已读`;
    $('#learn-readable').checked=prefs.readable;document.body.classList.toggle('readable',prefs.readable);
  }
  function persist(){changed=true;const patch=JSON.parse(JSON.stringify(prefs));queue=queue.catch(()=>{}).then(()=>api('/api/workspace/state',{method:'POST',body:JSON.stringify({key:'tutorial-v1',patch})})).catch(()=>toast('教程进度未能保存，可继续阅读。',true));}
  section.addEventListener('click',e=>{const b=e.target.closest('[data-learn-view]');if(b)switchView(b.dataset.learnView);});
  section.addEventListener('change',e=>{
    if(e.target.matches('[data-learn-done]')){prefs.done=[...section.querySelectorAll('[data-learn-done]:checked')].map(el=>el.dataset.learnDone);render();persist();}
    if(e.target.id==='learn-readable'){prefs.readable=e.target.checked;render();persist();}
  });
  $('#learn-search').addEventListener('input',e=>{let visible=0;const q=e.target.value.trim().toLowerCase();section.querySelectorAll('.learn-card').forEach(el=>{el.hidden=!el.textContent.toLowerCase().includes(q);if(!el.hidden)visible++;});$('#learn-empty').hidden=visible>0;});
  $('#open-tutorial').addEventListener('click',()=>switchView('learn'));
  api('/api/workspace/state',{method:'POST',body:JSON.stringify({key:'tutorial-v1'})}).then(r=>{if(changed)return;const ids=new Set(lessons.map(l=>l[0]));prefs={done:[...new Set((Array.isArray(r.value?.done)?r.value.done:[]).filter(id=>ids.has(id)))],readable:r.value?.readable===true};render();}).catch(()=>{});
})();
