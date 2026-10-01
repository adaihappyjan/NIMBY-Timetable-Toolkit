// Real browser UI, isolated fake APIs. No game files or user settings touched.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../web');
const file=(name,stamp,extra={})=>({name,path:'C:/QA/'+name,size:100,modified_ns:String(stamp),stable:true,...extra});
let files={saves:[file('City.nimbyrails5',1)],exports:[file('City Timetable Export 20280101T000000Z.json',1)]};
let task=null,request=null;const starts=[];
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://local');
  if(url.pathname.startsWith('/api/')){
    let body='';for await(const chunk of req)body+=chunk;const payload=body?JSON.parse(body):{};
    let result={ok:true,value:{},accounting:[],mod_packages:[],history:[]};
    if(url.pathname==='/api/bootstrap')result={ok:true,files,settings:{enabled:false,days:14,keep:5,auto_check_updates:false,follow_latest:true},cleanup:{groups:[],targets:[],copies:[]},capabilities:[]};
    if(url.pathname==='/api/files')result={ok:true,files};
    if(url.pathname==='/api/task/start'){starts.push(payload);request=payload;task=payload.action;}
    if(url.pathname==='/api/task/status')result={ok:true,state:'complete',action:task,result:{preview:true,station_count:2,changed_count:1,skipped_count:0,unresolved_count:1,fingerprint:'a'.repeat(64),changes:[{id:'0x20000020f0001',old_name:'未命名站',new_name:'Gogama'}],unresolved:[{id:'0x2000002100001',reason:'导出没有名称'}]}};
    res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(result));
  }
  const pathname=url.pathname==='/'?'/index.html':url.pathname;
  const target=path.resolve(root,'.'+pathname);
  if(!target.startsWith(root+path.sep)||!fs.existsSync(target)){res.writeHead(404);return res.end();}
  res.writeHead(200,{'Content-Type':({'.js':'text/javascript','.html':'text/html','.css':'text/css'})[path.extname(target)]||'application/octet-stream'});res.end(fs.readFileSync(target));
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.waitForFunction(()=>window.checkLiveFiles&&state.bootstrap);
    await page.evaluate(()=>window.checkLiveFiles());
    files={saves:[file('Other.nimbyrails5',9),file('City_Names_20260930_190000.nimbyrails5',8,{tool_generated:true}),file('City Autosave 1.nimbyrails5',3,{stable:false}),file('City.nimbyrails5',1)],exports:files.exports};
    await page.evaluate(()=>window.checkLiveFiles());assert.equal(await page.locator('#save-select').inputValue(),'C:/QA/City.nimbyrails5');
    files.saves[2].stable=true;
    await page.evaluate(()=>window.checkLiveFiles());assert.equal(await page.locator('#save-select').inputValue(),'C:/QA/City Autosave 1.nimbyrails5');
    // Same filename rewritten: update notice + invalidation, not just filename comparison.
    await page.evaluate(()=>{state.analysis={old:true};});files.saves[2].modified_ns='4';
    await page.evaluate(()=>window.checkLiveFiles());assert.equal(await page.evaluate(()=>state.analysis),null);
    // A running task pins selection. Once idle, metadata can be followed.
    await page.evaluate(()=>{state.taskActive=true;});files.saves.unshift(file('City Autosave 2.nimbyrails5',5));
    await page.evaluate(()=>window.checkLiveFiles());assert.equal(await page.locator('#save-select').inputValue(),'C:/QA/City Autosave 1.nimbyrails5');
    await page.evaluate(()=>{state.taskActive=false;});await page.evaluate(()=>window.checkLiveFiles());
    assert.equal(await page.locator('#save-select').inputValue(),'C:/QA/City Autosave 2.nimbyrails5');
    // Explicit selection pins old save and automatic list refresh keeps it.
    await page.selectOption('#save-select','C:/QA/City.nimbyrails5');assert.equal(await page.locator('#follow-latest').isChecked(),false);
    await page.evaluate(()=>window.checkLiveFiles());assert.equal(await page.locator('#save-select').inputValue(),'C:/QA/City.nimbyrails5');
    await page.check('#follow-latest');await page.waitForFunction(()=>document.querySelector('#save-select').value.includes('Autosave 2'));
    // Preview stays immutable while a new export/save appears.
    await page.click('#stationname-preview');await page.waitForFunction(()=>!document.querySelector('#stationname-write').disabled);
    assert.equal(starts.at(-1).preview,true);assert.match(await page.locator('#stationname-result').innerText(),/Gogama/);
    files.saves.unshift(file('City Autosave 3.nimbyrails5',6));await page.evaluate(()=>window.checkLiveFiles());
    assert.equal(await page.locator('#save-select').inputValue(),'C:/QA/City Autosave 2.nimbyrails5');assert.equal(await page.locator('#live-files-apply').isVisible(),true);
    await page.fill('#stationname-pairs','0x2000002100001=Westree');assert.equal(await page.locator('#stationname-write').isDisabled(),true);
    page.once('dialog',d=>d.accept());await page.click('#live-files-apply');
    assert.equal(await page.locator('#save-select').inputValue(),'C:/QA/City Autosave 3.nimbyrails5');
    assert.equal(await page.locator('#stationname-pairs').inputValue(),'0x2000002100001=Westree');
    assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks:['stable files','project isolation','skip generated copies','same-path overwrite','task pin','manual pin','preview pin','manual name invalidation','explicit application preserves text'],page_errors:errors},null,2));
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
