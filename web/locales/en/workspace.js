/* Line-centric workspace. All heavy work remains in the background process. */
(() => {
  'use strict';
  const esc = escapeHtml;
  const W = {catalog:null, selected:new Set(), preview:null, revision:0, results:{}, draft:null, undo:[], redo:[], restoring:false};
  const send = (path, value) => api(path, {method:'POST', body:JSON.stringify(value)});
  const clone = value => JSON.parse(JSON.stringify(value));
  const clock = value => {
    if(value == null) return "Unknown";
    const n=Math.round(value), day=Math.floor(n/86400), sec=((n%86400)+86400)%86400;
    return `${day?`No. ${day+1} days `:''}${String(Math.floor(sec/3600)).padStart(2,'0')}:${String(Math.floor(sec%3600/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;
  };
  const parseTime = id => {
    const text=$(id).value.trim(); if(!text)return null;
    if(!/^\d{1,2}:\d{2}(:\d{2})?$/.test(text))throw new Error("Enter time as HH:MM or HH:MM:SS");
    const [h,m,s=0]=text.split(':').map(Number); if(h>48||m>59||s>59)throw new Error("Invalid time range"); return h*3600+m*60+s;
  };
  const table = (headers,rows) => `<div class="ws-scroll"><table><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(x=>`<td>${esc(x??"Unknown")}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const section=document.createElement('section'); section.id='view-workspace'; section.className='view';
  section.innerHTML=`
    <div class="ws-intro"><div><h2>Select a line, then address its issues</h2><p>Reads saved files without controlling the game. Never overwrites the original save.</p></div><button class="primary-button" id="ws-load">Read selected save</button></div>
    <p id="ws-source">Select a save in Overview & health, then Read selected save. No game timetable export is needed for this step.</p>
    <div id="ws-status" class="ws-notice" role="status" aria-live="polite">Waiting to load</div>
    <div class="ws-tools"><input id="ws-search" type="search" placeholder="Search line, timetable or train names, or ID…" aria-label="Search operating objects"><label><input type="checkbox" id="ws-templates">Show line templates</label><button id="ws-select-visible">Select filtered results</button><button id="ws-select-none">Deselect all</button><span id="ws-count">0 timetables selected</span></div>
    <div id="ws-catalog" class="ws-catalog"><p>Not read yet.</p></div>
    <div class="ws-tabs" role="tablist">${[['batch',"Batch configuration"],['audit',"Connections & depots"],['corridor',"Shared-track coordination"],['accounting',"Operating rankings"],['diagnostic',"Diagnostic assistant"],['tasks',"Tasks and verification"]].map(([id,name],i)=>`<button role="tab" aria-selected="${i===0}" data-ws-tab="${id}">${name}</button>`).join('')}</div>
    <article class="ws-panel" data-ws-panel="batch">
      <h3>Batch presets · Preview before writing</h3><p>Change only specified fields in selected timetables. Blank fields retain their values; depot loops can be limited to one run.</p>
      <div class="ws-fields"><label>Operating days<select id="ws-days"><option value="">Leave unchanged</option><option value="127">Every day</option><option value="31">Monday–Friday</option><option value="15">Monday–Thursday</option><option value="96">Saturday and Sunday</option><option value="custom">Enable manually</option></select></label>
      <label>First passenger-service order time<input id="ws-start" placeholder="05:30"></label><label>Depot-return order time<input id="ws-depot-time" placeholder="00:30"></label><label>Passenger-service offsets per train (s)<input id="ws-interval" type="number" min="0.5" step="0.5" placeholder="Keep original value"></label></div>
      <div id="ws-weekdays" hidden>${["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map((d,i)=>`<label><input type="checkbox" data-ws-day="${1<<i}">week ${d}</label>`).join('')}</div>
      <p class="ws-notice">Operating days determine when an order starts, not when an existing infinite loop ends. To stop on weekends, arrange depot return or an ending connection after the final operating day and check the game's weekly graph.</p>
      <p>Select a line you have confirmed is a depot; its order will be changed to x1): </p><div id="ws-depots" class="ws-depots"></div>
      <p class="ws-muted">Per-train offsets are not the final headways along the whole line. Ambiguous edits are blocked when multiple passenger orders, stacking or depots share offset groups.</p>
      <details><summary>Peak / off-peak presets (optional)</summary><p>Create one Max passenger order at each boundary, with its own offset group, retaining existing depot-return orders. Supports only timetables with exactly one passenger order. Does not verify that trains can sustain the target headway.</p><label><input id="ws-periods-enabled" type="checkbox">Use time windows instead of the first-departure and per-train offset inputs above</label><div class="ws-fields">${[['05:30','900'],['07:00','420'],['09:30','900'],['15:30','420'],['18:00','900']].map(([t,n],i)=>`<label>No. ${i+1} section starts<input id="ws-period-time-${i}" value="${t}" aria-label="No. ${i+1} section starts"><input id="ws-period-offset-${i}" type="number" min="0.5" step="0.5" value="${n}" aria-label="No. ${i+1} section offsets per train (s)"><small>The second field is the per-train offset in seconds. Leave the start time blank to skip</small></label>`).join('')}</div></details>
      <div class="ws-tools"><button id="ws-preview" class="primary-button">Preview selected changes</button><button id="ws-apply" disabled>Write a new save</button><button id="ws-open-editor">Open selected timetable in full editor</button></div><div id="ws-batch-result"></div>
    </article>
    <article class="ws-panel" data-ws-panel="audit" hidden><h3>Weekly connections and depot plan</h3><p>After verifying the selected export, inspect the full week, including Sunday–Monday. You must confirm depot capacity; it is not guessed from track counts.</p>
      <div id="ws-capacities" class="ws-fields"></div><div class="ws-tools"><button id="ws-pair">Find compatible exports</button><button id="ws-audit" class="primary-button">Check the full fleet's weekly plan</button></div><div id="ws-pairs"></div><div id="ws-audit-result"></div></article>
    <article class="ws-panel" data-ws-panel="corridor" hidden><h3>Shared-track entry coordination</h3><p>Choose two lines and confirm adjacent stops in the same direction. Phase is measured at the shared-track entry. Enter branch running times in seconds.</p>
      <div class="ws-fields"><label>Branch A<select id="ws-line-a"></select></label><label>Branch B<select id="ws-line-b"></select></label><label>Shared entry section<select id="ws-segment"></select></label><label>A Time from origin to entry (s)<input id="ws-travel-a" type="number" value="0" min="0"></label><label>B Time from origin to entry (s)<input id="ws-travel-b" type="number" value="0" min="0"></label></div>
      <div class="ws-fields"><label>Window start<input id="ws-window-start" value="07:00"></label><label>Window end<input id="ws-window-end" value="09:30"></label><label>A Headway (s)<input id="ws-headway-a" type="number" value="420" min="10"></label><label>B Headway (s)<input id="ws-headway-b" type="number" value="840" min="10"></label><label>B Offset (s)<input id="ws-phase-b" type="number" value="210" min="0"></label></div>
      <div class="ws-tools"><button id="ws-add-window">Add time window</button><button id="ws-clear-windows">Clear time windows</button><button id="ws-corridor" class="primary-button">Calculate merged departures</button><button id="ws-download-corridor" disabled>Export sequence CSV</button></div><div id="ws-windows"></div><div id="ws-corridor-result"></div></article>
    <article class="ws-panel" data-ws-panel="accounting" hidden><h3>Operating issues ranked</h3><p>Uses the game's Accounting TSV export, not timetable JSON. Export statistics from the game's accounting/statistics interface, place the TSV in the save directory and refresh. If unavailable, skip this without affecting other tools. These are historical statistics, not live monitoring.</p>
      <div class="ws-fields"><label>Accounting export<select id="ws-account-file"></select></label><label>Objects<select id="ws-kind"><option value="line">Lines</option><option value="station">Stations</option><option value="train">Trains</option></select></label><label>Cycle<select id="ws-period"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></label><label>Date / timestamp<select id="ws-account-stamp"><option value="">Latest cycle</option></select></label><label>Metrics<select id="ws-metric"><option value="trains_signal_stop_time">Total signal waiting time</option><option value="trains_late_arrival_time">Total arrival delay</option><option value="pax_waited_too_long">Passengers exceeding wait limit</option><option value="pax_lost">Lost passengers</option><option value="train_departed_full">Full-capacity departures</option><option value="full_departure_ratio">Share of full-capacity departures</option></select></label></div>
      <button id="ws-account-refresh">Refresh statistics files</button><button id="ws-accounting" class="primary-button">Load and rank</button><div id="ws-accounting-result"></div></article>
    <article class="ws-panel" data-ws-panel="diagnostic" hidden><h3>Read-only diagnostic mod · Preview</h3><p>Does not change dispatching, occupancy checks or train positions. Only trains with the extension enabled in game are sampled: at most once per 60 simulated seconds, or every 5 minutes when stable. Compilation and some runtime states were checked on 1.19.10; verify your own network separately.</p>
      <ol><li>Install places the mod in the current save directory's mods subfolder.</li><li>Enable the private mod in game, then enable the extension on the trains to inspect Toolkit read-only diagnostic.</li><li>Enable script logging manually for this session. Run briefly, disable logging, then paste the text below.</li></ol>
      <div class="ws-tools"><button id="ws-diag-status">Check installed files</button><button id="ws-diag-install">Install read-only diagnostic mod</button></div><p id="ws-diag-state">Installation status not checked. File presence alone cannot determine whether the mod is enabled in game.</p>
      <details><summary>Install generated rule / vehicle packages</summary><p>Generate a package in Script rules or Vehicle workshop, then refresh. Only unmodified packages with toolkit creation records can be installed. Existing mods with the same name are not overwritten.</p><select id="ws-mod-package" aria-label="Generated mod packages"></select><button id="ws-mod-refresh">Refresh generated packages</button><button id="ws-mod-install">Install selected package</button></details>
      <label>Log contents<textarea id="ws-log" rows="6" placeholder="Paste data containing NIMBY_DIAG| log; maximum 500 KB"></textarea></label><button id="ws-log-parse">Analyze log</button><div id="ws-log-result"></div></article>
    <article class="ws-panel" data-ws-panel="tasks" hidden><h3>Task center and verification checklist</h3><p>Save writes are serialized for safety. Compatible-export checks use at most two workers, with lower concurrency for large saves. A write cannot be forcibly cancelled.</p><button id="ws-tasks-refresh">Refresh task history</button><div id="ws-tasks"></div><div id="ws-acceptance"></div></article>`;
  $('main').append(section);
  const status = (message,error=false) => {$('#ws-status').textContent=message; $('#ws-status').classList.toggle('error',error);};
  function run(operation,payload={}) {
    if(state.taskActive) {toast("A task is running; wait for it to finish.",true);return;}
    status("Processing in background; you can continue browsing…");
    const save = $('#save-select').value;
    return startTask('workspace',{operation,save,...payload},{revision:W.revision,save,payload:clone(payload)});
  }
  function requireCatalog(){if(!W.catalog||W.catalog.save!==$('#save-select').value)throw new Error("The save changed or has not been loaded. Read the selected save first.");}
  const guard = fn => async () => {try{await fn();}catch(e){status(e.message,true);toast(e.message,true);}};
  function filtered(){const term=$('#ws-search').value.trim().toLowerCase();return (W.catalog?.groups||[]).filter(g=>($('#ws-templates').checked||g.kind==='timetable')&&JSON.stringify([g.schedule_name,g.schedule_id,g.entries.map(e=>e.line_name),g.trains]).toLowerCase().includes(term));}
  function renderCatalog(){
    $('#ws-count').textContent=`Selected ${W.selected.size} timetables`;
    $('#ws-catalog').innerHTML=filtered().map(g=>`<label class="ws-card"><input type="checkbox" data-ws-group="${esc(g.schedule_id)}" ${W.selected.has(g.schedule_id)?'checked':''} ${g.kind==='template'?'disabled':''}><div><strong>${esc(g.schedule_name)}</strong><small>${g.kind==='template'?"Line templates":"Independent operating timetable"} · ${g.trains.length} Trains · ${g.entries.length} orders</small><span>${esc(g.entries.map(e=>`${clock(e.time_seconds)} ${e.line_name||e.line_id}`).join(' → '))}</span><details><summary>Trains & objects ID</summary>${esc(g.schedule_id)}<p>${esc(g.trains.map(t=>t.name).join('、')||"No trains assigned")}</p></details></div></label>`).join('')||"<p>No matches. Try part of a line name or enable line templates.</p>";
  }
  let projectTimer;
  function saveProject(){clearTimeout(projectTimer); const key=W.catalog?.save;if(!key)return;projectTimer=setTimeout(()=>{
    const fields={};$$('#view-workspace input[id],#view-workspace select[id]').forEach(e=>{fields[e.id]=e.type==='checkbox'?e.checked:e.value;});
    send('/api/workspace/state',{key:`workspace:${key}`,patch:{fields,selected:[...W.selected],windows:W.windows||[],depots:depotValues(),weekdays:$$('[data-ws-day]:checked').map(e=>e.dataset.wsDay)}}).catch(e=>status(`Could not save draft: ${e.message}`,true));
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
  $('#ws-preview').onclick=guard(()=>{if(state.taskActive){toast("A task is running; wait for it to finish.",true);return;}const payload=batchRequest();invalidate();run('batch',payload);});
  $('#ws-apply').onclick=guard(()=>{if(!W.preview||!previewIsCurrent(W.previewContext)||JSON.stringify(batchRequest())!==JSON.stringify(W.batchPayload)){invalidate();throw new Error("Parameters or save changed; preview again.");}if(confirm(`Will modify ${W.preview.changes.length} operating timetables and create a new save. Continue?`))run('batch',{...W.batchPayload,apply:true,preview_hash:W.preview.preview_hash,output:outputPath('Workspace')});});
  $('#ws-open-editor').onclick=guard(()=>{requireCatalog();if(W.selected.size!==1)throw new Error("Select exactly one timetable to open the editor.");renderOperatingRules({save:W.catalog.save,groups:W.catalog.groups,lines:W.catalog.lines,fingerprint:W.catalog.fingerprint});const id=[...W.selected][0];$('#oprule-schedule').value=id;opruleLoadGroup(W.catalog.groups.find(g=>g.schedule_id===id));switchView('timetable');$('#oprule-editor').scrollIntoView({behavior:'smooth'});});
  $('#ws-pair').onclick=()=>run('pair');
  $('#ws-audit').onclick=guard(()=>{requireCatalog();run('audit',{export:$('#export-select').value,depots:depotValues()});});
  function updateSegments(){
    const a=W.catalog?.lines.find(l=>l.id===$('#ws-line-a').value),b=W.catalog?.lines.find(l=>l.id===$('#ws-line-b').value);const saved=$('#ws-segment').value;
    const edges=l=>(l?.selectors||[]).filter(s=>s.station_id).sort((a,b)=>a.route_index-b.route_index).flatMap((s,i,arr)=>i<arr.length-1?[{ids:[s.station_id,arr[i+1].station_id],name:`${s.station_name} → ${arr[i+1].station_name}`}]:[]);
    const ae=edges(a),be=edges(b),unique=(list,key)=>list.filter(e=>e.ids.join('|')===key).length===1;
    const bs=new Set(be.map(e=>e.ids.join('|')));const options=ae.filter(e=>bs.has(e.ids.join('|'))&&unique(ae,e.ids.join('|'))&&unique(be,e.ids.join('|')));
    $('#ws-segment').innerHTML=options.map(e=>`<option value="${esc(e.ids.join('|'))}">${esc(e.name)}</option>`).join('')||"<option value=\"\">No same-direction shared section found</option>";
    if(options.some(e=>e.ids.join('|')===saved))$('#ws-segment').value=saved;
  }
  ['#ws-line-a','#ws-line-b'].forEach(id=>$(id).onchange=()=>{W.windows=[];updateSegments();renderWindows();});
  function newWindow(){const a=$('#ws-line-a').value,b=$('#ws-line-b').value;if(a===b)throw new Error("Select two different lines.");return {start:parseTime('#ws-window-start'),end:parseTime('#ws-window-end'),intervals:{[a]:+$('#ws-headway-a').value,[b]:+$('#ws-headway-b').value},phases:{[a]:0,[b]:+$('#ws-phase-b').value}};}
  function renderWindows(){$('#ws-windows').innerHTML=table(["Time window added","Headways for both lines / s"],(W.windows||[]).map(w=>[`${clock(w.start)} – ${clock(w.end)}`,Object.values(w.intervals).join(' / ')]));}
  $('#ws-add-window').onclick=guard(()=>{(W.windows ||= []).push(newWindow());renderWindows();saveProject();});
  $('#ws-clear-windows').onclick=()=>{W.windows=[];renderWindows();saveProject();};
  $('#ws-corridor').onclick=guard(()=>{requireCatalog();const stations=$('#ws-segment').value.split('|');if(stations.length!==2)throw new Error("Select a same-direction shared entry section.");run('corridor',{branches:[{id:$('#ws-line-a').value,stations,entry_travel:+$('#ws-travel-a').value},{id:$('#ws-line-b').value,stations,entry_travel:+$('#ws-travel-b').value}],windows:W.windows?.length?W.windows:[newWindow()]});});
  function download(name,text,type='text/plain'){const url=URL.createObjectURL(new Blob(['\ufeff',text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  $('#ws-download-corridor').onclick=()=>download("Shared-track departure sequence.csv","Lines ID,Shared-track entry time (s),Departure time (s),Gap from previous departure (s)\r\n"+(W.results.corridor?.events||[]).map(e=>[e.line,e.entry_time,e.origin_departure,e.gap].join(',')).join('\r\n'),'text/csv');
  $('#ws-accounting').onclick=()=>run('accounting',{accounting:$('#ws-account-file').value,kind:$('#ws-kind').value,period:$('#ws-period').value,metric:$('#ws-metric').value,timestamp:$('#ws-account-stamp').value||null});
  ['#ws-account-file','#ws-kind','#ws-period'].forEach(id=>$(id).onchange=()=>$('#ws-account-stamp').innerHTML="<option value=\"\">Latest cycle</option>");
  async function files(){try{const res=await api('/api/workspace/files');const v=$('#ws-account-file').value;setOptions($('#ws-account-file'),res.accounting);if(res.accounting.some(f=>f.path===v))$('#ws-account-file').value=v;
    $('#ws-mod-package').innerHTML=(res.mod_packages||[]).map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('')||"<option value=\"\">No generated packages yet; generate one first</option>";
    $('#ws-tasks').innerHTML=table(["Start time","Tasks","Results","New save / error"],res.history.slice().reverse().map(t=>[new Date(t.started*1000).toLocaleString(),t.operation||t.action,t.ok?"Completed":"Incomplete",t.output||t.error||"Read-only tasks"]));
  }catch(e){status(e.message,true);}}
  $('#ws-tasks-refresh').onclick=files;
  $('#ws-mod-refresh').onclick=files;
  $('#ws-account-refresh').onclick=files;
  $('#ws-mod-install').onclick=guard(async()=>{const packageName=$('#ws-mod-package').value;if(!packageName)throw new Error("Generate and select a mod package first");if(!confirm(`Install ${packageName} to the game's private mods? This will not enable it automatically.`))return;const r=await send('/api/workspace/install-mod',{package:packageName});$('#ws-diag-state').textContent=`${r.path} · ${r.note}`;});
  async function diag(install){const r=await send('/api/workspace/diagnostic',{install});$('#ws-diag-state').textContent=`${r.path||''} ${r.installed||r.path?"Mod files installed":"Not installed"}; In-game activation status is unknown. Follow the steps above.`;}
  $('#ws-diag-status').onclick=guard(()=>diag(false));$('#ws-diag-install').onclick=guard(()=>{if(confirm("Install the read-only diagnostic preview mod? It will not be enabled automatically or overwrite different existing files."))return diag(true);});
  $('#ws-log-parse').onclick=guard(async()=>{if($('#ws-log').value.length>500000)throw new Error("Log too long; paste the most recent 500 KB or less.");const r=await send('/api/workspace/log',{text:$('#ws-log').value});const labels={UNASSIGNED:"Unassigned shifts",ASSIGNED:"Assigned shifts",TIMED_STOP:"Timing stops",SIGNAL_WAIT:"Waiting at signals"};$('#ws-log-result').innerHTML=`<p>${esc(r.scope)} Total ${r.total} items.</p>`+table(["Status","Trains / signals"],r.records.map(e=>[labels[e.event]||e.event,e.detail]));});
  window.workspaceFailure=message=>status(message,true);
  window.workspaceResult=async (r,context)=>{
    W.results[r.operation]=r;status("Completed."+(r.scope||''));
    if(r.operation==='catalog'){
      W.catalog=r;invalidate();const c=r.counts;$('#ws-source').textContent=`${r.save} · ${r.game_version?.save_release||"Unknown version"} · ${c.timetables} independent operating timetables / ${c.templates} line templates / ${c.trains} trains (internal objects ${c.objects}）`;
      const depots=r.lines.filter(l=>l.stop_count===1);$('#ws-depots').innerHTML=depots.map(l=>`<label><input type="checkbox" data-ws-depot="${esc(l.id)}">${esc(l.name)} <small>Single-stop candidate; please confirm</small></label>`).join('')||"No single-stop depot candidates.";
      $('#ws-capacities').innerHTML=depots.map(l=>`<label>${esc(l.name)} Capacity<input type="number" min="1" max="10000" data-ws-capacity="${esc(l.id)}" placeholder="Enter a value and select this depot on the batch page"></label>`).join('');
      const opts=r.lines.filter(l=>l.stop_count>1).map(l=>`<option value="${esc(l.id)}">${esc(l.name)}</option>`).join('');$('#ws-line-a').innerHTML=opts;$('#ws-line-b').innerHTML=opts;$('#ws-line-b').selectedIndex=Math.min(1,$('#ws-line-b').options.length-1);await restoreProject();await files();
    }else if(r.operation==='pair'){
      $('#ws-pairs').innerHTML=`<p>${esc(r.note)} · ${r.workers_used} worker processes</p>`+r.pairs.map((p,i)=>`<div class="ws-notice">${esc(p.path.split(/[\\/]/).pop())} · ${p.matched?"Structure compatibility":esc(p.reason)} ${p.matched?`<button data-ws-use-export="${i}">Use</button>`:''}</div>`).join('');
      $$('[data-ws-use-export]').forEach(b=>b.onclick=()=>{const p=r.pairs[+b.dataset.wsUseExport].path;const el=$('#export-select');if(![...el.options].some(o=>o.value===p))el.add(new Option(p.split(/[\\/]/).pop(),p));el.value=p;status("Compatible export selected; it will be verified again before writing.");});
    }else if(r.operation==='batch'){
      if(r.preview&&!previewIsCurrent(context)){
        invalidate();status("Parameters or the save changed during preview. Previous results are invalid; preview again.",true);
        $('#ws-batch-result').textContent="Previous preview invalidated; no save written.";return;
      }
      W.previewContext=context;W.batchPayload=r.preview?context.payload:null;
      W.preview=r.preview?r:null;$('#ws-apply').disabled=!r.preview;
      $('#ws-batch-result').innerHTML=`<h4>${r.preview?"Change preview · Not written yet":"New save written and readback verified"}</h4>${r.output_save?`<p>${esc(r.output_save)}</p>`:''}`+r.changes.map(c=>`<details open><summary>${esc(c.name)}</summary>${table(["Orders","Original time / day","New time / day","New repetition"],c.after.entries.map(e=>{const old=c.before.entries.find(o=>o.order_id===e.order_id);return [e.line_name,old?`${clock(old.time_seconds)} / ${opruleDayText(old.days_mask)}`:"Added",`${clock(e.time_seconds)} / ${opruleDayText(e.days_mask)}`,e.repeat_is_max?'Max':`x${e.repeat_count}`];}))}${table(["Offset groups","Original mode / seconds","New mode / seconds"],c.after.offset_distributions.flatMap((g,i)=>JSON.stringify(g)!==JSON.stringify(c.before.offset_distributions[i])?[[i+1,`${c.before.offset_distributions[i].mode} / ${c.before.offset_distributions[i].fixed_interval_seconds}`,`${g.mode} / ${g.fixed_interval_seconds}`]]:[]))}</details>`).join('');
      if(!r.preview){acceptance(r);await send('/api/workspace/state',{key:`workspace:${r.input_save}`,patch:{last_output:{output_save:r.output_save,output_file_sha256:r.output_file_sha256}}});await refreshFileLists();await files();}
    }else if(r.operation==='audit'){
      $('#ws-audit-result').innerHTML=`<p>${esc(r.scope)}</p><h4>${r.coverage.length} Trains · ${r.issues.filter(i=>i.status==='error').length} timing errors · ${r.issues.filter(i=>i.status==='unknown').length} items to confirm</h4><p>No readable plan: ${r.without_plan?.length||0} trains; selected depot not visited: ${r.without_depot?.length||0} trains (other depots may still exist).</p>`+table(["Trains","Issues","Time","Time difference (s)"],r.issues.slice(0,500).map(i=>[i.train,i.problem,clock(i.time),i.seconds]))+`<p>Showing up to 500 issues.</p><details><summary>Coverage by day</summary>${table(["Trains","Days included in the plan","Planned segments"],r.coverage.map(c=>[c.train,c.days.map(d=>["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d]).join('、'),c.runs]))}</details>`+r.depots.map(d=>`<h4>${esc(W.catalog?.lines.find(l=>l.id===d.line)?.name||d.line)} · Planned peak ${d.planned_peak??"Unknown"} / Capacity ${d.capacity} · ${d.over_capacity==null?"Missing depot records":d.over_capacity?"Over capacity":"No planned capacity overruns found"}</h4><p>Weekly occupancy (Monday → Sunday; first 60 intervals): </p><div class="ws-occupancy">${d.intervals.slice(0,60).map(([s,e,tid])=>`<div><small>${esc(tid)}</small><span><i style="left:${s/6048}%;width:${Math.max(.1,(e-s)/6048)}%" title="${esc(clock(s)+' → '+clock(e))}"></i></span></div>`).join('')}</div>${table(["Time","Planned occupancy"],d.timeline.slice(0,200).map(t=>[clock(t.time),t.occupied]))}`).join('');
    }else if(r.operation==='corridor'){
      $('#ws-corridor-result').innerHTML=`<p>${esc(r.scope)} Total ${r.events.length} departures; first 300 shown below.</p>`+table(["Lines","Entry time","Departure time","Previous departure gap / s"],r.events.slice(0,300).map(e=>[W.catalog?.lines.find(l=>l.id===e.line)?.name||e.line,clock(e.entry_time),clock(e.origin_departure),e.gap]));$('#ws-download-corridor').disabled=false;
    }else if(r.operation==='accounting'){
      $('#ws-account-stamp').innerHTML="<option value=\"\">Latest cycle</option>"+r.timestamps.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');$('#ws-account-stamp').value=r.timestamp;
      $('#ws-accounting-result').innerHTML=`<p>${esc(r.scope)} Statistics date: ${esc(r.timestamp)}; Total ${r.rankings.length} items.</p>`+table(["Rank","Objects","Value"],r.rankings.map((x,i)=>[i+1,x.name,x.value==null?"Unknown":r.metric==='full_departure_ratio'?`${(x.value*100).toFixed(2)}%`:Number(x.value.toFixed(2))]));
    }
  };
  async function acceptance(r){
    const key=`acceptance:${r.output_file_sha256}`,saved=(await send('/api/workspace/state',{key})).value;
    $('#ws-acceptance').innerHTML=`<h4>Verify current output</h4><p>${esc(r.output_save)}</p><p>✓ Compression round-trip verified · Original save retained</p><label><input id="ws-accept-load" type="checkbox" ${saved.loaded?'checked':''}>I loaded this output save in the game</label><label><input id="ws-accept-run" type="checkbox" ${saved.running?'checked':''}>I checked depot departures, headways and returns</label><p>These are your confirmations, not automatic verification.</p><button id="ws-accept-export">Use this output and verify a fresh export</button>`;
    ['#ws-accept-load','#ws-accept-run'].forEach(id=>$(id).onchange=()=>send('/api/workspace/state',{key,patch:{loaded:$('#ws-accept-load').checked,running:$('#ws-accept-run').checked}}).catch(e=>status(e.message,true)));
    $('#ws-accept-export').onclick=()=>{const s=$('#save-select');if(![...s.options].some(o=>o.value===r.output_save))s.add(new Option(r.output_save,r.output_save));s.value=r.output_save;run('pair');};
  }
  // Draft journal is independent from browser origin; reloads on the same save fingerprint only.
  const draftBar=document.createElement('div');draftBar.className='ws-tools';draftBar.innerHTML="<button id=\"ws-undo\">Undo</button><button id=\"ws-redo\">Redo</button><span id=\"ws-draft-state\">Drafts stay on this computer; no save writes</span>";$('#oprule-editor')?.prepend(draftBar);
  let journal=Promise.resolve();
  function draftKey(){return OPR.fingerprint&&OPR.selected?`draft:${OPR.fingerprint}:${OPR.selected}`:null;}
  function persistDraft(){const key=draftKey();if(!key)return;const patch={draft:clone(OPR.draft),undo:clone(W.undo.slice(-20)),redo:clone(W.redo.slice(-20))};journal=journal.catch(()=>{}).then(()=>send('/api/workspace/state',{key,patch})).then(()=>{$('#ws-draft-state').textContent="Draft saved locally (not written to the game)";}).catch(e=>{$('#ws-draft-state').textContent=`Could not save draft: ${e.message}`;});}
  window.workspaceDraftChanged=()=>{if(W.restoring||!OPR.draft)return;const next=clone(OPR.draft);if(W.draft&&JSON.stringify(next)!==JSON.stringify(W.draft)){W.undo.push(clone(W.draft));W.undo=W.undo.slice(-20);W.redo=[];}W.draft=next;persistDraft();};
  window.workspaceDraftLoad=async()=>{const key=draftKey();W.undo=[];W.redo=[];W.draft=clone(OPR.draft);if(!key)return;try{await journal;const {value}=await send('/api/workspace/state',{key});if(key!==draftKey()||OPR.dirty)return;if(value.draft){OPR.draft=value.draft;W.draft=clone(value.draft);W.undo=value.undo||[];W.redo=value.redo||[];W.restoring=true;opruleSetDirty(JSON.stringify(OPR.draft)!==JSON.stringify(OPR.original));opruleRenderAll();W.restoring=false;$('#ws-draft-state').textContent="Draft restored for this save and timetable";}}catch(e){status(`Could not restore draft: ${e.message}`,true);}};
  function undo(redo){const source=redo?W.redo:W.undo,target=redo?W.undo:W.redo;if(!source.length)return;target.push(clone(OPR.draft));OPR.draft=source.pop();W.draft=clone(OPR.draft);W.restoring=true;opruleSetDirty(true);opruleRenderAll();W.restoring=false;persistDraft();}
  $('#ws-undo').onclick=()=>undo(false);$('#ws-redo').onclick=()=>undo(true);
  $('#save-select').addEventListener('change',()=>{invalidate();status("Save changed; reload the line workspace.");});
  window.restoreWorkspaceSelection=async()=>{try{const {value}=await send('/api/workspace/state',{key:'last-selection'});if(W.selectionTouched)return;for(const [id,key] of [['save-select','save'],['export-select','export']]){const el=document.getElementById(id);if(value[key]&&[...el.options].some(o=>o.value===value[key]))el.value=value[key];}refreshOutputNames();}catch(e){status(`Could not restore selection: ${e.message}`,true);}};
  ['#save-select','#export-select'].forEach(id=>$(id).addEventListener('change',()=>{W.selectionTouched=true;send('/api/workspace/state',{key:'last-selection',patch:{save:$('#save-select').value,export:$('#export-select').value}}).catch(e=>status(e.message,true));}));
  // Persistent map pins survive random server ports; legacy browser data is imported once.
  const oldLoad=loadJson,oldSave=saveJson;const persisted={};
  loadJson=function(key,fallback){return Object.hasOwn(persisted,key)?persisted[key]:oldLoad(key,fallback);};
  saveJson=function(key,val){persisted[key]=val;oldSave(key,val);send('/api/workspace/state',{key:'map-preferences',patch:{[key]:val}}).catch(e=>toast(`Could not save map planning data: ${e.message}`,true));};
  window.workspaceMapReady=send('/api/workspace/state',{key:'map-preferences'}).then(({value})=>{Object.assign(persisted,value);for(const key of ['nimby_realnet_pins','nimby_realnet_view'])if(!(key in persisted)){const prior=oldLoad(key,null);if(prior!=null)saveJson(key,prior);}}).catch(e=>status(e.message,true));
})();
