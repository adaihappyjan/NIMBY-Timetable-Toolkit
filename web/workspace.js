/* Line-centric workspace. All heavy work remains in the background process. */
(() => {
  'use strict';
  const esc = escapeHtml;
  const W = {catalog:null, selected:new Set(), preview:null, revision:0, results:{}, draft:null, undo:[], redo:[], restoring:false};
  const send = (path, value) => api(path, {method:'POST', body:JSON.stringify(value)});
  const clone = value => JSON.parse(JSON.stringify(value));
  const clock = value => {
    if(value == null) return '未知';
    const n=Math.round(value), day=Math.floor(n/86400), sec=((n%86400)+86400)%86400;
    return `${day?`第${day+1}天 `:''}${String(Math.floor(sec/3600)).padStart(2,'0')}:${String(Math.floor(sec%3600/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;
  };
  const parseTime = id => {
    const text=$(id).value.trim(); if(!text)return null;
    if(!/^\d{1,2}:\d{2}(:\d{2})?$/.test(text))throw new Error('时间请填 HH:MM 或 HH:MM:SS');
    const [h,m,s=0]=text.split(':').map(Number); if(h>48||m>59||s>59)throw new Error('时间范围无效'); return h*3600+m*60+s;
  };
  const table = (headers,rows) => `<div class="ws-scroll"><table><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(x=>`<td>${esc(x??'未知')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const section=document.createElement('section'); section.id='view-workspace'; section.className='view';
  section.innerHTML=`
    <div class="ws-intro"><div><h2>先选线路，再处理问题</h2><p>读取已保存文件，不控制游戏。不覆盖原存档。</p></div><button class="primary-button" id="ws-load">读取所选存档</button></div>
    <p id="ws-source">在“总览与体检”选择存档，再点击“读取所选存档”。此步骤不需要游戏时刻表导出。</p>
    <div id="ws-status" class="ws-notice" role="status" aria-live="polite">等待读取</div>
    <div class="ws-tools"><input id="ws-search" type="search" placeholder="搜索线路、时刻表、车辆名称或 ID…" aria-label="搜索运营对象"><label><input type="checkbox" id="ws-templates">显示线路模板</label><button id="ws-select-visible">勾选筛选结果</button><button id="ws-select-none">清空勾选</button><span id="ws-count">已选 0 张表</span></div>
    <div id="ws-catalog" class="ws-catalog"><p>尚未读取。</p></div>
    <div class="ws-tabs" role="tablist">${[['batch','批量配置'],['audit','接续与车库'],['corridor','共线协调'],['accounting','运营排行'],['diagnostic','诊断助手'],['tasks','任务与验收']].map(([id,name],i)=>`<button role="tab" aria-selected="${i===0}" data-ws-tab="${id}">${name}</button>`).join('')}</div>
    <article class="ws-panel" data-ws-panel="batch">
      <h3>批量预设 · 先预览，再写入</h3><p>只改勾选表中的指定字段。留空即保留原值；车库循环可固定为一次。</p>
      <div class="ws-fields"><label>运营日<select id="ws-days"><option value="">保持原样</option><option value="127">每天</option><option value="31">周一至周五</option><option value="15">周一至周四</option><option value="96">周六、周日</option><option value="custom">自行勾选</option></select></label>
      <label>首条客运指令时间<input id="ws-start" placeholder="05:30"></label><label>回库指令时间<input id="ws-depot-time" placeholder="00:30"></label><label>客运逐车偏移（秒）<input id="ws-interval" type="number" min="0.5" step="0.5" placeholder="保留原值"></label></div>
      <div id="ws-weekdays" hidden>${['一','二','三','四','五','六','日'].map((d,i)=>`<label><input type="checkbox" data-ws-day="${1<<i}">周${d}</label>`).join('')}</div>
      <p class="ws-notice">运营日决定指令何时开始，不会自动结束已有无限循环。若要周末停运，还需安排最后一个运营日之后的回库 / 结束接续，并检查游戏七天图。</p>
      <p>请选择确认为车库的线路（选择后该车库指令改为 x1）：</p><div id="ws-depots" class="ws-depots"></div>
      <p class="ws-muted">逐车偏移并非整段线路最终班距。多客运指令、堆积指令或车库共用偏移组时会阻止含糊的修改。</p>
      <details><summary>高峰 / 平峰分段预设（可选）</summary><p>每个边界创建一条 Max 客运指令，分配独立偏移组，保留已有回库指令。只支持当前恰好一条客运指令的表。不会自动验证列车能否维持目标班距。</p><label><input id="ws-periods-enabled" type="checkbox">使用分时段，替代上方首班与逐车偏移输入</label><div class="ws-fields">${[['05:30','900'],['07:00','420'],['09:30','900'],['15:30','420'],['18:00','900']].map(([t,n],i)=>`<label>第 ${i+1} 段开始<input id="ws-period-time-${i}" value="${t}" aria-label="第 ${i+1} 段开始"><input id="ws-period-offset-${i}" type="number" min="0.5" step="0.5" value="${n}" aria-label="第 ${i+1} 段逐车偏移秒数"><small>第二框为逐车偏移秒数；清空开始时间则跳过</small></label>`).join('')}</div></details>
      <div class="ws-tools"><button id="ws-preview" class="primary-button">预览勾选修改</button><button id="ws-apply" disabled>写入一个新存档</button><button id="ws-open-editor">打开所选表完整编排器</button></div><div id="ws-batch-result"></div>
    </article>
    <article class="ws-panel" data-ws-panel="audit" hidden><h3>七天接续与车库计划</h3><p>核对当前所选导出后检查一周，包括周日至周一。下方容量由你确认，不从轨道数量猜测。</p>
      <div id="ws-capacities" class="ws-fields"></div><div class="ws-tools"><button id="ws-pair">寻找兼容导出</button><button id="ws-audit" class="primary-button">检查全车队七天计划</button></div><div id="ws-pairs"></div><div id="ws-audit-result"></div></article>
    <article class="ws-panel" data-ws-panel="corridor" hidden><h3>共线入口协调器</h3><p>选择两条线路，再确认同方向相邻两站。相位基于共线入口；支线运行时间以秒填写。</p>
      <div class="ws-fields"><label>支线 A<select id="ws-line-a"></select></label><label>支线 B<select id="ws-line-b"></select></label><label>共同入口区间<select id="ws-segment"></select></label><label>A 始发至入口秒数<input id="ws-travel-a" type="number" value="0" min="0"></label><label>B 始发至入口秒数<input id="ws-travel-b" type="number" value="0" min="0"></label></div>
      <div class="ws-fields"><label>时段开始<input id="ws-window-start" value="07:00"></label><label>时段结束<input id="ws-window-end" value="09:30"></label><label>A 班距秒数<input id="ws-headway-a" type="number" value="420" min="10"></label><label>B 班距秒数<input id="ws-headway-b" type="number" value="840" min="10"></label><label>B 错开秒数<input id="ws-phase-b" type="number" value="210" min="0"></label></div>
      <div class="ws-tools"><button id="ws-add-window">加入时段</button><button id="ws-clear-windows">清空时段</button><button id="ws-corridor" class="primary-button">计算合流序列</button><button id="ws-download-corridor" disabled>导出序列 CSV</button></div><div id="ws-windows"></div><div id="ws-corridor-result"></div></article>
    <article class="ws-panel" data-ws-panel="accounting" hidden><h3>实际运营问题排行</h3><p>使用游戏导出的会计统计表（Accounting TSV），不是时刻表 JSON。先在游戏会计/统计界面执行统计数据导出，将 TSV 放入当前存档目录，再刷新列表。若游戏未提供该导出或没有统计数据，可跳过此项，不影响其他工具；这里显示历史统计，不是实时监控。</p>
      <div class="ws-fields"><label>会计导出<select id="ws-account-file"></select></label><label>对象<select id="ws-kind"><option value="line">线路</option><option value="station">车站</option><option value="train">列车</option></select></label><label>周期<select id="ws-period"><option value="daily">每日</option><option value="weekly">每周</option><option value="monthly">每月</option></select></label><label>日期 / 时间戳<select id="ws-account-stamp"><option value="">最新周期</option></select></label><label>指标<select id="ws-metric"><option value="trains_signal_stop_time">信号等待累计</option><option value="trains_late_arrival_time">到达晚点累计</option><option value="pax_waited_too_long">候车超时人数</option><option value="pax_lost">流失乘客</option><option value="train_departed_full">满载发车次数</option><option value="full_departure_ratio">满载发车比例</option></select></label></div>
      <button id="ws-account-refresh">刷新统计文件列表</button><button id="ws-accounting" class="primary-button">读取并排行</button><div id="ws-accounting-result"></div></article>
    <article class="ws-panel" data-ws-panel="diagnostic" hidden><h3>只读诊断模组 · 预览版</h3><p>不改变调度、占用检查或列车位置。仅对游戏内勾选扩展的列车采集状态，最多每 60 模拟秒输出一次，稳定状态每 5 分钟一次。1.19.10 已有零编译错误及部分状态运行记录；你的具体路网仍需单独验收。</p>
      <ol><li>点击安装，将模组放入当前存档目录的 mods 子目录。</li><li>游戏内启用 private mod，并在需检查的列车上启用 Toolkit read-only diagnostic。</li><li>本次会话手动开启脚本日志。短时运行后关闭日志，将文本粘贴到下方。</li></ol>
      <div class="ws-tools"><button id="ws-diag-status">检查文件安装状态</button><button id="ws-diag-install">安装只读诊断模组</button></div><p id="ws-diag-state">安装状态未读取；游戏内启用状态无法从文件存在与否推断。</p>
      <details><summary>安装工具箱生成的规则 / 车辆包</summary><p>先在“脚本规则”或“车辆工坊”生成包，再刷新列表。仅允许安装带本工具生成凭证且未被改动的包，不覆盖同名模组。</p><select id="ws-mod-package" aria-label="生成的模组包"></select><button id="ws-mod-refresh">刷新生成包</button><button id="ws-mod-install">安装选中包</button></details>
      <label>日志内容<textarea id="ws-log" rows="6" placeholder="粘贴包含 NIMBY_DIAG| 的日志，最多 500 KB"></textarea></label><button id="ws-log-parse">解读日志</button><div id="ws-log-result"></div></article>
    <article class="ws-panel" data-ws-panel="tasks" hidden><h3>任务中心与分步验收</h3><p>存档写入串行保护；兼容导出检查最多使用两个进程，并对大存档降低并行数。写入期间不能强制取消。</p><button id="ws-tasks-refresh">刷新任务历史</button><div id="ws-tasks"></div><div id="ws-acceptance"></div></article>`;
  $('main').append(section);
  const status = (message,error=false) => {$('#ws-status').textContent=message; $('#ws-status').classList.toggle('error',error);};
  function run(operation,payload={}) {
    if(state.taskActive) {toast('已有后台任务，请等它完成。',true);return;}
    status('正在后台处理，界面可以继续查看…');
    const save = $('#save-select').value;
    return startTask('workspace',{operation,save,...payload},{revision:W.revision,save,payload:clone(payload)});
  }
  function requireCatalog(){if(!W.catalog||W.catalog.save!==$('#save-select').value)throw new Error('存档已切换或尚未读取，请先读取所选存档。');}
  const guard = fn => async () => {try{await fn();}catch(e){status(e.message,true);toast(e.message,true);}};
  function filtered(){const term=$('#ws-search').value.trim().toLowerCase();return (W.catalog?.groups||[]).filter(g=>($('#ws-templates').checked||g.kind==='timetable')&&JSON.stringify([g.schedule_name,g.schedule_id,g.entries.map(e=>e.line_name),g.trains]).toLowerCase().includes(term));}
  function renderCatalog(){
    $('#ws-count').textContent=`已选 ${W.selected.size} 张表`;
    $('#ws-catalog').innerHTML=filtered().map(g=>`<label class="ws-card"><input type="checkbox" data-ws-group="${esc(g.schedule_id)}" ${W.selected.has(g.schedule_id)?'checked':''} ${g.kind==='template'?'disabled':''}><div><strong>${esc(g.schedule_name)}</strong><small>${g.kind==='template'?'线路模板':'独立运营表'} · ${g.trains.length} 列车 · ${g.entries.length} 条指令</small><span>${esc(g.entries.map(e=>`${clock(e.time_seconds)} ${e.line_name||e.line_id}`).join(' → '))}</span><details><summary>车辆与对象 ID</summary>${esc(g.schedule_id)}<p>${esc(g.trains.map(t=>t.name).join('、')||'没有分配车辆')}</p></details></div></label>`).join('')||'<p>没有匹配结果。试试线路名的一部分，或显示线路模板。</p>';
  }
  let projectTimer;
  function saveProject(){clearTimeout(projectTimer); const key=W.catalog?.save;if(!key)return;projectTimer=setTimeout(()=>{
    const fields={};$$('#view-workspace input[id],#view-workspace select[id]').forEach(e=>{fields[e.id]=e.type==='checkbox'?e.checked:e.value;});
    send('/api/workspace/state',{key:`workspace:${key}`,patch:{fields,selected:[...W.selected],windows:W.windows||[],depots:depotValues(),weekdays:$$('[data-ws-day]:checked').map(e=>e.dataset.wsDay)}}).catch(e=>status(`草稿保存失败：${e.message}`,true));
  },400);}
  async function restoreProject(){const key=W.catalog.save;const {value}=await send('/api/workspace/state',{key:`workspace:${key}`});if(key!==W.catalog?.save)return;
    W.selected=new Set((value.selected||[]).filter(id=>W.catalog.groups.some(g=>g.schedule_id===id&&g.kind==='timetable')));W.windows=value.windows||[];
    for(const [id,val] of Object.entries(value.fields||{})){const e=document.getElementById(id);if(e&&e.closest('#view-workspace')){if(e.type==='checkbox')e.checked=!!val;else e.value=val;}}
    for(const [id,cap] of Object.entries(value.depots||{})){const check=$$('[data-ws-depot]').find(e=>e.dataset.wsDepot===id);if(check)check.checked=true;const field=$$('[data-ws-capacity]').find(e=>e.dataset.wsCapacity===id);if(field)field.value=cap;}
    $$('[data-ws-day]').forEach(e=>e.checked=(value.weekdays||[]).includes(e.dataset.wsDay));
    updateSegments();renderWindows();renderCatalog();$('#ws-weekdays').hidden=$('#ws-days').value!=='custom';if(value.last_output)acceptance(value.last_output);
  }
  function depotValues(){const result={};$$('[data-ws-depot]:checked').forEach(e=>{const field=$$('[data-ws-capacity]').find(f=>f.dataset.wsCapacity===e.dataset.wsDepot);result[e.dataset.wsDepot]=Number(field?.value||0);});return result;}
  function batchRequest(){requireCatalog();const day=$('#ws-days').value;return {fingerprint:W.catalog.fingerprint,selected:[...W.selected],preset:{days_mask:day==='custom'?$$('[data-ws-day]:checked').reduce((n,e)=>n+Number(e.dataset.wsDay),0):day?+day:null,service_start:parseTime('#ws-start'),depot_time:parseTime('#ws-depot-time'),interval:$('#ws-interval').value?+$('#ws-interval').value:null,depot_ids:Object.keys(depotValues()),periods:$('#ws-periods-enabled').checked?[0,1,2,3,4].filter(i=>$(`#ws-period-time-${i}`).value.trim()).map(i=>({start:parseTime(`#ws-period-time-${i}`),interval:+$(`#ws-period-offset-${i}`).value})):null}};}
  function invalidate(){W.revision++;W.preview=null;W.batchPayload=null;$('#ws-apply').disabled=true;}
  function previewIsCurrent(context) {
    return !!context && context.revision===W.revision && context.save===$('#save-select').value;
  }
  section.addEventListener('change',e=>{if(e.target.matches('[data-ws-group]')){e.target.checked?W.selected.add(e.target.dataset.wsGroup):W.selected.delete(e.target.dataset.wsGroup);renderCatalog();}invalidate();saveProject();});
  section.addEventListener('input',e=>{if(e.target.id==='ws-search')renderCatalog(); if(e.target.id!=='ws-log'){invalidate();saveProject();}});
  $('#ws-load').onclick=()=>run('catalog');$('#ws-templates').onchange=renderCatalog;
  $('#ws-select-visible').onclick=()=>{filtered().filter(g=>g.kind==='timetable').forEach(g=>W.selected.add(g.schedule_id));invalidate();renderCatalog();saveProject();};
  $('#ws-select-none').onclick=()=>{W.selected.clear();invalidate();renderCatalog();saveProject();};
  $('#ws-days').onchange=()=>{$('#ws-weekdays').hidden=$('#ws-days').value!=='custom';};
  $$('[data-ws-tab]').forEach(b=>b.onclick=()=>{$$('[data-ws-panel]').forEach(p=>p.hidden=p.dataset.wsPanel!==b.dataset.wsTab);$$('[data-ws-tab]').forEach(t=>t.setAttribute('aria-selected',t===b));if(b.dataset.wsTab==='tasks'||b.dataset.wsTab==='accounting')files();});
  $('#ws-preview').onclick=guard(()=>{if(state.taskActive){toast('已有后台任务，请等它完成。',true);return;}const payload=batchRequest();invalidate();run('batch',payload);});
  $('#ws-apply').onclick=guard(()=>{if(!W.preview||!previewIsCurrent(W.previewContext)||JSON.stringify(batchRequest())!==JSON.stringify(W.batchPayload)){invalidate();throw new Error('参数或存档已改变，请重新预览。');}if(confirm(`将修改 ${W.preview.changes.length} 张运营表，并生成一个新存档。继续？`))run('batch',{...W.batchPayload,apply:true,preview_hash:W.preview.preview_hash,output:outputPath('Workspace')});});
  $('#ws-open-editor').onclick=guard(()=>{requireCatalog();if(W.selected.size!==1)throw new Error('请只勾选一张表打开编排器。');renderOperatingRules({save:W.catalog.save,groups:W.catalog.groups,lines:W.catalog.lines,fingerprint:W.catalog.fingerprint});const id=[...W.selected][0];$('#oprule-schedule').value=id;opruleLoadGroup(W.catalog.groups.find(g=>g.schedule_id===id));switchView('timetable');$('#oprule-editor').scrollIntoView({behavior:'smooth'});});
  $('#ws-pair').onclick=()=>run('pair');
  $('#ws-audit').onclick=guard(()=>{requireCatalog();run('audit',{export:$('#export-select').value,depots:depotValues()});});
  function updateSegments(){
    const a=W.catalog?.lines.find(l=>l.id===$('#ws-line-a').value),b=W.catalog?.lines.find(l=>l.id===$('#ws-line-b').value);const saved=$('#ws-segment').value;
    const edges=l=>(l?.selectors||[]).filter(s=>s.station_id).sort((a,b)=>a.route_index-b.route_index).flatMap((s,i,arr)=>i<arr.length-1?[{ids:[s.station_id,arr[i+1].station_id],name:`${s.station_name} → ${arr[i+1].station_name}`}]:[]);
    const ae=edges(a),be=edges(b),unique=(list,key)=>list.filter(e=>e.ids.join('|')===key).length===1;
    const bs=new Set(be.map(e=>e.ids.join('|')));const options=ae.filter(e=>bs.has(e.ids.join('|'))&&unique(ae,e.ids.join('|'))&&unique(be,e.ids.join('|')));
    $('#ws-segment').innerHTML=options.map(e=>`<option value="${esc(e.ids.join('|'))}">${esc(e.name)}</option>`).join('')||'<option value="">未找到同方向共同区间</option>';
    if(options.some(e=>e.ids.join('|')===saved))$('#ws-segment').value=saved;
  }
  ['#ws-line-a','#ws-line-b'].forEach(id=>$(id).onchange=()=>{W.windows=[];updateSegments();renderWindows();});
  function newWindow(){const a=$('#ws-line-a').value,b=$('#ws-line-b').value;if(a===b)throw new Error('请选择两条不同线路。');return {start:parseTime('#ws-window-start'),end:parseTime('#ws-window-end'),intervals:{[a]:+$('#ws-headway-a').value,[b]:+$('#ws-headway-b').value},phases:{[a]:0,[b]:+$('#ws-phase-b').value}};}
  function renderWindows(){$('#ws-windows').innerHTML=table(['已加入时段','两线班距 / 秒'],(W.windows||[]).map(w=>[`${clock(w.start)} – ${clock(w.end)}`,Object.values(w.intervals).join(' / ')]));}
  $('#ws-add-window').onclick=guard(()=>{(W.windows ||= []).push(newWindow());renderWindows();saveProject();});
  $('#ws-clear-windows').onclick=()=>{W.windows=[];renderWindows();saveProject();};
  $('#ws-corridor').onclick=guard(()=>{requireCatalog();const stations=$('#ws-segment').value.split('|');if(stations.length!==2)throw new Error('请选择同方向共同入口区间。');run('corridor',{branches:[{id:$('#ws-line-a').value,stations,entry_travel:+$('#ws-travel-a').value},{id:$('#ws-line-b').value,stations,entry_travel:+$('#ws-travel-b').value}],windows:W.windows?.length?W.windows:[newWindow()]});});
  function download(name,text,type='text/plain'){const url=URL.createObjectURL(new Blob(['\ufeff',text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  $('#ws-download-corridor').onclick=()=>download('共线发车序列.csv','线路ID,共线入口秒数,始发秒数,与前班间隔秒数\r\n'+(W.results.corridor?.events||[]).map(e=>[e.line,e.entry_time,e.origin_departure,e.gap].join(',')).join('\r\n'),'text/csv');
  $('#ws-accounting').onclick=()=>run('accounting',{accounting:$('#ws-account-file').value,kind:$('#ws-kind').value,period:$('#ws-period').value,metric:$('#ws-metric').value,timestamp:$('#ws-account-stamp').value||null});
  ['#ws-account-file','#ws-kind','#ws-period'].forEach(id=>$(id).onchange=()=>$('#ws-account-stamp').innerHTML='<option value="">最新周期</option>');
  async function files(){try{const res=await api('/api/workspace/files');const v=$('#ws-account-file').value;setOptions($('#ws-account-file'),res.accounting);if(res.accounting.some(f=>f.path===v))$('#ws-account-file').value=v;
    $('#ws-mod-package').innerHTML=(res.mod_packages||[]).map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('')||'<option value="">尚无本工具生成包，请先生成</option>';
    $('#ws-tasks').innerHTML=table(['开始时间','任务','结果','新存档 / 错误'],res.history.slice().reverse().map(t=>[new Date(t.started*1000).toLocaleString(),t.operation||t.action,t.ok?'已完成':'未完成',t.output||t.error||'只读任务']));
  }catch(e){status(e.message,true);}}
  $('#ws-tasks-refresh').onclick=files;
  $('#ws-mod-refresh').onclick=files;
  $('#ws-account-refresh').onclick=files;
  $('#ws-mod-install').onclick=guard(async()=>{const packageName=$('#ws-mod-package').value;if(!packageName)throw new Error('请先生成并选择模组包');if(!confirm(`安装 ${packageName} 到游戏 private mods？不会自动启用。`))return;const r=await send('/api/workspace/install-mod',{package:packageName});$('#ws-diag-state').textContent=`${r.path} · ${r.note}`;});
  async function diag(install){const r=await send('/api/workspace/diagnostic',{install});$('#ws-diag-state').textContent=`${r.path||''} ${r.installed||r.path?'模组文件已安装':'未安装'}；游戏内启用状态未知。请按上方步骤操作。`;}
  $('#ws-diag-status').onclick=guard(()=>diag(false));$('#ws-diag-install').onclick=guard(()=>{if(confirm('安装只读诊断预览模组？不会自动启用或覆盖已有不同文件。'))return diag(true);});
  $('#ws-log-parse').onclick=guard(async()=>{if($('#ws-log').value.length>500000)throw new Error('日志过长，请粘贴最近 500 KB 以内内容。');const r=await send('/api/workspace/log',{text:$('#ws-log').value});const labels={UNASSIGNED:'未分配班次',ASSIGNED:'已分配班次',TIMED_STOP:'计时停站',SIGNAL_WAIT:'等待信号'};$('#ws-log-result').innerHTML=`<p>${esc(r.scope)} 共 ${r.total} 条。</p>`+table(['状态','列车 / 信号'],r.records.map(e=>[labels[e.event]||e.event,e.detail]));});
  window.workspaceFailure=message=>status(message,true);
  window.workspaceResult=async (r,context)=>{
    W.results[r.operation]=r;status('已完成。'+(r.scope||''));
    if(r.operation==='catalog'){
      W.catalog=r;invalidate();const c=r.counts;$('#ws-source').textContent=`${r.save} · ${r.game_version?.save_release||'未知版本'} · ${c.timetables} 张独立运营表 / ${c.templates} 个线路模板 / ${c.trains} 列车（内部对象 ${c.objects}）`;
      const depots=r.lines.filter(l=>l.stop_count===1);$('#ws-depots').innerHTML=depots.map(l=>`<label><input type="checkbox" data-ws-depot="${esc(l.id)}">${esc(l.name)} <small>单站候选，请确认</small></label>`).join('')||'没有单站车库候选。';
      $('#ws-capacities').innerHTML=depots.map(l=>`<label>${esc(l.name)} 容量<input type="number" min="1" max="10000" data-ws-capacity="${esc(l.id)}" placeholder="请填写；需在批量页勾选此车库"></label>`).join('');
      const opts=r.lines.filter(l=>l.stop_count>1).map(l=>`<option value="${esc(l.id)}">${esc(l.name)}</option>`).join('');$('#ws-line-a').innerHTML=opts;$('#ws-line-b').innerHTML=opts;$('#ws-line-b').selectedIndex=Math.min(1,$('#ws-line-b').options.length-1);await restoreProject();await files();
    }else if(r.operation==='pair'){
      $('#ws-pairs').innerHTML=`<p>${esc(r.note)} · ${r.workers_used} 个工作进程</p>`+r.pairs.map((p,i)=>`<div class="ws-notice">${esc(p.path.split(/[\\/]/).pop())} · ${p.matched?'结构兼容':esc(p.reason)} ${p.matched?`<button data-ws-use-export="${i}">选用</button>`:''}</div>`).join('');
      $$('[data-ws-use-export]').forEach(b=>b.onclick=()=>{const p=r.pairs[+b.dataset.wsUseExport].path;const el=$('#export-select');if(![...el.options].some(o=>o.value===p))el.add(new Option(p.split(/[\\/]/).pop(),p));el.value=p;status('已选择兼容导出；执行前仍将再次核对。');});
    }else if(r.operation==='batch'){
      if(r.preview&&!previewIsCurrent(context)){
        invalidate();status('预览期间参数或存档已改变，旧结果已作废；请重新预览。',true);
        $('#ws-batch-result').textContent='旧预览已作废，未写入存档。';return;
      }
      W.previewContext=context;W.batchPayload=r.preview?context.payload:null;
      W.preview=r.preview?r:null;$('#ws-apply').disabled=!r.preview;
      $('#ws-batch-result').innerHTML=`<h4>${r.preview?'修改预览 · 尚未写入':'新存档已写入并反读校验'}</h4>${r.output_save?`<p>${esc(r.output_save)}</p>`:''}`+r.changes.map(c=>`<details open><summary>${esc(c.name)}</summary>${table(['指令','原时间 / 星期','新时间 / 星期','新重复'],c.after.entries.map(e=>{const old=c.before.entries.find(o=>o.order_id===e.order_id);return [e.line_name,old?`${clock(old.time_seconds)} / ${opruleDayText(old.days_mask)}`:'新增',`${clock(e.time_seconds)} / ${opruleDayText(e.days_mask)}`,e.repeat_is_max?'Max':`x${e.repeat_count}`];}))}${table(['偏移组','原模式 / 秒','新模式 / 秒'],c.after.offset_distributions.flatMap((g,i)=>JSON.stringify(g)!==JSON.stringify(c.before.offset_distributions[i])?[[i+1,`${c.before.offset_distributions[i].mode} / ${c.before.offset_distributions[i].fixed_interval_seconds}`,`${g.mode} / ${g.fixed_interval_seconds}`]]:[]))}</details>`).join('');
      if(!r.preview){acceptance(r);await send('/api/workspace/state',{key:`workspace:${r.input_save}`,patch:{last_output:{output_save:r.output_save,output_file_sha256:r.output_file_sha256}}});await refreshFileLists();await files();}
    }else if(r.operation==='audit'){
      $('#ws-audit-result').innerHTML=`<p>${esc(r.scope)}</p><h4>${r.coverage.length} 列车 · ${r.issues.filter(i=>i.status==='error').length} 个时间错误 · ${r.issues.filter(i=>i.status==='unknown').length} 项待确认</h4><p>没有可读计划：${r.without_plan?.length||0} 列车；未访问所选车库：${r.without_depot?.length||0} 列车（不等于一定没有其他车库）。</p>`+table(['列车','问题','时间','时间差（秒）'],r.issues.slice(0,500).map(i=>[i.train,i.problem,clock(i.time),i.seconds]))+`<p>最多展示 500 个问题。</p><details><summary>七天覆盖明细</summary>${table(['列车','出现计划的星期','计划段数'],r.coverage.map(c=>[c.train,c.days.map(d=>['一','二','三','四','五','六','日'][d]).join('、'),c.runs]))}</details>`+r.depots.map(d=>`<h4>${esc(W.catalog?.lines.find(l=>l.id===d.line)?.name||d.line)} · 计划峰值 ${d.planned_peak??'未知'} / 容量 ${d.capacity} · ${d.over_capacity==null?'缺少车库记录':d.over_capacity?'超容量':'未发现计划超容量'}</h4><p>一周占用区间（周一 → 周日，前 60 段）：</p><div class="ws-occupancy">${d.intervals.slice(0,60).map(([s,e,tid])=>`<div><small>${esc(tid)}</small><span><i style="left:${s/6048}%;width:${Math.max(.1,(e-s)/6048)}%" title="${esc(clock(s)+' → '+clock(e))}"></i></span></div>`).join('')}</div>${table(['时间','计划占用'],d.timeline.slice(0,200).map(t=>[clock(t.time),t.occupied]))}`).join('');
    }else if(r.operation==='corridor'){
      $('#ws-corridor-result').innerHTML=`<p>${esc(r.scope)} 共 ${r.events.length} 班，前 300 班如下。</p>`+table(['线路','入口时间','始发时间','与前班间隔 / 秒'],r.events.slice(0,300).map(e=>[W.catalog?.lines.find(l=>l.id===e.line)?.name||e.line,clock(e.entry_time),clock(e.origin_departure),e.gap]));$('#ws-download-corridor').disabled=false;
    }else if(r.operation==='accounting'){
      $('#ws-account-stamp').innerHTML='<option value="">最新周期</option>'+r.timestamps.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');$('#ws-account-stamp').value=r.timestamp;
      $('#ws-accounting-result').innerHTML=`<p>${esc(r.scope)} 统计日期：${esc(r.timestamp)}；共 ${r.rankings.length} 项。</p>`+table(['排名','对象','数值'],r.rankings.map((x,i)=>[i+1,x.name,x.value==null?'未知':r.metric==='full_departure_ratio'?`${(x.value*100).toFixed(2)}%`:Number(x.value.toFixed(2))]));
    }
  };
  async function acceptance(r){
    const key=`acceptance:${r.output_file_sha256}`,saved=(await send('/api/workspace/state',{key})).value;
    $('#ws-acceptance').innerHTML=`<h4>当前输出验收</h4><p>${esc(r.output_save)}</p><p>✓ 压缩反读校验完成 · 原存档保留</p><label><input id="ws-accept-load" type="checkbox" ${saved.loaded?'checked':''}>我已在游戏加载此输出存档</label><label><input id="ws-accept-run" type="checkbox" ${saved.running?'checked':''}>我已检查出库、班距与回库</label><p>这两项是用户确认，不是工具自动判定。</p><button id="ws-accept-export">选择此输出并核对新导出</button>`;
    ['#ws-accept-load','#ws-accept-run'].forEach(id=>$(id).onchange=()=>send('/api/workspace/state',{key,patch:{loaded:$('#ws-accept-load').checked,running:$('#ws-accept-run').checked}}).catch(e=>status(e.message,true)));
    $('#ws-accept-export').onclick=()=>{const s=$('#save-select');if(![...s.options].some(o=>o.value===r.output_save))s.add(new Option(r.output_save,r.output_save));s.value=r.output_save;run('pair');};
  }
  // Draft journal is independent from browser origin; reloads on the same save fingerprint only.
  const draftBar=document.createElement('div');draftBar.className='ws-tools';draftBar.innerHTML='<button id="ws-undo">撤销一步</button><button id="ws-redo">重做</button><span id="ws-draft-state">草稿保存在本机，不写入存档</span>';$('#oprule-editor')?.prepend(draftBar);
  let journal=Promise.resolve();
  function draftKey(){return OPR.fingerprint&&OPR.selected?`draft:${OPR.fingerprint}:${OPR.selected}`:null;}
  function persistDraft(){const key=draftKey();if(!key)return;const patch={draft:clone(OPR.draft),undo:clone(W.undo.slice(-20)),redo:clone(W.redo.slice(-20))};journal=journal.catch(()=>{}).then(()=>send('/api/workspace/state',{key,patch})).then(()=>{$('#ws-draft-state').textContent='草稿已自动保存（未写入游戏）';}).catch(e=>{$('#ws-draft-state').textContent=`草稿保存失败：${e.message}`;});}
  window.workspaceDraftChanged=()=>{if(W.restoring||!OPR.draft)return;const next=clone(OPR.draft);if(W.draft&&JSON.stringify(next)!==JSON.stringify(W.draft)){W.undo.push(clone(W.draft));W.undo=W.undo.slice(-20);W.redo=[];}W.draft=next;persistDraft();};
  window.workspaceDraftLoad=async()=>{const key=draftKey();W.undo=[];W.redo=[];W.draft=clone(OPR.draft);if(!key)return;try{await journal;const {value}=await send('/api/workspace/state',{key});if(key!==draftKey()||OPR.dirty)return;if(value.draft){OPR.draft=value.draft;W.draft=clone(value.draft);W.undo=value.undo||[];W.redo=value.redo||[];W.restoring=true;opruleSetDirty(JSON.stringify(OPR.draft)!==JSON.stringify(OPR.original));opruleRenderAll();W.restoring=false;$('#ws-draft-state').textContent='已恢复此存档、此表的草稿';}}catch(e){status(`草稿恢复失败：${e.message}`,true);}};
  function undo(redo){const source=redo?W.redo:W.undo,target=redo?W.undo:W.redo;if(!source.length)return;target.push(clone(OPR.draft));OPR.draft=source.pop();W.draft=clone(OPR.draft);W.restoring=true;opruleSetDirty(true);opruleRenderAll();W.restoring=false;persistDraft();}
  $('#ws-undo').onclick=()=>undo(false);$('#ws-redo').onclick=()=>undo(true);
  $('#save-select').addEventListener('change',()=>{invalidate();status('存档已切换，请重新读取线路工作台。');});
  window.restoreWorkspaceSelection=async()=>{try{const {value}=await send('/api/workspace/state',{key:'last-selection'});if(W.selectionTouched)return;for(const [id,key] of [['save-select','save'],['export-select','export']]){const el=document.getElementById(id);if(value[key]&&[...el.options].some(o=>o.value===value[key]))el.value=value[key];}refreshOutputNames();}catch(e){status(`选择状态恢复失败：${e.message}`,true);}};
  ['#save-select','#export-select'].forEach(id=>$(id).addEventListener('change',()=>{W.selectionTouched=true;send('/api/workspace/state',{key:'last-selection',patch:{save:$('#save-select').value,export:$('#export-select').value}}).catch(e=>status(e.message,true));}));
  // Persistent map pins survive random server ports; legacy browser data is imported once.
  const oldLoad=loadJson,oldSave=saveJson;const persisted={};
  loadJson=function(key,fallback){return Object.hasOwn(persisted,key)?persisted[key]:oldLoad(key,fallback);};
  saveJson=function(key,val){persisted[key]=val;oldSave(key,val);send('/api/workspace/state',{key:'map-preferences',patch:{[key]:val}}).catch(e=>toast(`地图规划保存失败：${e.message}`,true));};
  window.workspaceMapReady=send('/api/workspace/state',{key:'map-preferences'}).then(({value})=>{Object.assign(persisted,value);for(const key of ['nimby_realnet_pins','nimby_realnet_view'])if(!(key in persisted)){const prior=oldLoad(key,null);if(prior!=null)saveJson(key,prior);}}).catch(e=>status(e.message,true));
})();
