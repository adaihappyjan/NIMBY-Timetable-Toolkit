// Exercise the actual shipped handlers with a minimal DOM, without a browser
// dependency or any save writes. The interactive acceptance covers the real UI.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const ws = fs.readFileSync(path.join(__dirname, '../web/workspace.js'), 'utf8');
function between(source, begin, end) {
  const a = source.indexOf(begin), b = source.indexOf(end, a + begin.length);
  assert.ok(a >= 0 && b > a, `source anchors: ${begin}`);
  return source.slice(a, b);
}
function harness() {
  const nodes = new Map(), messages = [];
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {value:'', disabled:false, hidden:false,
      style:{}, textContent:'', innerHTML:'', focus(){this.focused=true;}});
    return nodes.get(id);
  };
  $('#save-select').value = 'save-A'; $('#export-select').value = 'export-A';
  const c = vm.createContext({$, state:{}, window:{}, console, JSON, Set,
    clearTimeout, toast:m=>messages.push(m), confirm:()=>true,
    ensureTicker:()=>null, fallbackLoop:()=>{}, pollOnce:()=>{},
    WRITE_ACTIONS:new Set(), messages, nodes});
  return c;
}

test('map JSON exports only selected lines and referenced original stations', () => {
  const c=harness();
  c.state.bootstrap={app_version:'1.8.0'};
  c.state.network={stations:{a:{name:'起点',lon:10,lat:20},b:{name:'终点',lon:11,lat:21},c:{name:'未选'}}};
  c.selectedMapLines=()=>[{id:'L1',stops:['a','b','missing']}];
  c.mapStyle=()=>'schematic'; c.mapOpts=()=>({W:1400,H:940});
  vm.runInContext(between(app,'function buildMapJsonData()', 'async function exportMapJson()'),c);
  const result=c.buildMapJsonData();
  assert.deepEqual(Object.keys(result.stations),['a','b']);
  assert.equal(result.stations.a.lon,10);
  assert.equal(result.schema,'nimby-toolkit-line-map.v1');
  assert.equal(result.missing_station_ids[0],'missing');
  assert.equal(result.drawing.style,'schematic');
  c.selectedMapLines=()=>[];
  assert.throws(()=>c.buildMapJsonData(),/勾选/);
});

