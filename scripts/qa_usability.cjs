// Isolated UI acceptance: mock APIs only; never opens or modifies a game save.
// NODE_PATH must provide Playwright. Outputs are written only to the given QA folder.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../web'), output=path.resolve(process.argv[2]);
fs.mkdirSync(output,{recursive:true});
const exportsSeen=[];
const bootstrap={ok:true,app_version:fs.readFileSync(path.join(root,'../VERSION'),'utf8').trim(),files:{saves:[],exports:[]},settings:{enabled:false,days:14,keep:5,auto_check_updates:false},
  cleanup:{completed_copy_count:1,protected_copy_count:1,candidate_count:0,candidate_bytes:0,keep:5,days:14,targets:[],copies:[{name:'QA_Workspace_20260101_000000.nimbyrails5',pinned:true}]},capabilities:[],map_export_dir:output};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/')){
    let body='';for await(const part of req)body+=part;const payload=body?JSON.parse(body):{};
    let result={ok:true,value:{},accounting:[],packages:[],tasks:[]};
    if(url.pathname==='/api/bootstrap')result=bootstrap;
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
    const upstream=await fetch(new URL(req.url,process.env.QA_STATIC_ORIGIN));
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
    assert.match(await page.locator('#map-render-status').innerText(),/已绘制.*铁路总览/);
    await page.selectOption('#map-metro-theme','metro');
    await page.click('#export-map-svg');await page.click('#export-map-json');
    await page.waitForFunction(()=>document.querySelector('#map-export-status').textContent.includes('.json'));
    assert.equal(exportsSeen.length,2);
    const json=JSON.parse(fs.readFileSync(exportsSeen.find(e=>e.format==='json').path));
    assert.equal(json.drawing.style,'metro');assert.equal(json.schematic_layout.coordinate_space,'display-only');assert.equal(json.stations.c.lon,2);
    const svg=fs.readFileSync(exportsSeen.find(e=>e.format==='svg').path,'utf8');assert.ok(svg.includes('地铁线网图'));
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
      for(const region of ['TTC','Montreal']){
        if(process.env.QA_DETAILS)await page.evaluate(()=>{
          if(window.qaOriginalJoin)return;window.qaOriginalJoin=metroJoinCorridors;
          metroJoinCorridors=(...args)=>{window.qaRoutes=args[0];const result=window.qaOriginalJoin(...args);window.qaPaths=result;return result;};
        });
        const regionLines=objects.filter(o=>o.class==='Line'&&o.stops?.length>1&&(region==='TTC'?o.name.includes('TTC'):/STM|REM/.test(o.name))).map(o=>({id:o.id,name:o.name,code:o.code,color:o.color,stops:o.stops.map(s=>s.station_id),stop_count:o.stops.length}));
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
            const match=/^(Union|King|Queen|TMU|Summerhill|St\. Clair|Avenue|Spadina|Museum|Bay|Canora|Ville-de-Mont-Royal)$/;
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
    await page.getByText('副本保留管理 · 勾选后永久保留').click();
    assert.equal(await page.locator('[data-protect-copy]').isChecked(),true);
    await page.locator('#view-cleanup').screenshot({path:path.join(output,'cleanup-guidance.png')});
    await page.evaluate(()=>toast(updateFailureMessage({rollback_complete:false,backup_dir:'QA backup',error:'测试恢复失败'}),true));
    assert.ok((await page.locator('#error-help').innerText()).includes('展开诊断信息'));
    await page.click('#error-help summary');
    assert.ok((await page.locator('#error-help pre').innerText()).includes('恢复不完整'));
    await page.click('#error-help button');
    await page.evaluate(()=>switchView('learn'));
    assert.equal(await page.locator('[data-lesson]').count(),9);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({page_errors:errors,exports:exportsSeen,screenshots:output,tutorial_lessons:9},null,2));
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
