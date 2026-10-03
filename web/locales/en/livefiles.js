/* Metadata-only polling; tasks/drafts and explicit old-file selections stay pinned. */
const LiveFilePolicy = (() => {
  const signature=f=>f?`${f.path}|${f.size}|${f.modified_ns||f.modified_utc}`:'';
  const project=p=>String(p).split(/[\\/]/).pop().replace(/\.nimbyrails5$/i,'')
    .replace(/_(Toolkit|Extension|Recovery|Repair|Workspace|Autotrack|Names|StopTimes?|GarageJoin|Align)_\d{8}_\d{6}/gi,'')
    .replace(/ Autosave \d+$/i,'').toLowerCase();
  function choose(files,save){
    const key=project(save), top=files.saves.find(f=>!f.tool_generated&&(!key||project(f.path)===key));
    const exp=files.exports.find(f=>project(f.name.split(' Timetable Export')[0])===(key||project(top?.path)));
    return {save:top?.stable?top:null,export:exp?.stable?exp:null};
  }
  return {signature,project,choose};
})();
if(typeof module!=='undefined')module.exports=LiveFilePolicy;
if(typeof window!=='undefined')(() => {
  let started=false,busy=false,timer=null,dirty=false,latest=null,baseline={},generation=0,applying=false;
  const check=$('#follow-latest'), notice=$('#live-files-status'), apply=$('#live-files-apply');
  const select=kind=>$(kind==='save'?'#save-select':'#export-select');
  const locked=()=>state.taskActive||state.cleanupBusy||state.pollBusy||dirty;
  function remember(files){for(const [kind,key] of [['save','saves'],['export','exports']])baseline[kind]=LiveFilePolicy.signature(files[key].find(f=>f.path===select(kind).value));}
  function refreshOptions(files){
    for(const [kind,key] of [['save','saves'],['export','exports']]){
      const el=select(kind),old=el.value;
      setOptions(el,files[key]);
      if(old&&!files[key].some(f=>f.path===old))el.add(new Option(`Current file has moved: ${old.split(/[\\/]/).pop()}`,old));
      if(old)el.value=old;
    }
    syncStationNameExport();
  }
  function changes(){
    if(!latest)return [];
    const chosen=LiveFilePolicy.choose(latest.files,select('save').value);
    return Object.entries(chosen).filter(([kind,f])=>f&&LiveFilePolicy.signature(f)!==baseline[kind]);
  }
  function applyChanges(force=false){
    if(!check.checked||!latest)return;
    const changed=changes();
    if(!changed.length){notice.textContent="Following latest files: checks every 5 seconds and waits for stable writes. Newest does not mean matching.";apply.hidden=true;return;}
    if(locked()&&!force){notice.textContent="New files found; switching is deferred because a task, edit or loaded plan is active. Apply them below when ready; current inputs will not be discarded automatically.";apply.hidden=false;return;}
    if(state.taskActive||state.cleanupBusy||state.pollBusy)return;
    dirty=false;
    applying=true;
    try{for(const [kind,f] of changed){select(kind).value=f.path;baseline[kind]=LiveFilePolicy.signature(f);select(kind).dispatchEvent(new Event('change'));}}
    finally{applying=false;}
    state.analysis=null;state.plan=null;state.gameVersion=null;
    $('#health-summary').textContent="Input files changed. Run the check again; previous results do not describe the current files.";
    refreshOutputNames();apply.hidden=true;
    notice.textContent=`Updated selection: ${changed.map(([,f])=>f.name).join(' / ')}. Reload the tools you need. The save and export have not yet been verified.`;
    toast("Selected newer files. They are not yet verified as a matching pair, and no game export was performed. Reload previous previews.");
    if(document.querySelector('#view-autotrack.active'))$('#at-refresh').click();
    else if(document.querySelector('#view-workspace.active'))$('#ws-load').click();
  }
  async function poll(){
    if(busy)return;
    busy=true;const version=generation;
    try{
      const res=await api('/api/files');
      if(version!==generation)return;
      latest=res;
      if(!state.taskActive&&!state.pollBusy&&!state.cleanupBusy)refreshOptions(res.files);
      if(check.checked)applyChanges();
      else notice.textContent="Follow-latest paused; manual selection retained. The file list still updates automatically.";
    }catch(e){notice.textContent=`Automatic discovery unavailable: ${e.message}. Keep the current selection and retry later.`;}
    finally{busy=false;clearTimeout(timer);timer=setTimeout(poll,5000);}
  }
  async function persist(){try{await api('/api/settings',{method:'POST',body:JSON.stringify({follow_latest:check.checked})});}catch(e){toast(`Follow-latest preference was not saved: ${e.message}`,true);}}
  check.onchange=()=>{generation++;persist();if(check.checked){dirty=false;poll();}else apply.hidden=true;};
  apply.onclick=()=>{
    if(state.taskActive||state.cleanupBusy)return toast("Wait for the current task to finish",true);
    if(confirm("Switching to newer files invalidates existing checks and previews. Reload them before writing. Editing fields does not write to the game automatically. Continue?"))applyChanges(true);
  };
  window.followLatestNow=async()=>{
    check.checked=true;await persist();await poll();
    if(changes().length)apply.onclick();
  };
  ['#save-select','#export-select'].forEach(id=>$(id).addEventListener('change',event=>{
    if(!applying){generation++;check.checked=false;dirty=false;persist();notice.textContent="Manual selection pinned. Re-enable follow-latest to resume automatic selection.";}
    if(latest)remember(latest.files);
  }));
  // Read previews and editor interaction pin inputs until explicit application.
  document.addEventListener('input',e=>{if(e.isTrusted&&e.target.closest('#view-workspace,#view-autotrack,#view-timetable,#stationname-panel'))dirty=true;});
  document.addEventListener('change',e=>{if(e.isTrusted&&e.target.closest('#view-workspace,#view-autotrack,#view-timetable,#stationname-panel'))dirty=true;});
  document.addEventListener('click',e=>{if(e.isTrusted&&e.target.closest('#ws-load,#at-preview,#at-discover,#stationname-preview,#timetable-read,#oprule-read'))dirty=true;});
  window.startLiveFiles=data=>{if(started)return;started=true;check.checked=data.settings.follow_latest!==false;remember(data.files);poll();};
  window.resetLiveFiles=files=>{generation++;latest=null;dirty=false;remember(files);apply.hidden=true;};
  window.holdLiveInputs=()=>{dirty=true;};
  window.checkLiveFiles=poll;
  if(state.bootstrapReady)window.startLiveFiles(state.bootstrap);
  document.addEventListener('visibilitychange',()=>{if(started&&!document.hidden)poll();});
})();
