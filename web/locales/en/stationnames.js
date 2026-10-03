/* Explicit, fingerprinted station-name preview; never auto-writes saves. */
(() => {
  let plan=null;
  const request=()=>({save:$('#save-select').value,export:$('#stationname-export').value,
    pairs:$('#stationname-pairs').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),all:$('#stationname-all').checked});
  function invalidate(){plan=null;$('#stationname-write').disabled=true;}
  ['#save-select','#export-select','#stationname-export','#stationname-all','#stationname-pairs'].forEach(id=>$(id).addEventListener('change',invalidate));
  $('#stationname-pairs').addEventListener('input',invalidate);
  $('#export-select').addEventListener('change',()=>syncStationNameExport(true));
  $('#stationname-preview').onclick=()=>{
    invalidate();const req=request();
    if(!req.save)return toast("Select a save first",true);
    if(!req.export&&!req.pairs.length)return toast("Select a game timetable export, or enter ID=Station name",true);
    startTask('station-name-write',{...req,preview:true,output:outputPath('Names')},{signature:JSON.stringify(req)});
  };
  window.stationNamesResult=result=>{
    const box=$('#stationname-result');box.hidden=false;
    const rows=result.changes||[],missing=result.unresolved||[];
    box.innerHTML=`<strong>${result.preview?"Names available to write":"Written"} ${result.changed_count} stations · Still unnamed ${result.unresolved_count||0} stops</strong>`+
      `<p>Verified ${result.station_count} stations; retained / skipped ${result.skipped_count} stations. Source names are used only after ID and position checks; this does not verify timetable matching.</p>`+
      `<details open><summary>Renamed</summary>${rows.map(r=>`<p><code>${escapeHtml(r.id)}</code> ${escapeHtml(r.old_name)} → <b>${escapeHtml(r.new_name)}</b></p>`).join('')||"<p>No names need writing; no empty copy will be created.</p>"}</details>`+
      (missing.length?`<details open><summary>Unresolved: copy the ID into the manual name field above</summary>${missing.map(r=>`<p><code>${escapeHtml(r.id)}</code> — ${escapeHtml(r.reason)}</p>`).join('')}</details>`:'')+
      (result.output_save?`<p>New copy: <code>${escapeHtml(result.output_save)}</code></p><p><b>Load this copy in game before continuing to save. The toolkit has not changed game memory or the original save.</b></p>`:'');
    if(result.preview&&state.taskContext?.signature===JSON.stringify(request())){
      plan={request:request(),fingerprint:result.fingerprint};$('#stationname-write').disabled=!rows.length;
    }else invalidate();
    $('#stationname-count').textContent=`Still unnamed: ${result.unresolved_count||0}`;
    toast(result.preview?"Station-name preview ready; review before writing":result.output_save?"Save copy with station names created; load it in game":"Name check complete; no copy created");
  };
  window.writeStationNames=()=>{
    if(!plan||JSON.stringify(request())!==JSON.stringify(plan.request)){invalidate();return toast("Files or names changed; check names again",true);}
    startTask('station-name-write',{...plan.request,fingerprint:plan.fingerprint,output:outputPath('Names')});
    $('#stationname-write').disabled=true;
  };
})();