test('map JSON export reports the actual path and errors without fake success', async () => {
  const c=harness();c.timestamp=()=>'test'; c.buildMapJsonData=()=>({schema:'test'});
  vm.runInContext(between(app,'async function exportMapJson()', 'async function saveMapExportFolder'),c);
  c.api=async(route,request)=>{assert.equal(route,'/api/map/export');assert.equal(JSON.parse(request.body).format,'json');return {path:'D:/maps/test.json'};};
  await c.exportMapJson(); assert.match(c.$('#map-export-status').textContent,/D:\/maps\/test.json/);
  c.api=async()=>{throw Error('permission denied');};
  await c.exportMapJson();assert.match(c.messages.at(-1),/导出失败.*permission denied/);
});
test('double click keeps the original task and context alive', async () => {
  const c = harness(); let resolve, requests = 0, polls = 0;
  c.api = () => {requests++; return new Promise(r=>resolve=r);};
  c.pollOnce = () => polls++;
  vm.runInContext(between(app,'function finishTask()', 'const WRITE_ACTIONS') +
    between(app,'async function startTask(', 'async function pollOnce()'), c);
  const first = c.startTask('save-health', {save:'A'}, {key:'first'});
  assert.equal(await c.startTask('analyze', {save:'B'}, {key:'second'}), false);
  assert.equal(requests, 1);
  assert.equal(c.state.taskActive, true);
  assert.equal(c.state.taskContext.key, 'first');
  assert.equal(c.state.taskAction, 'save-health');
  resolve({ok:true}); assert.equal(await first, true); assert.equal(polls, 1);
});
test('start failure cleans up the task dock and permits retry', async () => {
  const c = harness(); c.api = async()=>{throw Error('test failure');};
  vm.runInContext(between(app,'function finishTask()', 'const WRITE_ACTIONS') +
    between(app,'async function startTask(', 'async function pollOnce()'), c);
  assert.equal(await c.startTask('save-health', {}), false);
  assert.equal(c.state.taskActive, false);
  assert.equal(c.$('#task-dock').hidden, true);
});
function workspaceHarness() {
  const c = harness(); c.W = {revision:0, preview:null, results:{}};
  c.clone = x=>JSON.parse(JSON.stringify(x)); c.status=m=>c.messages.push(m);
  c.guard = fn=>async()=>{try{return await fn();}catch(e){c.messages.push(e.message);}};
  c.batchRequest=()=>({selected:['OT4'],preset:{service_start:c.$('#ws-start').value}});
  c.outputPath=()=> 'unused-output'; c.esc=String; c.clock=String; c.opruleDayText=String; c.table=()=>'';
  c.started=[];
  c.startTask=(action,payload,context)=>{c.started.push({action,payload,context});return true;};
  const handlers = ws.split('\n').filter(s=>s.includes("$('#ws-preview').onclick=")||s.includes("$('#ws-apply').onclick=")).join('\n');
  vm.runInContext(between(ws,'  function run(', '  function requireCatalog') +
    between(ws,'  function invalidate()', "  section.addEventListener('change'") + handlers +
    between(ws,'  window.workspaceResult=', '  async function acceptance('), c);
  return c;
}
const result = {operation:'batch',preview:true,preview_hash:'hash',changes:[]};
function tileCacheHarness() {
  const c = harness();
  for (const node of c.nodes.values()) node.addEventListener = () => {};
  const original = c.$;
  c.$ = id => {
    const node = original(id);
    node.listeners ||= {};
    node.addEventListener = (event, fn) => node.listeners[event] = fn;
    node.setAttribute = () => {};
    node.querySelectorAll = () => ['start','stop','prune','clear','save','game-start','refresh'].map(k=>c.$('#tc-'+k));
    return node;
  };
  c.viewMeta = {}; c.formatBytes = String;
  c.navigator = {clipboard:{writeText:async()=>{}}};
  c.api = async()=>({cache:c.cache});
  c.cache = {running:true,config:{directory:'cache',port:58743,max_mb:2048,max_age_days:90,offline:false,autostart:false},urls:{standard:'http://127.0.0.1:58743/tiles/standard/{z}/{x}/{y}.png'},pending:2,active_downloads:1,coalesced:3,queue_full:4,wait_timeouts:5,average_fetch_ms:100,average_wait_ms:200,game_start:{enabled:true,watcher_running:true}};
  c.$('#tc-style').value = 'standard';
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/tilecache.js'),'utf8'),c);
  return c;
}
test('cache panel shows independent queue metrics and game startup state', async()=>{
  const c=tileCacheHarness(); await c.window.refreshTileCache();
  assert.match(c.$('#tc-performance').textContent,/队列满 4/);
  assert.match(c.$('#tc-performance').textContent,/等待超时 5/);
  assert.equal(c.$('#tc-game-start').textContent,'关闭随游戏启动');
  assert.equal(c.$('#tc-start').disabled,true);
});
test('cache refresh preserves unsaved settings', async()=>{
  const c=tileCacheHarness(); await c.window.refreshTileCache();
  c.$('#tc-max').value=4096; c.$('#tc-max').listeners.input();
  await c.window.refreshTileCache();
  assert.equal(c.$('#tc-max').value,4096);
});
test('cache duplicate clicks cannot enqueue two actions', async()=>{
  const c=tileCacheHarness(); let finish, calls=0;
  c.api=()=>{calls++;return new Promise(r=>finish=r);};
  const pending=c.$('#tc-start').onclick();
  await c.$('#tc-start').onclick();
  assert.equal(calls,1); finish({cache:c.cache}); await pending;
});
test('editing during preview discards old response and keeps write disabled', async()=>{
  const c=workspaceHarness(); c.$('#ws-start').value='06:00';
  await c.$('#ws-preview').onclick(); const context=c.started[0].context;
  c.$('#ws-start').value='07:00'; c.invalidate();
  await c.window.workspaceResult(result,context);
  assert.equal(c.W.preview,null); assert.equal(c.$('#ws-apply').disabled,true);
  await c.$('#ws-apply').onclick(); assert.equal(c.started.length,1);
});
test('switching save discards preview even without a DOM change event', async()=>{
  const c=workspaceHarness(); await c.$('#ws-preview').onclick();
  c.$('#save-select').value='save-B';
  await c.window.workspaceResult(result,c.started[0].context);
  assert.equal(c.$('#ws-apply').disabled,true);
});
test('accepted preview uses its immutable payload, and later edits require preview', async()=>{
  const c=workspaceHarness(); c.$('#ws-start').value='06:00';
  await c.$('#ws-preview').onclick(); await c.window.workspaceResult(result,c.started[0].context);
  assert.equal(c.$('#ws-apply').disabled,false);
  await c.$('#ws-apply').onclick(); assert.equal(c.started[1].payload.preset.service_start,'06:00');
  c.$('#ws-start').value='07:00'; // catch even a programmatic change without events
  await c.$('#ws-apply').onclick(); assert.equal(c.started.length,2);
  assert.equal(c.$('#ws-apply').disabled,true);
});
test('second preview click during active task cannot replace preview context', async()=>{
  const c=workspaceHarness(); await c.$('#ws-preview').onclick();
  const revision=c.W.revision; c.state.taskActive=true;
  await c.$('#ws-preview').onclick();
  assert.equal(c.W.revision,revision); assert.equal(c.started.length,1);
});
test('binder guides basic-health users to deep check and rejects another source', ()=>{
  const c=harness(); c.switchView=name=>c.view=name; c.renderBinderFleets=()=>c.loaded=true;
  vm.runInContext(between(app,'function binderAnalysisCurrent()', 'function renderBinderFleets()'),c);
  c.state.saveHealth={health:{health_score:100}}; c.loadBinderFleets();
  assert.equal(c.view,'dashboard'); assert.equal(c.$('#adv-json-box').open,true);
  assert.equal(c.$('#deep-scan-button').focused,true);
  c.state.analysis={save:'save-A',export:'export-A'}; c.loadBinderFleets(); assert.equal(c.loaded,true);
  c.$('#export-select').value='export-B'; assert.equal(c.binderAnalysisCurrent(),false);
  c.$('#export-select').value='export-A'; c.$('#save-select').value='save-B';
  assert.equal(c.binderAnalysisCurrent(),false);
});
