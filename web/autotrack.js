/* Experimental blueprint UI; computation/writing uses the existing hidden worker. */
(() => {
  'use strict';
  viewMeta.autotrack = ['TRACK BLUEPRINT LAB', '自动铺轨 · 实验'];
  let imported = null, preview = null, revision = 0, catalog = null;
  let viaValues=[];
  const tutorialKey='nimby.autotrack.tutorial.v3';
  let tutorialSeen=false,tutorialTouched=false;
  const tutorialReady=api('/api/workspace/state',{method:'POST',body:JSON.stringify({key:tutorialKey})}).then(r=>{if(!tutorialTouched)tutorialSeen=r.value?.seen===true;}).catch(()=>{});
  const lessons=[
    ['先选存档，再自动读取','在总览选择刚保存的文件。打开本页会自动读取站名、Steam 底图和本地路线。自动寻路需要 Node.js 22+；缺少时会提示，不会静默安装。'],
    ['按顺序添加起点、途经站和终点','选择含 ID 的完整站名，同名站不会混淆；也可输入 经度,纬度。用“添加途经站”和上下移动调整站序，最多 20 站。逐段检查，不会跳过失败站点或用直线顶替断路。'],
    ['地面、桥梁、隧道分别设置','自动模式默认中速地面，并保留底图桥隧标记。三种结构可分别选中速、高速、电车；也可强制全程地面、高架或隧道。速度是类型上限，桥隧层级不是地形高程。'],
    ['处理失败区间后，生成一个新副本','检查每个区间的结果。失败时可删除相关站点或修改线路类型，重新预览；全部通过才允许写入。各站附近留接轨空隙，生成后在游戏里手动接站和设置信号，不要覆盖正式档。']
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
  function syncVia(){viaValues=viaValues.map((value,i)=>$(`#at-via-${i}`).value);}
  function renderVia(){
    const rows=viaValues.map((value,i)=>{
      const row=document.createElement('div');row.className='at-via-row';
      const label=document.createElement('label');label.textContent=`途经站 ${i+1}`;
      const input=document.createElement('input');input.id=`at-via-${i}`;input.value=value;
      input.setAttribute('list','at-stations');input.placeholder='选择完整站名；或输入 经度,纬度';
      input.addEventListener('input',()=>{viaValues[i]=input.value;invalidate();});
      label.append(input);row.append(label);
      [['上移',-1],['下移',1],['删除',0]].forEach(([name,delta])=>{
        const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent=name;
        button.setAttribute('aria-label',`${name}途经站 ${i+1}`);
        button.disabled=(delta===-1&&i===0)||(delta===1&&i===viaValues.length-1);
        button.addEventListener('click',()=>{
          syncVia();if(delta)[viaValues[i],viaValues[i+delta]]=[viaValues[i+delta],viaValues[i]];else viaValues.splice(i,1);
          invalidate();renderVia();updateMode();
        });row.append(button);
      });return row;
    });
    $('#at-via-list').replaceChildren(...rows);$('#at-add-via').disabled=viaValues.length>=18;
  }
  function removeStation(index){
    syncVia();const all=[$('#at-from').value,...viaValues,$('#at-to').value];
    if(all.length<=2){toast('至少保留起点和终点；请修改该站。',true);return;}
    all.splice(index,1);$('#at-from').value=all[0];$('#at-to').value=all[all.length-1];viaValues=all.slice(1,-1);
    invalidate();renderVia();updateMode();toast('已删除该站，请重新预览新的相邻区间。');
  }
  $('#at-add-via').addEventListener('click',()=>{
    syncVia();if(viaValues.length>=18)return;viaValues.push('');invalidate();renderVia();updateMode();
  });
  async function readCatalog(){
    const save=$('#save-select').value;if(!save)return;
    if(state.taskActive){toast('请等待当前后台任务完成，再重新自动读取。',true);return;}
    invalidate();catalog=null;$('#at-catalog-state').textContent='正在后台读取站点、游戏底图与本地路线…';
    await startTask('autotrack',{save,operation:'catalog'},{catalogSave:save});
  }
  function updateMode(){
    const mode=$('#at-preset').value;
    $('#at-via-panel').hidden=mode!=='auto';
    ['#at-start','#at-end'].forEach(id=>{$(id).disabled=mode==='auto'&&viaValues.length>0;});
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
    $('#at-leg-results').replaceChildren();
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
      syncVia();
      // Keep malformed entries in the plan so the backend can report all bad
      // stations together rather than failing at the first incomplete input.
      const parse=value=>{try{const e=endpoint(value,'point');return e.point_station?{station:e.point_station}:{coord:e.point_coord};}catch{return {station:null,coord:null};}};
      const from=parse($('#at-from').value),to=parse($('#at-to').value);
      extra={from_station:from.station,from_coord:from.coord,to_station:to.station,to_coord:to.coord,
        via:viaValues.map(parse),map_path:$('#at-map-path').value,rail_type:$('#at-rail-type').value};
    }
    if(preset==='file')extra.route_path=$('#at-route-path').value;
    return {save, preset, ...extra, geojson:preset === 'custom' ? imported : null,
      bridge_variant:Number($('#at-bridge-variant').value||6),tunnel_variant:Number($('#at-tunnel-variant').value||6),structure_mode:$('#at-structure').value||'auto',
      variant:Number($('#at-variant').value), start_m:preset==='auto'&&viaValues.length?0:Number($('#at-start').value),
      end_m:preset==='auto'&&viaValues.length?null:($('#at-end').value === '' ? null : Number($('#at-end').value)), gap_m:Number($('#at-gap').value)};
  }
  function draw(result) {
    const svg = $('#at-map'); svg.replaceChildren();
    const parts=result.multi_station?result.legs.filter(l=>l.status==='ok').map(l=>l.preview):[result];
    const stations=result.multi_station?result.waypoints.filter(p=>Array.isArray(p.coord)&&p.coord.every(Number.isFinite)):[];
    const coords=parts.flatMap(p=>p.coordinates).concat(stations.map(p=>p.coord));
    if(!coords.length)return;
    const lat = coords.reduce((sum,p) => sum+p[1],0)/coords.length;
    const project=p=>[p[0]*Math.cos(lat*Math.PI/180),-p[1]];
    const pts = coords.map(project);
    const xs=pts.map(p=>p[0]), ys=pts.map(p=>p[1]);
    const minX=Math.min(...xs), maxX=Math.max(...xs), minY=Math.min(...ys), maxY=Math.max(...ys);
    const scale=Math.min(820/Math.max(maxX-minX,1e-9),240/Math.max(maxY-minY,1e-9));
    const position=coord=>{const p=project(coord);return [40+(p[0]-minX)*scale,40+(p[1]-minY)*scale];};
    parts.forEach(part=>{
      const positions=part.coordinates.map(position);
      positions.slice(1).forEach((p,i)=>{
      const segment=document.createElementNS(SVG_NS,'line');
      const level=part.levels[i]===part.levels[i+1]?part.levels[i]:0;
      for (const [key,value] of Object.entries({x1:positions[i][0],y1:positions[i][1],x2:p[0],y2:p[1],stroke:level===2?'#ffbc66':level===1?'#b59aff':'#53decc','stroke-width':4})) segment.setAttribute(key,value);
      svg.append(segment);
      });
    });
    const markers=result.multi_station?stations.map(s=>[s.coord,`${s.index+1} · ${s.label}`,s.status]):
      [[result.coordinates[0],'起点','ready'],[result.coordinates[result.coordinates.length-1],'终点','ready']];
    markers.forEach(([coord,name,status])=>{
      const p=position(coord),text=document.createElementNS(SVG_NS,'text'),circle=document.createElementNS(SVG_NS,'circle');
      for(const [key,value] of Object.entries({cx:p[0],cy:p[1],r:5,fill:status==='ready'?'#53decc':'#ff8d83'}))circle.setAttribute(key,value);
      text.setAttribute('x',p[0]);text.setAttribute('y',p[1]+22);text.setAttribute('fill','#fff');
      text.setAttribute('text-anchor',p[0]>600?'end':'start');text.setAttribute('font-size','12');
      text.textContent=name;svg.append(circle,text);
    });
  }
  function renderLegs(result){
    const root=$('#at-leg-results');root.replaceChildren();if(!result.multi_station)return;
    const intro=document.createElement('p');intro.textContent='按站序逐段检查；区间失败不一定由某一站造成。删除站点会重新连接它前后的站，须再次预览。';root.append(intro);
    for(const leg of result.legs){
      const row=document.createElement('div');row.className=`at-leg ${leg.status==='ok'?'':'at-leg-error'}`;
      const title=document.createElement('strong');title.textContent=`${leg.status==='ok'?'✓ 通过':'✕ 未通过'} · ${leg.index+1}：${leg.from_name} → ${leg.to_name}`;
      const detail=document.createElement('p');
      detail.textContent=leg.status==='ok'?`${(leg.preview.length_m/1000).toFixed(2)} 公里 · ${leg.preview.nodes} 节点 · 吸附距离 ${leg.preview.routing.snap_m?.join(' / ')||'—'} 米`:leg.error;
      row.append(title,detail);
      if(leg.status!=='ok')for(const index of [leg.from_index,leg.to_index]){
        const button=document.createElement('button');button.type='button';button.className='text-button';
        const label=result.waypoints[index].label;
        button.textContent=`删除第 ${index+1} 站`+(label===`第 ${index+1} 站`?'':`：${label}`);button.disabled=result.waypoints.length<=2;
        button.addEventListener('click',()=>removeStation(index));row.append(button);
      }
      root.append(row);
    }
  }
  window.autotrackResult = async (result, context) => {
    if(result.operation==='catalog'){
      if(context?.catalogSave!==$('#save-select').value)return;
      catalog=result;catalog.save=$('#save-select').value;
      $('#at-stations').replaceChildren(...result.stations.map(s=>option(s.name,stationLabel(s))));
      $('#at-route-path').replaceChildren(...(result.routes.length?result.routes.map(r=>option(r.name,r.path)):[option('未发现路线文件','')]));
      if(!$('#at-map-path').value&&result.maps.length===1)$('#at-map-path').value=result.maps[0];
      $('#at-catalog-state').textContent=`已读取 ${result.stations.length} 站 · ${result.routes.length} 份本地路线 · ${result.maps.length} 份游戏底图。${result.node_ready?'自动寻路运行时已找到。':'未找到 Node.js，自动寻路寻路组件缺失：完整包请重新完整解压；源码版需提供 Node.js 22+；GeoJSON 仍可用。'}`;
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
    preview = {result, request:request()}; draw(result);renderLegs(result);
    $('#at-state').textContent = result.can_apply===false?'部分区间未通过 · 已禁止写入':'预览完成 · 尚未写入';
    $('#at-summary').textContent = result.multi_station?
      `${result.waypoints.length} 站 / ${result.legs.length} 个区间 · 通过 ${result.successful_legs} / 失败 ${result.failed_legs} · 可用区间 ${(result.length_m/1000).toFixed(2)} 公里 · ${result.nodes} 个双轨节点`:
      `${(result.length_m/1000).toFixed(2)} 公里 · ${result.nodes} 个双轨节点 · 桥梁 ${result.bridge_nodes} / 隧道 ${result.tunnel_nodes||0} 节点 · 区间 ${result.start_m}–${result.end_m} 米 · 避让记录 ${result.avoided_intervals}`+(result.routing?.snap_m?` · 两站到底图的吸附距离 ${result.routing.snap_m.join(' / ')} 米 · 读取 ${result.routing.tiles} 瓦片 · 底图类型 ${result.routing.rail_types.join(' / ')}`:'');
    $('#at-warnings').replaceChildren(...result.warnings.map(message=>{const li=document.createElement('li');li.textContent=message;return li;}));
    $('#at-apply').disabled = result.can_apply===false||!$('#at-accept').checked; $('#at-download').disabled = false;
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
      if(preview.result.can_apply===false)throw new Error('仍有失败区间，请删除或调整站点后重新预览');
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
  $('#at-accept').addEventListener('change',()=>{$('#at-apply').disabled=!!state.taskActive||!preview||preview.result.can_apply===false||!$('#at-accept').checked;});
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
