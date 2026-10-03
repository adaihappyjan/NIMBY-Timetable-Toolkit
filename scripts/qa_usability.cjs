// Isolated UI acceptance: mock APIs only; never opens or modifies a game save.
// NODE_PATH must provide Playwright. Outputs are written only to the given QA folder.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../web'), output=path.resolve(process.argv[2]);
fs.mkdirSync(output,{recursive:true});
const exportsSeen=[];
const english=process.env.QA_LANGUAGE==='en';
const cleanupCalls=[];
const bootstrap={ok:true,app_version:fs.readFileSync(path.join(root,'../VERSION'),'utf8').trim(),files:{saves:[],exports:[]},settings:{enabled:false,days:14,keep:5,auto_check_updates:false},
  cleanup:{completed_copy_count:1,protected_copy_count:1,candidate_count:0,candidate_bytes:0,keep:5,days:14,targets:[],copies:[{name:'QA_Workspace_20260101_000000.nimbyrails5',pinned:true}]},capabilities:[],map_export_dir:output};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/')){
    let body='';for await(const part of req)body+=part;const payload=body?JSON.parse(body):{};
    let result={ok:true,value:{},accounting:[],packages:[],tasks:[]};
    if(url.pathname==='/api/bootstrap')result=bootstrap;
    if(url.pathname==='/api/files')result={ok:true,files:bootstrap.files};
    if(url.pathname==='/api/cleanup/preview'){
      const targets=[{name:'旧时刻表.json',path:'QA-old-timetable.json',kind:'timetable-json',bytes:100,reason:'旧游戏导出，需确认'},
        {name:'旧线路图.json',path:'QA-old-map.json',kind:'map-json',bytes:200,reason:'旧地图，需确认'}]
        .filter(x=>x.kind==='map-json'?payload.include_maps:payload.include_timetables);
      result={ok:true,cleanup:{...bootstrap.cleanup,token:'qa-cleanup',days:payload.days,keep:payload.keep,
        targets,candidate_count:targets.length,candidate_bytes:targets.reduce((s,x)=>s+x.bytes,0)}};
    }
    if(url.pathname==='/api/cleanup/execute'){
      cleanupCalls.push(payload);result={ok:true,result:{moved_group_count:payload.selected.length,moved_file_count:payload.selected.length,recoverable:true}};
    }
    if(url.pathname==='/api/map/export'){
      assert.ok(!payload.filename.includes('/')&&!payload.filename.includes('\\'));
      const file=path.join(output,payload.filename);
      fs.writeFileSync(file,payload.format==='svg'?payload.svg:JSON.stringify(payload.data,null,2));
      exportsSeen.push({format:payload.format,path:file});result={ok:true,path:file};
    }
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(result));return;
  }
  if(process.env.QA_STATIC_ORIGIN){
    // Exercise the actual Python static handler/bundle, while all data APIs stay mocked.
    const assetURL=new URL(req.url,process.env.QA_STATIC_ORIGIN);
    if(!assetURL.searchParams.has('lang'))assetURL.searchParams.set('lang',process.env.QA_LANGUAGE||'zh-CN');
    const upstream=await fetch(assetURL);
    res.writeHead(upstream.status,{'Content-Type':upstream.headers.get('content-type')||'application/octet-stream'});
    res.end(Buffer.from(await upstream.arrayBuffer()));return;
  }
  const file=path.resolve(root,'.'+(url.pathname==='/'?'/index.html':decodeURIComponent(url.pathname)));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
  const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png'}[path.extname(file)]||'application/octet-stream';
  res.writeHead(200,{'Content-Type':mime+'; charset=utf-8'});res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1500,height:1100},deviceScaleFactor:1});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForFunction(()=>typeof state!=='undefined'&&state.bootstrap);
    await page.evaluate(()=>{
      const station=(name,lon,lat)=>({name,lon,lat});
      renderMapData({station_count:10,stations:{
        a:station('西山公园',0,0),b:station('大学城',1,0),c:station('中央车站',2,0),d:station('市政广场',3,0),e:station('滨江东站',4,0),
        f:station('机场',2,2),g:station('北苑',2,1),h:station('南湖',2,-1),i:station('南部新城',2,-2),j:station('博物馆',4,-1)},
        lines:[{id:'1',name:'1号线 · 东西干线',code:'1',color:'ff4242e8',stop_count:5,stops:['a','b','c','d','e']},
        {id:'2',name:'2号线 · 南北干线',code:'2',color:'ffe59b24',stop_count:5,stops:['f','g','c','h','i']},
        {id:'3',name:'3号线 · 滨江支线',code:'3',color:'ff5fa231',stop_count:4,stops:['h','c','d','j']}]});
      switchView('map');
    });
    await page.selectOption('#map-style','metro');
    await page.locator('#map-canvas svg[data-map-style="metro"]').waitFor();
    await page.waitForTimeout(400);
    await page.evaluate(()=>{document.querySelector('#toast').hidden=true;});
    await page.locator('#map-canvas').screenshot({path:path.join(output,'metro-network.png')});
    assert.equal(await page.locator('#map-canvas [data-station]').count(),10);
    // Theme must activate the schematic even if an old UI exposes the control
    // while a different style is selected. Hidden controls must actually hide.
    await page.selectOption('#map-style','geo');
    assert.equal(await page.locator('#map-metro-theme-wrap').isVisible(),false);
    await page.evaluate(()=>{const el=document.querySelector('#map-metro-theme');el.value='atlas';el.dispatchEvent(new Event('change'));});
    assert.equal(await page.locator('#map-canvas svg').getAttribute('data-metro-theme'),'atlas');
    assert.match(await page.locator('#map-render-status').innerText(),english?/Railway overview/i:/已绘制.*铁路总览/);
    await page.selectOption('#map-metro-theme','metro');
    await page.click('#export-map-svg');await page.click('#export-map-json');
    await page.waitForFunction(()=>document.querySelector('#map-export-status').textContent.includes('.json'));
    assert.equal(exportsSeen.length,2);
    const json=JSON.parse(fs.readFileSync(exportsSeen.find(e=>e.format==='json').path));
    assert.equal(json.drawing.style,'metro');assert.equal(json.schematic_layout.coordinate_space,'display-only');assert.equal(json.stations.c.lon,2);
    const svg=fs.readFileSync(exportsSeen.find(e=>e.format==='svg').path,'utf8');assert.match(svg,english?/Metro network/i:/地铁线网图/);
    await page.fill('#map-line-search','1号线');
    assert.equal(await page.locator('.map-line-check').count(),1);
    assert.equal(await page.evaluate(()=>selectedMapLines().length),3);
    await page.click('#map-clear');assert.equal(await page.evaluate(()=>selectedMapLines().length),2);
    await page.click('#map-select-all');assert.equal(await page.evaluate(()=>selectedMapLines().length),3);
    await page.fill('#map-line-search','不存在的线路');assert.equal(await page.locator('.map-line-check').count(),0);
    assert.equal(await page.evaluate(()=>buildMapJsonData().lines.length),3);
    await page.fill('#map-line-search','');await page.selectOption('#map-line-sort','name-desc');
    assert.match(await page.locator('.map-line-option strong').first().innerText(),/3号线/);
    await page.selectOption('#map-line-sort','name-asc');
    await page.locator('.map-branch-controls summary').click();
    await page.fill('#map-branch-name','测试同线路分支');
    await page.fill('#map-line-search','1号线');
    await page.click('#map-branch-group');
    assert.equal(await page.evaluate(()=>state.metroLayout.display_lines.length),1);
    assert.equal(await page.locator('[data-transfer="true"]').count(),0);
    assert.equal(await page.evaluate(()=>Object.keys(buildMapJsonData().drawing.branch_groups).length),3,'manual grouping includes hidden checked lines');
    assert.equal(await page.evaluate(()=>buildMapJsonData().lines.length),3,'source lines stay separate in export');
    await page.click('#map-branch-independent');
    assert.equal(await page.evaluate(()=>state.metroLayout.display_lines.length),3);
    await page.click('#map-branch-auto');
    assert.equal(await page.evaluate(()=>Object.keys(state.mapBranchGroups).length),0);
    await page.fill('#map-line-search','');
    await page.locator('.map-branch-controls summary').click();
    if(process.argv[3]) {
      const objects=JSON.parse(fs.readFileSync(process.argv[3],'utf8').replace(/^\uFEFF/,''));
      const stations=Object.fromEntries(objects.filter(o=>o.class==='Station'&&o.lonlat).map(o=>[o.id,{name:o.name,lon:o.lonlat[0],lat:o.lonlat[1]}]));
      const lines=objects.filter(o=>o.class==='Line'&&o.name.includes('STM')&&o.stops?.length>1).map(o=>({id:o.id,name:o.name,code:o.code,color:o.color,stops:o.stops.map(s=>s.station_id),stop_count:o.stops.length}));
      assert.ok(lines.length>0);
      await page.evaluate(data=>renderMapData(data),{lines,stations,station_count:Object.keys(stations).length});
      await page.evaluate(()=>{document.querySelector('#toast').hidden=true;});
      await page.locator('#map-canvas').screenshot({path:path.join(output,'metro-STM-real-export.png')});
      await page.click('#export-map-svg');await page.click('#export-map-json');
      await page.waitForFunction(()=>document.querySelector('#map-export-status').textContent.includes('.json'));
      assert.equal(await page.evaluate(()=>state.metroLayout.label_conflicts),0);
      assert.equal(await page.locator('[data-station-label]').count(),await page.locator('[data-station]').count());
      const detached=await page.evaluate(()=>{
        const graph=metroTopology(selectedMapLines(),state.network.stations);
        const linked=new Set(graph.edges.flatMap(e=>[e.a,e.b]));
        const strokes=[...document.querySelectorAll('#map-canvas path[data-line]')].map(path=>{
          const length=path.getTotalLength(),points=[];for(let d=0;d<=length;d+=2)points.push(path.getPointAtLength(d));points.push(path.getPointAtLength(length));return {id:path.dataset.line,points};
        });
        return [...document.querySelectorAll('#map-canvas [data-station]')].filter(dot=>{
          const id=dot.dataset.station;if(!linked.has(id))return false;
          const allowed=new Set(selectedMapLines().filter(l=>l.stops.map(String).includes(id)).map(l=>String(l.id)));
          const x=+dot.getAttribute('cx'),y=+dot.getAttribute('cy'),r=+dot.getAttribute('r');
          return !strokes.some(s=>allowed.has(s.id)&&s.points.some(p=>Math.hypot(p.x-x,p.y-y)<=r+1.5));
        }).map(dot=>dot.querySelector('title').textContent);
      });
      assert.deepEqual(detached,[],'connected station markers must touch their own lines');
      await page.selectOption('#map-metro-theme','atlas');
      await page.evaluate(()=>{document.querySelector('#toast').hidden=true;});
      await page.locator('#map-canvas').screenshot({path:path.join(output,'rail-atlas-STM.png')});
      const fit=await page.locator('#map-canvas svg').boundingBox();
      assert.ok(fit.height<=1100*0.72+2,'portrait atlas fits viewport height');
      assert.equal(await page.locator('#map-canvas [data-station-label]').count(),await page.locator('#map-canvas [data-station]').count());
      await page.evaluate(()=>{document.querySelector('#map-canvas').scrollTop=500;});
      await page.selectOption('#map-metro-theme','metro');
      assert.equal(await page.locator('#map-canvas').evaluate(e=>e.scrollTop),0);
      const gallery=await page.evaluate(()=>{
        const names=['Snowdon','Vendôme','Atwater','Jean-Talon','Lionel-Groulx'];
        return names.map(name=>{
          const entry=Object.entries(state.network.stations).find(([,s])=>s.name===name);if(!entry)return '';
          const p=state.metroLayout.positions[entry[0]];if(!p)return '';
          const svg=state.mapSvg.cloneNode(true);svg.removeAttribute('style');svg.setAttribute('viewBox',`${p.x-85} ${p.y-70} 170 140`);
          svg.setAttribute('width','340');svg.setAttribute('height','280');
          return `<section><h3>${name}</h3>${svg.outerHTML}</section>`;
        }).join('');
      });
      const detail=await browser.newPage({viewport:{width:1080,height:720}});
      await detail.setContent(`<body style="margin:20px;background:white;display:flex;flex-wrap:wrap;font-family:sans-serif">${gallery}</body>`);
      await detail.screenshot({path:path.join(output,'junction-details.png'),fullPage:true});await detail.close();
      await page.selectOption('#map-zoom','1');
      assert.ok((await page.locator('#map-canvas svg').getAttribute('style')).includes('px'));
      await page.selectOption('#map-zoom','fit');
      await page.fill('#map-line-search','STM');
      await page.locator('.map-list-tools').screenshot({path:path.join(output,'line-search-sort.png')});
      for(const region of ['TTC','Montreal','GO']){
        if(process.env.QA_DETAILS)await page.evaluate(()=>{
          if(window.qaOriginalJoin)return;window.qaOriginalJoin=metroJoinCorridors;
          metroJoinCorridors=(...args)=>{window.qaRoutes=args[0];const result=window.qaOriginalJoin(...args);window.qaPaths=result;return result;};
        });
        const regionLines=objects.filter(o=>o.class==='Line'&&o.stops?.length>1&&(region==='TTC'?o.name.includes('TTC'):region==='GO'?/^GO /i.test(o.name):/STM|REM/.test(o.name))).map(o=>({id:o.id,name:o.name,code:o.code,color:o.color,stops:o.stops.map(s=>s.station_id),stop_count:o.stops.length}));
        if(region==='GO')await page.selectOption('#map-metro-orientation','geo');
        await page.fill('#map-line-search','');
        await page.evaluate(data=>renderMapData(data),{lines:regionLines,stations,station_count:Object.keys(stations).length});
        if(region==='TTC')assert.ok(await page.evaluate(()=>{
          const a=state.metroLayout.positions['0x20000007f0003'],b=state.metroLayout.positions['0x2000000800002'];
          return state.metroLayout.rotated?b.y>a.y:b.x>a.x;
        }),'Spadina to St. George must not reverse its eastward order');
        if(region==='TTC'){
          const unionPath=await page.locator('[data-station-join="0x2000000700001"]').getAttribute('d');
          assert.match(unionPath,/ Q/,'Union is one tangent corner, not two retracing cubic curves');
          assert.doesNotMatch(unionPath,/ C/);
        }
        if(process.env.QA_DETAILS)console.log(JSON.stringify(await page.evaluate(()=>({debugRoutes:window.qaRoutes.filter(r=>r.ids.some(id=>/^(Union)$/.test(state.network.stations[id]?.name))).map(r=>({...r,name:selectedMapLines()[r.line]?.name})),debugPaths:window.qaPaths.filter(r=>/0x2000000700001/.test(r.join)).map(r=>({line:r.line,d:r.d}))}))));
        if(region==='GO'){
          const intrusion=await page.evaluate(()=>{
            const lines=selectedMapLines(),positions=state.metroLayout.positions;
            const failures=[];
            for(const dot of document.querySelectorAll('#map-canvas [data-station]')){
              const id=dot.dataset.station,p={x:+dot.dataset.x,y:+dot.dataset.y};
              if(dot.dataset.transfer==='true')continue;
              for(const path of document.querySelectorAll('#map-canvas path[data-line]')){
                const sources=JSON.parse(path.dataset.sourceLines);
                if(lines.some(l=>sources.includes(String(l.id))&&l.stops.includes(id)))continue;
                const length=path.getTotalLength();
                for(let d=0;d<=length;d+=2){const q=path.getPointAtLength(d);if(Math.hypot(q.x-p.x,q.y-p.y)<8){failures.push(state.network.stations[id].name);break;}}
              }
            }
            return failures;
          });
          assert.deepEqual(intrusion,[],'an ordinary GO station must not sit on an unrelated line');
        }
        for(const marker of ['circle','capsule']){
          await page.selectOption('#map-transfer-style',marker);
          await page.evaluate(()=>{document.querySelector('#toast').hidden=true;});
          assert.ok(await page.locator(`[data-transfer="true"][data-marker="${marker}"]`).count()>0);
          assert.equal(await page.evaluate(()=>buildMapJsonData().drawing.transfer_style),marker);
          assert.equal(await page.evaluate(()=>state.metroLayout.transfer_style),marker);
          if(marker==='circle'){
            const missed=await page.evaluate(()=>{
              const lines=selectedMapLines(),graph=metroTopology(lines,state.network.stations);
              const paths=[...document.querySelectorAll('#map-canvas path[data-line]')].map(path=>{
                const length=path.getTotalLength(),points=[];for(let d=0;d<=length;d+=2)points.push(path.getPointAtLength(d));points.push(path.getPointAtLength(length));return {lines:JSON.parse(path.dataset.sourceLines||JSON.stringify([path.dataset.line])),points};
              });
              const failures=[];
              for(const dot of document.querySelectorAll('#map-canvas [data-station]')){
                const id=dot.dataset.station,x=+dot.getAttribute('cx'),y=+dot.getAttribute('cy'),radius=+dot.getAttribute('r');
                const used=new Set(graph.edges.filter(e=>e.a===id||e.b===id).flatMap(e=>[...e.lines]));
                for(const line of used)if(!paths.some(p=>p.lines.includes(String(lines[line].id))&&p.points.some(p=>Math.hypot(p.x-x,p.y-y)<radius+2)))failures.push(`${state.network.stations[id].name}: ${lines[line].name}`);
              }
              return failures;
            });
            assert.deepEqual(missed,[],'every incident line must reach its station marker');
          }
          await page.locator('#map-canvas').screenshot({path:path.join(output,`${region}-${marker}.png`)});
          const clips=await page.evaluate(()=>{
            const match=/^(Toronto Union Station|Aldershot GO|Weston GO|Union|King|Queen|TMU|Summerhill|St\. Clair|Avenue|Spadina|Museum|Bay|Canora|Ville-de-Mont-Royal)$/;
            return Object.entries(state.network.stations).filter(([,s])=>match.test(s.name)).map(([id,s])=>{
              const p=state.metroLayout.positions[id];if(!p)return '';
              const svg=state.mapSvg.cloneNode(true);svg.removeAttribute('style');svg.setAttribute('viewBox',`${p.x-70} ${p.y-55} 140 110`);
              svg.setAttribute('width','280');svg.setAttribute('height','220');
              return `<section><h3>${s.name}</h3>${svg.outerHTML}</section>`;
            }).join('');
          });
          const details=await browser.newPage({viewport:{width:900,height:780}});
          await details.setContent(`<body style="margin:20px;display:flex;flex-wrap:wrap;font-family:sans-serif">${clips}</body>`);
          await details.screenshot({path:path.join(output,`${region}-${marker}-details.png`),fullPage:true});await details.close();
        }
      }
      await page.selectOption('#map-transfer-style','circle');
      const remLines=objects.filter(o=>o.class==='Line'&&/^REM[\s_-]*A\d/.test(o.name)&&o.stops?.length>1).map(o=>({id:o.id,name:o.name,color:o.color,stops:o.stops.map(s=>s.station_id),stop_count:o.stops.length}));
      await page.evaluate(data=>renderMapData(data),{lines:remLines,stations,station_count:Object.keys(stations).length});
      assert.equal(await page.locator('[data-transfer="true"]').count(),0);
      assert.equal(await page.evaluate(()=>state.metroLayout.display_lines.length),1);
      assert.equal(await page.evaluate(()=>buildMapJsonData().lines.length),remLines.length);
      await page.evaluate(()=>document.querySelector('#toast').hidden=true);
      await page.locator('#map-canvas').screenshot({path:path.join(output,'REM-merged.png')});
      await page.uncheck('#map-merge-branches');
      assert.ok(await page.locator('[data-transfer="true"]').count()>0);
      await page.check('#map-merge-branches');
      await page.selectOption('#map-metro-layout','grid');
      assert.equal(await page.evaluate(()=>state.metroLayout.layout),'grid');
      assert.equal(await page.locator('[data-transfer="true"]').count(),0);
      assert.ok(await page.evaluate(()=>Object.values(state.metroLayout.positions).every(p=>['x','y'].every(axis=>{
        const q=(p[axis]-state.metroLayout.grid_origin[axis])/state.metroLayout.grid_step;return Math.abs(q-Math.round(q))<1e-7;
      }))));
      await page.locator('#map-canvas').screenshot({path:path.join(output,'REM-grid.png')});
      await page.selectOption('#map-metro-layout','regular');
      if(process.env.QA_ALL_LINES){
        const allLines=objects.filter(o=>o.class==='Line'&&o.stops?.length>1).map(o=>({id:o.id,name:o.name,code:o.code,color:o.color,stops:o.stops.map(s=>s.station_id),stop_count:o.stops.length}));
        const stress=await page.evaluate(data=>{
          const start=performance.now();renderMapData(data);
          return {lines:data.lines.length,stations:Object.keys(state.metroLayout.positions).length,
            labels:state.metroLayout.label_count,conflicts:state.metroLayout.label_conflicts,
            elapsed_ms:Math.round(performance.now()-start),width:state.metroLayout.width,height:state.metroLayout.height};
        },{lines:allLines,stations,station_count:Object.keys(stations).length});
        assert.equal(stress.labels,stress.stations);assert.ok(Number.isFinite(stress.width)&&Number.isFinite(stress.height));
        console.log(JSON.stringify({all_lines_stress:stress}));
        const gridStress=await page.evaluate(()=>{
          const start=performance.now();document.querySelector('#map-metro-layout').value='grid';drawTransitMap();
          const layout=state.metroLayout;
          return {layout:layout.layout,stations:Object.keys(layout.positions).length,labels:layout.label_count,elapsed_ms:Math.round(performance.now()-start),unique:new Set(Object.values(layout.positions).map(p=>`${p.x},${p.y}`)).size};
        });
        assert.equal(gridStress.layout,'grid');assert.equal(gridStress.stations,gridStress.labels);assert.equal(gridStress.stations,gridStress.unique);
        console.log(JSON.stringify({all_lines_grid:gridStress}));
      }
    }
    await page.evaluate(()=>switchView('timetable'));
    await page.locator('#view-timetable').screenshot({path:path.join(output,'timetable-guidance.png')});
    await page.evaluate(()=>switchView('cleanup'));
    await page.getByText(english?'Copy protection · Check to keep permanently':'副本保留管理 · 勾选后永久保留').click();
    assert.equal(await page.locator('[data-protect-copy]').isChecked(),true);
    await page.locator('#view-cleanup').screenshot({path:path.join(output,'cleanup-guidance.png')});
    await page.check('#cleanup-timetables');await page.check('#cleanup-maps');
    await page.click('#refresh-cleanup');
    await page.waitForFunction(()=>!state.cleanupBusy&&state.cleanup?.candidate_count===2);
    assert.equal(await page.locator('.cleanup-select:checked').count(),0);
    assert.ok(await page.locator('#execute-cleanup').isDisabled());
    await page.locator('.cleanup-select').first().check();
    assert.ok(await page.locator('#execute-cleanup').isEnabled());
    await page.fill('#cleanup-days','20');await page.locator('#cleanup-days').blur();
    assert.ok(await page.locator('#execute-cleanup').isDisabled());
    await page.click('#refresh-cleanup');await page.waitForFunction(()=>!state.cleanupBusy&&state.cleanup.days===20);
    await page.locator('.cleanup-select').first().check();
    await page.evaluate(()=>{document.querySelector('#toast').hidden=true;});
    await page.locator('#view-cleanup').screenshot({path:path.join(output,'cleanup-export-selection.png')});
    page.once('dialog',dialog=>dialog.accept());await page.click('#execute-cleanup');
    await page.waitForFunction(()=>!state.cleanupBusy);
    assert.equal(cleanupCalls.length,1);assert.deepEqual(cleanupCalls[0].selected,['QA-old-timetable.json']);
    await page.evaluate(()=>toast(updateFailureMessage({rollback_complete:false,backup_dir:'QA backup',error:'测试恢复失败'}),true));
    assert.match(await page.locator('#error-help').innerText(),english?/diagnostic/i:/展开诊断信息/);
    await page.click('#error-help summary');
    assert.match(await page.locator('#error-help pre').innerText(),english?/not fully restored/i:/恢复不完整/);
    await page.click('#error-help button');
    await page.evaluate(()=>switchView('learn'));
    assert.equal(await page.locator('[data-lesson]').count(),9);
    // Partial blueprint UI acceptance: use fake task results, never game saves.
    await page.evaluate(async()=>{
      switchView('autotrack');
      const select=document.querySelector('#save-select');
      select.replaceChildren(new Option('QA source','QA-source.nimbyrails5'));select.value='QA-source.nimbyrails5';
      document.querySelector('#at-preset').value='auto';
      await window.autotrackResult({operation:'catalog',stations:[],maps:['QA-map'],routes:[],node_ready:true},{catalogSave:'QA-source.nimbyrails5'});
      startTask=async(action,payload,context)=>{window.qaPartialTask={action,payload,context};return true;};
    });
    await page.fill('#at-from','30,20');await page.fill('#at-to','30.015,20');
    await page.click('#at-add-via');await page.fill('#at-via-0','30.005,20');
    await page.click('#at-add-via');await page.fill('#at-via-1','30.01,20');
    await page.click('#at-preview');
    await page.evaluate(async()=>{
      const points=[[30,20],[30.005,20],[30.01,20],[30.015,20]];
      const names=['A 起点','B 西站','C 东站','D 终点'];
      const legs=[0,1,2].map(i=>({index:i,from_index:i,to_index:i+1,from_name:names[i],to_name:names[i+1],status:i===1?'error':'ok',
        ...(i===1?{error:'测试：中间区间不满足要求'}:{preview:{coordinates:[points[i],points[i+1]],levels:[0,0],length_m:500,nodes:4,routing:{snap_m:[0,0]}}})}));
      window.qaPartialResult={multi_station:true,can_apply:true,requires_partial_confirmation:true,successful_legs:2,failed_legs:1,
        fingerprint:'qa-partial-token',length_m:1000,nodes:8,warnings:['跳过 B 西站 → C 东站，缺口不会补连。'],legs,
        waypoints:points.map((coord,index)=>({coord,index,label:names[index],status:index===1||index===2?'warning':'ready'})),
        included_legs:[0,2],skipped_legs:[legs[1]]};
      await window.autotrackResult(window.qaPartialResult,window.qaPartialTask.context);
    });
    assert.ok(await page.locator('#at-partial-wrap').isVisible());
    await page.check('#at-accept');assert.ok(await page.locator('#at-apply').isDisabled());
    await page.check('#at-partial-accept');assert.ok(await page.locator('#at-apply').isEnabled());
    assert.match(await page.locator('#at-apply').innerText(),english?/2 passed sections/:/2 个通过区间/);
    assert.equal(await page.locator('#at-map line').count(),2,'no line across the failed middle leg');
    await page.locator('#at-partial-wrap').scrollIntoViewIfNeeded();
    await page.locator('#at-partial-wrap').evaluate(e=>e.closest('article').setAttribute('data-qa-partial','true'));
    // Clear the earlier intentional updater-failure toast before capturing this panel.
    await page.evaluate(()=>{document.querySelector('#toast').hidden=true;});
    await page.locator('[data-qa-partial]').screenshot({path:path.join(output,'partial-blueprint.png')});
    await page.click('#at-apply');
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.allow_partial),true);
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.fingerprint),'qa-partial-token');
    await page.evaluate(()=>window.autotrackResult({...window.qaPartialResult,partial_output:true,output_save:'QA-only.nimbyrails5'}));
    assert.match(await page.locator('#at-output').innerText(),english?/skipped 1 sections.*B 西站 → C 东站/:/跳过 1 个区间.*B 西站 → C 东站/);
    assert.ok(await page.locator('#at-partial-wrap').isHidden());
    // Saved-station discovery: mock only worker output; exercise the real controls.
    await page.evaluate(async()=>{
      const stations=[{id:'a',name:'起点站'},{id:'z',name:'终点站'},
        {id:'built',name:'沿线站',along_m:1300,distance_m:12,ambiguous:false},
        {id:'planned',name:'沿线站',along_m:2700,distance_m:95,ambiguous:true}];
      await window.autotrackResult({operation:'catalog',stations,maps:['QA-map'],routes:[],node_ready:true},{catalogSave:'QA-source.nimbyrails5'});
      window.qaDiscoveryStations=stations;
    });
    await page.fill('#at-from','起点站 — a');await page.fill('#at-to','终点站 — z');
    await page.click('#at-discover');
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.operation),'discover');
    await page.evaluate(()=>window.autotrackResult({operation:'discover',source_sha256:'qa-snapshot',
      candidates:window.qaDiscoveryStations.slice(2),warnings:['仅列出存档中的已建站 / 蓝图站；平行线路请逐项确认。']},window.qaPartialTask.context));
    assert.equal(await page.locator('#at-discovery-list input:checked').count(),0);
    assert.ok(await page.locator('#at-use-discovery').isDisabled());
    await page.locator('#at-discovery-list input').nth(0).check();
    await page.locator('#at-discovery-list input').nth(1).check();
    assert.ok(await page.locator('#at-use-discovery').isDisabled());
    await page.check('#at-discovery-replace');
    assert.ok(await page.locator('#at-use-discovery').isEnabled());
    assert.equal(await page.locator('#at-discovery-list label').first().evaluate(e=>getComputedStyle(e).flexDirection),'row');
    assert.ok((await page.locator('#at-discovery-replace').boundingBox()).height<=24);
    await page.evaluate(()=>{document.querySelector('#toast').hidden=true;});
    await page.locator('#at-discovery').screenshot({path:path.join(output,'station-discovery.png')});
    await page.click('#at-use-discovery');
    assert.equal(await page.locator('#at-via-0').inputValue(),'沿线站 — built');
    assert.equal(await page.locator('#at-via-1').inputValue(),'沿线站 — planned');
    await page.click('#at-preview');
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.discovery_source_sha256),'qa-snapshot');
    // Facility avoidance controls and worker payload (no live files or game UI).
    assert.ok(await page.locator('#at-player-radius').isDisabled());
    await page.selectOption('#at-player-obstacles','tunnel');
    assert.ok(await page.locator('#at-player-radius').isEnabled());
    await page.fill('#at-player-radius','85');
    await page.click('#at-preview');
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.player_obstacle_mode),'tunnel');
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.player_station_radius_m),85);
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.obstacle_mode),'bridge');
    await page.locator('#at-player-obstacles').evaluate(e=>e.closest('article').setAttribute('data-qa-avoidance','true'));
    await page.locator('[data-qa-avoidance]').screenshot({path:path.join(output,'player-avoidance.png')});
    await page.selectOption('#at-structure','ground');
    assert.ok(await page.locator('#at-player-obstacles').isDisabled());
    assert.ok(await page.locator('#at-player-radius').isDisabled());
    await page.click('#at-preview');
    assert.equal(await page.evaluate(()=>window.qaPartialTask.payload.player_obstacle_mode),'off');
    await page.selectOption('#at-structure','auto');
    assert.ok(await page.locator('#at-player-radius').isEnabled());
    // Stable 1.8.7 theme: navigation SVGs, command search and beta notice.
    await page.evaluate(()=>{switchView('dashboard');document.querySelector('#toast').hidden=true;});
    assert.equal(await page.locator('#main-nav .nav-item svg').count(),17);
    for(const width of [1500,1000,720]){
      await page.setViewportSize({width,height:1100});
      const icon=await page.locator('#main-nav [data-view="dashboard"] svg').boundingBox();
      assert.ok(icon&&icon.width>=16&&icon.height>=16,`navigation icon at ${width}px`);
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({path:path.join(output,`theme-dashboard-${width}.png`),animations:'disabled'});
    }
    await page.setViewportSize({width:1500,height:1100});
    await page.keyboard.press('Control+k');
    await page.fill('#cmdk-input',english?'Features':'功能一览');
    assert.equal(await page.locator('#cmdk-list .cmdk-item svg').count(),1);
    await page.keyboard.press('Enter');
    assert.ok(await page.locator('#release-preview').isVisible());
    assert.match(await page.locator('#release-preview').innerText(),english?/2\.0\.0 beta 3D is coming soon/:/2\.0\.0 beta 3D 版本即将释出/);
    assert.match(await page.locator('#release-preview').innerText(),english?/no 3D content is downloaded or installed/:/不会下载安装任何 3D 内容/);
    await page.screenshot({path:path.join(output,'theme-release-preview.png'),animations:'disabled'});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({page_errors:errors,exports:exportsSeen,screenshots:output,tutorial_lessons:9},null,2));
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
