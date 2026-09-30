const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/autotrack.js'),'utf8');
function harness(){
  const nodes=new Map(),calls=[];
  function $(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:false,disabled:false,textContent:'',files:[],events:{},
    addEventListener(type,fn){this.events[type]=fn;},replaceChildren(){},append(){},setAttribute(){},click(){return this.events.click?.();}});return nodes.get(id);}
  $('#save-select').value='source.nimbyrails5';$('#at-preset').value='vandry-dessane';$('#at-variant').value='6';$('#at-gap').value='50';$('#at-start').value='0';
  const context=vm.createContext({$,window:{},state:{taskActive:false},viewMeta:{},JSON,Math,Number,String,Error,SVG_NS:'svg',setTimeout,
    toast:()=>{},startTask:async(action,payload,ctx)=>{calls.push({action,payload,ctx});return true;},outputPath:()=> 'new.nimbyrails5',
    api:async()=>({value:{}}),
    document:{querySelector:$,createElement:()=>({}),createElementNS:()=>({setAttribute(){},textContent:''})}});
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
