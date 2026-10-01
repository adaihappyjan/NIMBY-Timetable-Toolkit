const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/autotrack.js'),'utf8');
test('player avoidance choice reaches backend, invalidates preview and disables in forced mode',async()=>{
  const h=harness();h.$('#at-structure').value='auto';h.$('#at-player-obstacles').value='tunnel';
  h.$('#at-player-obstacles').events.change();assert.equal(h.$('#at-player-radius').disabled,false);
  h.$('#at-player-radius').value='85';await h.$('#at-preview').click();
  assert.equal(h.calls[0].payload.player_obstacle_mode,'tunnel');assert.equal(h.calls[0].payload.player_station_radius_m,85);
  await h.context.window.autotrackResult(h.result,h.calls[0].ctx);
  h.$('#at-player-radius').value='100';h.$('#at-player-radius').events.input();
  assert.equal(h.$('#at-download').disabled,true);
  await h.$('#at-preview').click();h.$('#at-player-obstacles').value='bridge';
  await h.context.window.autotrackResult(h.result,h.calls[1].ctx);
  assert.equal(h.$('#at-download').disabled,true);
  h.$('#at-structure').value='ground';h.$('#at-structure').events.change();
  assert.equal(h.$('#at-player-obstacles').disabled,true);assert.equal(h.$('#at-player-radius').disabled,true);
  await h.$('#at-preview').click();assert.equal(h.calls[2].payload.player_obstacle_mode,'off');
});
function harness(){
  const nodes=new Map(),calls=[];
  function element(){return {value:'',checked:false,disabled:false,textContent:'',files:[],events:{},children:[],
    set id(value){nodes.set('#'+value,this);},
    addEventListener(type,fn){this.events[type]=fn;},replaceChildren(...items){this.children=items;},append(...items){this.children.push(...items);},setAttribute(){},click(){return this.events.click?.();}};}
  function $(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);}
  $('#save-select').value='source.nimbyrails5';$('#at-preset').value='vandry-dessane';$('#at-variant').value='6';$('#at-gap').value='50';$('#at-start').value='0';
  const context=vm.createContext({$,window:{},state:{taskActive:false},viewMeta:{},JSON,Math,Number,String,Error,SVG_NS:'svg',setTimeout,
    toast:()=>{},startTask:async(action,payload,ctx)=>{calls.push({action,payload,ctx});return true;},outputPath:()=> 'new.nimbyrails5',
    api:async()=>({value:{}}),
    document:{querySelector:$,createElement:element,createElementNS:element}});
  vm.runInContext(source,context);
  const result={coordinates:[[0,0],[.01,.01]],levels:[0,0],length_m:1000,nodes:4,bridge_nodes:0,start_m:0,end_m:1000,avoided_intervals:0,warnings:[],fingerprint:'token'};
  return {$,context,calls,result};
}
test('acknowledgement and a fresh matching preview are mandatory',async()=>{
  const h=harness();await h.$('#at-preview').click();await h.context.window.autotrackResult(h.result,h.calls[0].ctx);
  assert.equal(h.$('#at-apply').disabled,true);
  h.$('#at-accept').checked=true;h.$('#at-accept').events.change();assert.equal(h.$('#at-apply').disabled,false);
  await h.$('#at-apply').click();assert.equal(h.calls[1].payload.fingerprint,'token');assert.equal(h.calls[1].payload.apply,true);
  await h.context.window.autotrackResult({...h.result,output_save:'new.nimbyrails5'});
  assert.equal(h.$('#at-apply').disabled,true);assert.equal(h.$('#at-download').disabled,true);
});
test('late results cannot restore a stale preview',async()=>{
  const h=harness();await h.$('#at-preview').click();h.$('#at-gap').value='80';h.$('#at-gap').events.change();
  await h.context.window.autotrackResult(h.result,h.calls[0].ctx);
  assert.equal(h.$('#at-apply').disabled,true);assert.equal(h.$('#at-download').disabled,true);
});
test('save selection changed without an event still invalidates preview',async()=>{
  const h=harness();await h.$('#at-preview').click();h.$('#save-select').value='different.nimbyrails5';
  await h.context.window.autotrackResult(h.result,h.calls[0].ctx);assert.equal(h.$('#at-apply').disabled,true);
});
test('failed operations have persistent visible feedback and disable writing',async()=>{
  const h=harness();await h.$('#at-preview').click();await h.context.window.autotrackResult(h.result,h.calls[0].ctx);
  h.context.window.autotrackFailure('duplicate tracks');assert.equal(h.$('#at-output').textContent,'duplicate tracks');
  assert.equal(h.$('#at-apply').disabled,true);
});

