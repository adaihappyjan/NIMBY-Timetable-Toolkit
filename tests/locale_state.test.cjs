const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/locale.js'),'utf8');
function harness({active=false,hidden=true,accept=true,fail=false}={}){
  const calls=[],alerts=[],reloads=[];let ready,changed,confirms=0;
  const select={value:'',addEventListener:(ev,fn)=>changed=fn};
  const c={window:{},state:{taskActive:active},URL,
    document:{documentElement:{lang:'en'},addEventListener:(ev,fn)=>ready=fn,getElementById:id=>id==='language-select'?select:{hidden}},
    alert:s=>alerts.push(s),confirm:()=>{confirms++;return accept;},
    fetch:async(url,opts)=>{calls.push({url,opts});return {ok:!fail,json:async()=>({ok:!fail,error:fail?'Write failed':undefined})};},
    location:{href:'http://127.0.0.1:9000/?lang=en',replace:s=>reloads.push(s)}};
  vm.runInNewContext(source,c);ready();select.value='zh-CN';
  return {change:()=>changed(),calls,alerts,reloads,select,get confirms(){return confirms;}};
}
test('language change requires confirmation and persists before reloading',async()=>{
  const h=harness();await h.change();assert.equal(h.confirms,1);
  assert.deepEqual(JSON.parse(h.calls[0].opts.body),{language:'zh-CN'});
  assert.match(h.reloads[0],/lang=zh-CN/);assert.equal(h.select.value,'en');
});
test('declining language change has no side effects',async()=>{
  const h=harness({accept:false});await h.change();assert.equal(h.calls.length,0);assert.equal(h.reloads.length,0);
});
test('running task blocks switching even with hidden dock',async()=>{
  const h=harness({active:true});await h.change();assert.equal(h.confirms,0);assert.equal(h.calls.length,0);assert.equal(h.alerts.length,1);
});
test('failed settings write never reloads',async()=>{
  const h=harness({fail:true});await h.change();assert.equal(h.reloads.length,0);assert.deepEqual(h.alerts,['Write failed']);
});
