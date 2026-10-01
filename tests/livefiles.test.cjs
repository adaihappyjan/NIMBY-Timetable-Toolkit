const {test}=require('node:test');
const assert=require('node:assert/strict');
const {choose,project,signature}=require('../web/livefiles.js');
const file=(name,extra={})=>({path:'C:/saves/'+name,name,size:1,modified_ns:'1',stable:true,...extra});
test('same-project newest excludes toolkit output and other projects',()=>{
  const files={saves:[file('Other.nimbyrails5'),file('City_Names_20260930_175900.nimbyrails5',{tool_generated:true}),file('City Autosave 4.nimbyrails5')],exports:[file('Other Timetable Export 20280101T000000Z.json'),file('City Timetable Export 20280101T000000Z.json')]};
  assert.equal(choose(files,'C:/saves/City.nimbyrails5').save.name,'City Autosave 4.nimbyrails5');
  assert.equal(choose(files,'C:/saves/City.nimbyrails5').export.name,'City Timetable Export 20280101T000000Z.json');
});
test('never select old file while newest is being written',()=>{
  const files={saves:[file('City Autosave 4.nimbyrails5',{stable:false}),file('City.nimbyrails5')],exports:[]};
  assert.equal(choose(files,'City.nimbyrails5').save,null);
});
test('same-path overwrite detectable and names normalize',()=>{
  assert.notEqual(signature(file('a',{modified_ns:'123'})),signature(file('a',{modified_ns:'124'})));
  assert.equal(project('C:\\x\\City Autosave 4.nimbyrails5'),'city');
  assert.equal(project('C:\\x\\City_Names_20260930_175900.nimbyrails5'),'city');
});