test('catalog is scoped to selected save and station IDs disambiguate names',async()=>{
  const h=harness();h.$('#at-preset').value='auto';h.$('#at-rail-type').value='auto';
  const stations=[{id:'one',name:'Same',lon:1,lat:2},{id:'two',name:'Same',lon:3,lat:4}];
  await h.context.window.autotrackResult({operation:'catalog',save:'source.nimbyrails5',stations,maps:['map'],routes:[],node_ready:true},{catalogSave:'wrong'});
  h.$('#at-from').value='Same — one';h.$('#at-to').value='Same — two';
  await h.$('#at-preview').click();assert.equal(h.calls.length,0);
  await h.context.window.autotrackResult({operation:'catalog',save:'source.nimbyrails5',stations,maps:['map'],routes:[],node_ready:true},{catalogSave:'source.nimbyrails5'});
  await h.$('#at-preview').click();assert.equal(h.calls[0].payload.from_station,'one');assert.equal(h.calls[0].payload.to_station,'two');
});

test('first-open tutorial can be completed and reopened without starting writes',async()=>{
  const h=harness();await h.$('[data-view="autotrack"]').click();
  assert.equal(h.$('#at-tutorial').hidden,false);
  for(let i=0;i<4;i++)await h.$('#at-tutorial-next').click();
  assert.equal(h.$('#at-tutorial').hidden,true);
  await h.$('[data-view="autotrack"]').click();assert.equal(h.$('#at-tutorial').hidden,true);
  await h.$('#at-help').click();assert.equal(h.$('#at-tutorial').hidden,false);
  assert.ok(h.calls.every(c=>c.payload.operation==='catalog'));
});

async function autoHarness(){
  const h=harness();h.$('#at-preset').value='auto';h.$('#at-rail-type').value='auto';
  await h.context.window.autotrackResult({operation:'catalog',stations:[],maps:['map'],routes:[],node_ready:true},{catalogSave:'source.nimbyrails5'});
  h.$('#at-from').value='30,20';h.$('#at-to').value='30.02,20';return h;
}
test('via entries are ordered, movable, removable and use whole-leg mileage',async()=>{
  const h=await autoHarness();await h.$('#at-add-via').click();h.$('#at-via-0').value='30.005,20';
  await h.$('#at-add-via').click();h.$('#at-via-1').value='30.01,20';h.$('#at-start').value='123';
  await h.$('#at-via-list').children[1].children[1].click(); // move second up
  await h.$('#at-preview').click();
  assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0].payload.via)),[{coord:[30.01,20]},{coord:[30.005,20]}]);
  assert.equal(h.calls[0].payload.start_m,0);
  await h.$('#at-via-list').children[0].children[3].click(); // remove first
  await h.$('#at-preview').click();assert.equal(h.calls[1].payload.via.length,1);
});
test('all-failed preview cannot write even when acknowledged; deleting station invalidates it',async()=>{
  const h=await autoHarness();await h.$('#at-add-via').click();h.$('#at-via-0').value='bad input';
  await h.$('#at-preview').click();
  const result={...h.result,multi_station:true,can_apply:false,successful_legs:0,failed_legs:2,
    waypoints:[{index:0,label:'A',coord:[30,20]},{index:1,label:'B'},{index:2,label:'C',coord:[30.02,20]}],
    legs:[{index:0,from_index:0,to_index:1,from_name:'A',to_name:'B',status:'error',error:'站点无效'}]};
  await h.context.window.autotrackResult(result,h.calls[0].ctx);
  h.$('#at-accept').checked=true;h.$('#at-accept').events.change();assert.equal(h.$('#at-apply').disabled,true);
  await h.$('#at-apply').click();assert.equal(h.calls.length,1);
  await h.$('#at-leg-results').children[1].children[3].click(); // delete B
  assert.equal(h.$('#at-download').disabled,true);
  await h.$('#at-preview').click();assert.equal(h.calls[1].payload.via.length,0);
});

test('mixed preview needs separate consent and writes only the fingerprinted plan',async()=>{
  const h=await autoHarness();await h.$('#at-preview').click();
  const result={...h.result,multi_station:true,can_apply:true,requires_partial_confirmation:true,successful_legs:1,failed_legs:1,
    waypoints:[{index:0,label:'A',coord:[30,20]},{index:1,label:'B',coord:[30.01,20]},{index:2,label:'C',coord:[30.02,20]}],
    legs:[{index:0,from_index:0,to_index:1,from_name:'A',to_name:'B',status:'ok',preview:{...h.result,routing:{}}},
      {index:1,from_index:1,to_index:2,from_name:'B',to_name:'C',status:'error',error:'断线'}],
    skipped_legs:[{index:1,from_name:'B',to_name:'C',error:'断线'}]};
  await h.context.window.autotrackResult(result,h.calls[0].ctx);
  assert.equal(h.$('#at-partial-wrap').hidden,false);
  h.$('#at-accept').checked=true;h.$('#at-accept').events.change();
  assert.equal(h.$('#at-apply').disabled,true);
  await h.$('#at-apply').click();assert.equal(h.calls.length,1);
  h.$('#at-partial-accept').checked=true;h.$('#at-partial-accept').events.change();
  assert.equal(h.$('#at-apply').disabled,false);
  await h.$('#at-apply').click();assert.equal(h.calls[1].payload.allow_partial,true);
  assert.equal(h.calls[1].payload.fingerprint,'token');
  await h.context.window.autotrackResult({...result,partial_output:true,output_save:'new.nimbyrails5'});
  assert.match(h.$('#at-output').textContent,/跳过 1 个区间.*B → C/);
  assert.equal(h.$('#at-partial-accept').checked,false);
});

