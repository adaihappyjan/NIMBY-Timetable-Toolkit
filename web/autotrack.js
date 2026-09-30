/* Experimental blueprint UI; computation/writing uses the existing hidden worker. */
(() => {
  'use strict';
  viewMeta.autotrack = ['TRACK BLUEPRINT LAB', '自动铺轨 · 实验'];
  let imported = null, preview = null, revision = 0, catalog = null;
  const tutorialKey='nimby.autotrack.tutorial.v2';
  let tutorialSeen=false,tutorialTouched=false;
  const tutorialReady=api('/api/workspace/state',{method:'POST',body:JSON.stringify({key:tutorialKey})}).then(r=>{if(!tutorialTouched)tutorialSeen=r.value?.seen===true;}).catch(()=>{});
  const lessons=[
    ['先选存档，再自动读取','在总览选择刚保存的文件。打开本页会自动读取站名、Steam 底图和本地路线。自动寻路需要 Node.js 22+；缺少时会提示，不会静默安装。'],
    ['选择两站与现实线路类型','输入站名，选择含 ID 的完整结果；同名站不会混淆。地图上尚未建设的站点可输入 经度,纬度。选择铁路、地铁或电车等底图类型，无连通路径就停止，不画直线顶替。'],
    ['地面、桥梁、隧道分别设置','自动模式默认中速地面，并保留底图桥隧标记。三种结构可分别选中速、高速、电车；也可强制全程地面、高架或隧道。速度是类型上限，桥隧层级不是地形高程。'],
    ['预览后，只生成新副本','检查线形、桥隧、吸附距离和警告。两端留接轨空隙，中部冲突会拒绝。生成后在游戏里暂停检查并小范围试建，手动完成站台接轨与信号；不要覆盖正式档。']
  ];
  let lesson=0;
  function showLesson(){
    $('#at-tutorial').hidden=false;$('#at-tutorial-title').textContent=`${lesson+1} / ${lessons.length} · ${lessons[lesson][0]}`;
    $('#at-tutorial-text').textContent=lessons[lesson][1];$('#at-tutorial-back').disabled=lesson===0;
    $('#at-tutorial-next').textContent=lesson===lessons.length-1?'明白了，开始使用':'下一步';
  }
  function closeLesson(){
    $('#at-tutorial').hidden=true;tutorialSeen=true;tutorialTouched=true;
    api('/api/workspace/state',{method:'POST',body:JSON.stringify({key:tutorialKey,patch:{seen:true}})}).catch(()=>toast('教学已关闭，但未能保存已读状态。',true));
  }
  $('#at-help').addEventListener('click',()=>{lesson=0;showLesson();});
  $('#at-tutorial-back').addEventListener('click',()=>{lesson=Math.max(0,lesson-1);showLesson();});
  $('#at-tutorial-next').addEventListener('click',()=>{if(lesson===lessons.length-1)closeLesson();else{lesson++;showLesson();}});
  $('#at-tutorial-close').addEventListener('click',closeLesson);
  function option(label,value){const element=document.createElement('option');element.textContent=label;element.value=value;return element;}
  function stationLabel(s){return `${s.name} — ${s.id}`;}
  function endpoint(value,key){
    const station=catalog?.stations.find(s=>stationLabel(s)===value);
    if(station)return {[`${key}_station`]:station.id};
    const match=value.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)$/);
    if(match)return {[`${key}_coord`]:[Number(match[1]),Number(match[2])]};
    throw new Error('请从建议列表选择完整站名，或输入 经度,纬度');
  }
  async function readCatalog(){
    const save=$('#save-select').value;if(!save)return;
    if(state.taskActive){toast('请等待当前后台任务完成，再重新自动读取。',true);return;}
    invalidate();catalog=null;$('#at-catalog-state').textContent='正在后台读取站点、游戏底图与本地路线…';
    await startTask('autotrack',{save,operation:'catalog'},{catalogSave:save});
  }
  function updateMode(){
    const mode=$('#at-preset').value;
    ['#at-from','#at-to','#at-map-path','#at-rail-type'].forEach(id=>{$(id).disabled=mode!=='auto';});
    $('#at-route-path').disabled=mode!=='file';$('#at-file').disabled=mode!=='custom';
    ['#at-from','#at-to','#at-map-path','#at-rail-type','#at-route-path','#at-file'].forEach(id=>{const label=$(id).closest?.('label');if(label)label.hidden=$(id).disabled;});
  }
  function invalidate() {
    revision++; preview = null;
    $('#at-apply').disabled = $('#at-download').disabled = true;
    $('#at-accept').checked = false;
    $('#at-state').textContent = '参数已变化，请重新预览';
    $('#at-save-name').textContent = $('#save-select').value.split(/[\\/]/).pop() || '尚未选择';
    $('#at-map').replaceChildren(); $('#at-summary').textContent = '等待当前存档与参数的预览';
    $('#at-warnings').replaceChildren(); $('#at-output').textContent = '';
  }
  function request() {
    const save = $('#save-select').value;
    if (!save) throw new Error('请先在总览选择存档');
    const preset = $('#at-preset').value;
    if (preset === 'custom' && !imported) throw new Error('请先导入 GeoJSON 路线文件');
    let extra={};
    if(preset==='auto'){
      if(!catalog||catalog.save!==save)throw new Error('请先完成当前存档的自动读取');
      if(!catalog.node_ready)throw new Error('未找到 Node.js；请安装 Node.js 22+ 后重开工具箱，或选择本地 GeoJSON');
      extra={...endpoint($('#at-from').value,'from'),...endpoint($('#at-to').value,'to'),map_path:$('#at-map-path').value,rail_type:$('#at-rail-type').value};
    }
    if(preset==='file')extra.route_path=$('#at-route-path').value;
    return {save, preset, ...extra, geojson:preset === 'custom' ? imported : null,
      bridge_variant:Number($('#at-bridge-variant').value||6),tunnel_variant:Number($('#at-tunnel-variant').value||6),structure_mode:$('#at-structure').value||'auto',
      variant:Number($('#at-variant').value), start_m:Number($('#at-start').value),
      end_m:$('#at-end').value === '' ? null : Number($('#at-end').value), gap_m:Number($('#at-gap').value)};
  }
  function draw(result) {
    const svg = $('#at-map'); svg.replaceChildren();
    const lat = result.coordinates.reduce((sum,p) => sum+p[1],0)/result.coordinates.length;
    const pts = result.coordinates.map(p=>[p[0]*Math.cos(lat*Math.PI/180),-p[1]]);
    const xs=pts.map(p=>p[0]), ys=pts.map(p=>p[1]);
    const minX=Math.min(...xs), maxX=Math.max(...xs), minY=Math.min(...ys), maxY=Math.max(...ys);
    const scale=Math.min(820/Math.max(maxX-minX,1e-9),240/Math.max(maxY-minY,1e-9));
    const positions=pts.map(p=>[40+(p[0]-minX)*scale,40+(p[1]-minY)*scale]);
    positions.slice(1).forEach((p,i)=>{
      const segment=document.createElementNS(SVG_NS,'line');
      const level=result.levels[i]===result.levels[i+1]?result.levels[i]:0;
      for (const [key,value] of Object.entries({x1:positions[i][0],y1:positions[i][1],x2:p[0],y2:p[1],stroke:level===2?'#ffbc66':level===1?'#b59aff':'#53decc','stroke-width':4})) segment.setAttribute(key,value);
      svg.append(segment);
    });
    [[0,'起点'],[positions.length-1,'终点']].forEach(([i,name])=>{
      const p=positions[i],text=document.createElementNS(SVG_NS,'text');
      text.setAttribute('x',p[0]);text.setAttribute('y',p[1]+22);text.setAttribute('fill','#fff');text.textContent=name;svg.append(text);
    });
  }
  window.autotrackResult = async (result, context) => {
    if(result.operation==='catalog'){
      if(context?.catalogSave!==$('#save-select').value)return;
      catalog=result;catalog.save=$('#save-select').value;
      $('#at-stations').replaceChildren(...result.stations.map(s=>option(s.name,stationLabel(s))));
      $('#at-route-path').replaceChildren(...(result.routes.length?result.routes.map(r=>option(r.name,r.path)):[option('未发现路线文件','')]));
      if(!$('#at-map-path').value&&result.maps.length===1)$('#at-map-path').value=result.maps[0];
      $('#at-catalog-state').textContent=`已读取 ${result.stations.length} 站 · ${result.routes.length} 份本地路线 · ${result.maps.length} 份游戏底图。${result.node_ready?'自动寻路运行时已找到。':'未找到 Node.js，自动寻路需安装 Node.js 22+；GeoJSON 仍可用。'}`;
      $('#at-state').textContent='资料已就绪，请选择路线并预览';updateMode();return;
    }
    if (result.output_save) {
      preview = null; $('#at-apply').disabled = $('#at-download').disabled = true;
      $('#at-state').textContent = '新副本已生成 · 等待游戏验收';
      $('#at-output').textContent = `游戏加载此文件：${result.output_save}。原存档没有修改。`;
      toast('自动铺轨副本已生成，请先在游戏中暂停检查。');
      return;
    }
    if (context?.revision !== revision || context?.signature !== JSON.stringify(request())) {
      invalidate(); toast('预览期间参数或存档选择改变，请重新预览。',true); return;
    }
    preview = {result, request:request()}; draw(result);
    $('#at-state').textContent = '预览完成 · 尚未写入';
    $('#at-summary').textContent = `${(result.length_m/1000).toFixed(2)} 公里 · ${result.nodes} 个双轨节点 · 桥梁 ${result.bridge_nodes} / 隧道 ${result.tunnel_nodes||0} 节点 · 区间 ${result.start_m}–${result.end_m} 米 · 避让记录 ${result.avoided_intervals}`+(result.routing?.snap_m?` · 两站到底图的吸附距离 ${result.routing.snap_m.join(' / ')} 米 · 读取 ${result.routing.tiles} 瓦片 · 底图类型 ${result.routing.rail_types.join(' / ')}`:'');
    $('#at-warnings').replaceChildren(...result.warnings.map(message=>{const li=document.createElement('li');li.textContent=message;return li;}));
    $('#at-apply').disabled = !$('#at-accept').checked; $('#at-download').disabled = false;
  };
  window.autotrackFailure = message => {
    preview=null; $('#at-apply').disabled=$('#at-download').disabled=true;
    $('#at-state').textContent='已停止 · 未完成生成';
    $('#at-output').textContent=message;
    if(!catalog)$('#at-catalog-state').textContent=`自动读取未就绪：${message}`;
  };
  $('#at-preview').addEventListener('click',async()=>{
    try { invalidate(); const payload=request(); const started=await startTask('autotrack',payload,{revision,signature:JSON.stringify(payload)}); if(started)$('#at-state').textContent='正在后台检查…'; }
    catch(e){toast(e.message,true);}
  });
  $('#at-apply').addEventListener('click',async()=>{
    try {
      if(!preview||!$('#at-accept').checked)throw new Error('请先预览并确认验收提示');
      if(JSON.stringify(request())!==JSON.stringify(preview.request)){invalidate();throw new Error('参数改变，请重新预览');}
      // The explicit acknowledgement checkbox above is the confirmation; avoid
      // a second blocking browser dialog in the native desktop webview.
      const started=await startTask('autotrack',{...preview.request,apply:true,fingerprint:preview.result.fingerprint,output:outputPath('Autotrack')});
      if(started)$('#at-apply').disabled=true;
    }catch(e){toast(e.message,true);}
  });
  $('#at-download').addEventListener('click',()=>{
    if(!preview)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(preview.result,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='autotrack-preview.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  $('#at-accept').addEventListener('change',()=>{$('#at-apply').disabled=!!state.taskActive||!preview||!$('#at-accept').checked;});
  ['#at-variant','#at-bridge-variant','#at-tunnel-variant','#at-structure','#at-from','#at-to','#at-map-path','#at-route-path','#at-rail-type','#at-start','#at-end','#at-gap','#save-select'].forEach(id=>$(id).addEventListener('change',invalidate));
  $('#at-preset').addEventListener('change',()=>{invalidate();updateMode();});
  $('#at-file').addEventListener('change',async()=>{
    invalidate(); imported=null;
    const fileRevision=revision;
    try {const file=$('#at-file').files[0];if(!file)return;if(file.size>500000)throw new Error('路线文件须小于 500 KB');const data=JSON.parse(await file.text());if(fileRevision!==revision)return;imported=data;toast(`已导入：${file.name}，请点击预览。`);}catch(e){toast(e.message,true);}
  });
  $('#at-choose-save').addEventListener('click',()=>document.querySelector('[data-view="dashboard"]').click());
  $('#at-refresh').addEventListener('click',readCatalog);
  document.querySelector('[data-view="autotrack"]').addEventListener('click',async()=>{
    $('#at-save-name').textContent=$('#save-select').value.split(/[\\/]/).pop()||'尚未选择';
    if(!catalog||catalog.save!==$('#save-select').value)readCatalog();
    updateMode();
    await tutorialReady;if(!tutorialSeen){lesson=0;showLesson();}
  });
})();
