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
