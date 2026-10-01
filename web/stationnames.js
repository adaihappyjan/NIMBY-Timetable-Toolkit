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
    if(!req.save)return toast('请先选择存档',true);
    if(!req.export&&!req.pairs.length)return toast('请选择游戏时刻表导出，或填写 ID=站名',true);
    startTask('station-name-write',{...req,preview:true,output:outputPath('Names')},{signature:JSON.stringify(req)});
  };
  window.stationNamesResult=result=>{
    const box=$('#stationname-result');box.hidden=false;
    const rows=result.changes||[],missing=result.unresolved||[];
    box.innerHTML=`<strong>${result.preview?'可补写':'已写入'} ${result.changed_count} 站 · 仍缺名称 ${result.unresolved_count||0} 站</strong>`+
      `<p>已核验 ${result.station_count} 个车站；保留 / 跳过 ${result.skipped_count} 站。来源名称只按 ID 和位置使用，不代表时刻表已匹配。</p>`+
      `<details open><summary>名称变更</summary>${rows.map(r=>`<p><code>${escapeHtml(r.id)}</code> ${escapeHtml(r.old_name)} → <b>${escapeHtml(r.new_name)}</b></p>`).join('')||'<p>没有需要写入的站名；不会创建空副本。</p>'}</details>`+
      (missing.length?`<details open><summary>未解决：可复制 ID 到上方手动补名</summary>${missing.map(r=>`<p><code>${escapeHtml(r.id)}</code> — ${escapeHtml(r.reason)}</p>`).join('')}</details>`:'')+
      (result.output_save?`<p>新副本：<code>${escapeHtml(result.output_save)}</code></p><p><b>请在游戏中加载这个副本，再继续保存。工具箱没有改动当前游戏内存或原存档。</b></p>`:'');
    if(result.preview&&state.taskContext?.signature===JSON.stringify(request())){
      plan={request:request(),fingerprint:result.fingerprint};$('#stationname-write').disabled=!rows.length;
    }else invalidate();
    $('#stationname-count').textContent=`仍缺名称：${result.unresolved_count||0}`;
    toast(result.preview?'站名预览完成，请核对后写入':result.output_save?'站名副本已生成，请在游戏中加载':'名称检查完成，没有创建副本');
  };
  window.writeStationNames=()=>{
    if(!plan||JSON.stringify(request())!==JSON.stringify(plan.request)){invalidate();return toast('文件或名称已变化，请重新检查站名',true);}
    startTask('station-name-write',{...plan.request,fingerprint:plan.fingerprint,output:outputPath('Names')});
    $('#stationname-write').disabled=true;
  };
})();