test('editing geometry clears partial consent and output permission',async()=>{
  const h=harness();await h.$('#at-preview').click();
  await h.context.window.autotrackResult({...h.result,requires_partial_confirmation:true,successful_legs:1,can_apply:true},h.calls[0].ctx);
  h.$('#at-partial-accept').checked=true;
  h.$('#at-gap').value='80';h.$('#at-gap').events.change();
  assert.equal(h.$('#at-partial-accept').checked,false);
  assert.equal(h.$('#at-partial-wrap').hidden,true);
  assert.equal(h.$('#at-apply').disabled,true);
});
test('late result after waypoint edit cannot restore write permission',async()=>{
  const h=await autoHarness();await h.$('#at-add-via').click();h.$('#at-via-0').value='30.005,20';
  await h.$('#at-preview').click();h.$('#at-via-0').value='30.008,20';h.$('#at-via-0').events.input();
  await h.context.window.autotrackResult(h.result,h.calls[0].ctx);assert.equal(h.$('#at-apply').disabled,true);
});

async function discoveryHarness(count=2){
  const h=await autoHarness();
  const candidates=Array.from({length:count},(_,i)=>({id:'mid'+i,name:'同名候选站',lon:30.001+i*.001,lat:20,along_m:100+i*100,distance_m:30,ambiguous:false}));
  const stations=[{id:'a',name:'A'},{id:'z',name:'Z'},...candidates];
  await h.context.window.autotrackResult({operation:'catalog',stations,maps:['map'],routes:[],node_ready:true},{catalogSave:'source.nimbyrails5'});
  h.$('#at-from').value='A — a';h.$('#at-to').value='Z — z';
  await h.$('#at-discover').click();
  const result={operation:'discover',candidates,source_sha256:'snapshot',warnings:['请核对平行线']};
  return {...h,discoveryResult:result};
}

test('discovery is read-only, requires selection and replacement consent, then fills ordered IDs',async()=>{
  const h=await discoveryHarness();
  assert.equal(h.calls[0].payload.operation,'discover');assert.equal(h.calls[0].payload.apply,undefined);
  await h.context.window.autotrackResult(h.discoveryResult,h.calls[0].ctx);
  assert.equal(h.$('#at-discovery').hidden,false);assert.equal(h.$('#at-use-discovery').disabled,true);
  for(const row of h.$('#at-discovery-list').children){assert.equal(row.children[0].checked,false);row.children[0].checked=true;row.children[0].events.change();}
  assert.equal(h.$('#at-use-discovery').disabled,true);
  h.$('#at-discovery-replace').checked=true;h.$('#at-discovery-replace').events.change();
  assert.equal(h.$('#at-use-discovery').disabled,false);
  await h.$('#at-use-discovery').click();
  assert.equal(h.$('#at-via-0').value,'同名候选站 — mid0');assert.equal(h.$('#at-via-1').value,'同名候选站 — mid1');
  assert.equal(h.$('#at-apply').disabled,true);
  await h.$('#at-preview').click();
  assert.equal(h.calls[1].payload.discovery_source_sha256,'snapshot');
  assert.deepEqual(JSON.parse(JSON.stringify(h.calls[1].payload.via)),[{station:'mid0'},{station:'mid1'}]);
});

test('discovery results and chosen candidates cannot survive stale parameters',async()=>{
  const h=await discoveryHarness();h.$('#at-to').value='A — a';
  await h.context.window.autotrackResult(h.discoveryResult,h.calls[0].ctx);
  assert.equal(h.$('#at-discovery').hidden,true);assert.equal(h.$('#at-use-discovery').disabled,true);
});

test('discovery rejects coordinates, too many selected stations and empty selection',async()=>{
  const coord=await autoHarness();await coord.$('#at-discover').click();assert.equal(coord.calls.length,0);
  const h=await discoveryHarness(39);await h.context.window.autotrackResult(h.discoveryResult,h.calls[0].ctx);
  h.$('#at-discovery-replace').checked=true;h.$('#at-discovery-replace').events.change();
  assert.equal(h.$('#at-use-discovery').disabled,true);
  for(const row of h.$('#at-discovery-list').children){row.children[0].checked=true;row.children[0].events.change();}
  assert.equal(h.$('#at-use-discovery').disabled,true);
  await h.$('#at-use-discovery').click();assert.equal(h.$('#at-via-list').children.length,0);
});

test('nineteen intermediate stations can be selected for a twenty-one station plan',async()=>{
  const h=await discoveryHarness(19);await h.context.window.autotrackResult(h.discoveryResult,h.calls[0].ctx);
  for(const row of h.$('#at-discovery-list').children){row.children[0].checked=true;row.children[0].events.change();}
  h.$('#at-discovery-replace').checked=true;h.$('#at-discovery-replace').events.change();
  assert.equal(h.$('#at-use-discovery').disabled,false);
  await h.$('#at-use-discovery').click();
  assert.equal(h.$('#at-via-list').children.length,19);
  await h.$('#at-preview').click();assert.equal(h.calls[1].payload.via.length,19);
});
