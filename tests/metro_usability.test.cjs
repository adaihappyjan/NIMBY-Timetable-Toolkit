const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const app=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const metro=fs.readFileSync(path.join(__dirname,'../web/metro.js'),'utf8')+fs.readFileSync(path.join(__dirname,'../web/metro-poster.js'),'utf8');
function between(start,end){const a=app.indexOf(start),b=app.indexOf(end,a+start.length);assert.ok(a>=0&&b>a);return app.slice(a,b);}
function element(tag,attrs={}){return {tag,attrs:{...attrs},children:[],setAttribute(k,v){this.attrs[k]=v;},appendChild(e){this.children.push(e);},textContent:'',innerHTML:''};}
function harness(options={}){
  const canvas=element('div');
  const c=vm.createContext({console,Math,Set,Map,JSON,Number,String,state:{},SVG_NS:'http://www.w3.org/2000/svg',
    $:selector=>selector==='#map-canvas'?canvas:{checked:true,value:options[selector]},svgEl:element,
    mapOpts:()=>({width:1000,height:700,fontSize:12,lineWidth:6,dotScale:1,gap:60}),canvas});
  vm.runInContext(between('function lineColor(', 'function secToClock(')+
    between('function octilinearize(', 'function mapStyle()')+metro,c);
  return c;
}
const stations={a:{name:'起点',lon:-73.6,lat:45.5},b:{name:'换乘',lon:-73.58,lat:45.51},c:{name:'终点',lon:-73.55,lat:45.52},d:{name:'支线',lon:-73.57,lat:45.48}};
const lines=[{id:'1',name:'红线',color:'ff3333ee',stops:['a','b','c']},{id:'2',name:'蓝线',color:'ffee8833',stops:['d','b','c']}];
test('REM branches are one display network, without linking branch tips or false transfers',()=>{
  const c=harness(),source=[{...lines[0],name:'REMA1/A4',code:'REM'},{...lines[1],name:'REM A1-A3',code:'REM'}],before=JSON.stringify(source);
  const grouped=c.metroDisplayLines(source),g=c.metroTopology(grouped,stations);
  assert.equal(grouped.length,1);assert.equal(grouped[0].routes.length,2);
  assert.equal(g.edges.length,3);assert.ok([...g.nodes.values()].every(n=>n.lines.size===1));
  assert.ok(!g.edges.some(e=>[e.a,e.b].includes('a')&&[e.a,e.b].includes('d')));
  c.drawMetroDiagram(source,stations);
  const group=c.state.mapSvg.children.find(n=>n.tag==='g');
  assert.equal(group.children.filter(n=>n.attrs['data-transfer']==='true').length,0);
  assert.equal(c.state.metroLayout.display_lines.length,1);
  assert.equal(c.metroDisplayLines(source,false).length,2);assert.equal(JSON.stringify(source),before);
});
test('same-colour independent routes remain distinct and genuine interchange remains',()=>{
  const c=harness(),source=[{...lines[0],name:'REMA1/A4'},{...lines[1],name:'STM Green',color:lines[0].color}];
  const grouped=c.metroDisplayLines(source),g=c.metroTopology(grouped,stations);
  assert.equal(grouped.length,2);assert.equal(g.nodes.get('b').lines.size,2);
});
test('generic branch families and manual overrides work without any REM names',()=>{
  const c=harness();
  for(const names of [['Airport branch A','Airport branch B'],['Line 7A','Line 7B'],['Airport (North)','Airport (South)']]){
    const source=lines.map((l,i)=>({...l,name:names[i]}));
    assert.equal(c.metroDisplayLines(source).length,1,names.join(','));
    assert.equal(c.metroDisplayLines(source,true,{'1':'!independent'}).length,2);
  }
  const source=[{...lines[0],name:'East'},{...lines[1],name:'West'}];
  const grouped=c.metroDisplayLines(source,true,{'1':'Airport','2':'Airport'});
  assert.equal(grouped.length,1);assert.equal(grouped[0].group_method,'manual');
  assert.equal(grouped[0].name,'Airport');
  assert.equal(c.metroDisplayLines(source,false,{'1':'Airport','2':'Airport'}).length,2);
});
test('common origin alone is not a branch; common trunk of same-colour branches is deduplicated',()=>{
  const c=harness(),source=[{id:'x',name:'North',color:'ff00ff00',stops:['a','b','c','d']},{id:'y',name:'Airport',color:'ff00ff00',stops:['a','b','c','e']}];
  assert.equal(c.metroDisplayLines(source).length,1);
  source[1].stops=['a','f','e'];assert.equal(c.metroDisplayLines(source).length,2);
  source[1].stops=['a','b','c','e'];source[1].color='ff0000ff';assert.equal(c.metroDisplayLines(source).length,2);
});
test('numbered independent lines do not lose their route number during family detection',()=>{
  const c=harness();
  for(const names of [['STM L1','STM L2'],['Line1','Line2'],['Route A1','Route A2']]){
    const source=lines.map((l,i)=>({...l,name:names[i],color:lines[0].color}));
    assert.equal(c.metroDisplayLines(source).length,2);
  }
});
test('regular routing cannot emit tiny corrective legs in any octant',()=>{
  const c=harness();
  for(const x of [-300,-100,-30,0,30,100,300])for(const y of [-300,-100,-22,-4,0,4,22,100,300]){
    if(!x&&!y)continue;
    const route=c.metroRouteParts([{ids:['a','b'],lines:[0]}],{a:{x:0,y:0},b:{x,y}},60)[0];
    assert.ok(route.length<=3);
    if(route.length>2)for(let i=1;i<route.length;i++)assert.ok(Math.hypot(route[i].x-route[i-1].x,route[i].y-route[i-1].y)>=Math.min(21,Math.hypot(x,y)*0.3)-1e-7);
  }
});
test('acute Union-like corner is a single tangent quadratic with no overshoot',()=>{
  const c=harness(),a={x:-30,y:-30},b={x:0,y:-40},q=Math.SQRT1_2;
  const result=c.metroCornerJoin(a,{x:q,y:q},b,{x:0,y:-1});
  assert.ok(result);assert.match(result.d,/ Q/);assert.doesNotMatch(result.d,/ C/);
  for(const p of result.samples){assert.ok(p.x>=-30&&p.x<=0);assert.ok(p.y>=-40&&p.y<=0);}
  assert.equal(result.center,result.samples[16]);
  assert.ok(Math.abs(result.control.x)<1e-8&&Math.abs(result.control.y)<1e-8);
});
test('adjacent through corridors do not double back on top of one another at Union',()=>{
  const c=harness(),positions={west:{x:8.5116,y:176.5653},union:{x:222.9525,y:426.4691},east:{x:222.9525,y:169.6625}};
  const routes=c.metroRouteParts([{ids:['west','union'],lines:[0]},{ids:['union','east'],lines:[0]}],positions,66);
  const a=routes[0].at(-2),b=routes[1][1],p=positions.union;
  const dot=((a.x-p.x)*(b.x-p.x)+(a.y-p.y)*(b.y-p.y))/(Math.hypot(a.x-p.x,a.y-p.y)*Math.hypot(b.x-p.x,b.y-p.y));
  assert.ok(dot<0.98);
});
test('grid layout places unique station markers on grid and emits only orthogonal segments',()=>{
  const c=harness({'#map-metro-layout':'grid'});c.drawMetroDiagram(lines,stations);
  const layout=c.state.metroLayout;assert.equal(layout.layout,'grid');
  assert.equal(new Set(Object.values(layout.positions).map(p=>`${p.x},${p.y}`)).size,4);
  for(const p of Object.values(layout.positions))for(const axis of ['x','y']){
    const cell=(p[axis]-layout.grid_origin[axis])/layout.grid_step;
    assert.ok(Math.abs(cell-Math.round(cell))<1e-7);
  }
  const group=c.state.mapSvg.children.find(n=>n.tag==='g');
  for(const path of group.children.filter(n=>n.attrs['data-line'])){
    assert.doesNotMatch(path.attrs.d,/[QC]/);
    const points=[...path.attrs.d.matchAll(/[ML]([\d.e+-]+) ([\d.e+-]+)/g)].map(m=>({x:+m[1],y:+m[2]}));
    for(let i=1;i<points.length;i++)assert.ok(Math.abs(points[i].x-points[i-1].x)<1e-7||Math.abs(points[i].y-points[i-1].y)<1e-7);
  }
});
test('Bay corridor residual is distributed on a straight segment, not a tiny middle stair',()=>{
  const c=harness();
  const points=c.metroRouteParts([{ids:['a','bay','b'],lines:[0]}],{a:{x:8.5116456,y:176.5652673},b:{x:222.9524811,y:169.6624674}},66)[0];
  assert.equal(points.length,2);
});
test('metro shared edge has two lanes and each station is one node',()=>{
  const c=harness();c.drawMetroDiagram(lines,stations);
  const svg=c.state.mapSvg;
  assert.equal(svg.attrs['data-map-style'],'metro');
  const content=svg.children.find(n=>n.tag==='g');
  const dots=content.children.filter(n=>n.attrs['data-station']);assert.equal(dots.length,4);
  const paths=content.children.filter(n=>n.attrs['data-line']&&!n.attrs['data-station-join']);assert.equal(paths.length,4);
  assert.notEqual(paths[1].attrs.d,paths[2].attrs.d);
  assert.equal(c.state.metroLayout.coordinate_space,'display-only');
  assert.deepEqual(stations.b,{name:'换乘',lon:-73.58,lat:45.51});
});
test('small axis residuals are aligned without a dogleg or station-order reversal',()=>{
  const c=harness(),positions={a:{x:0,y:0.1},b:{x:80,y:-0.15},d:{x:160,y:0.05}};
  c.metroAlignAnchors([{ids:['a','b'],direction:{x:1,y:0}},{ids:['b','d'],direction:{x:1,y:0}}],positions,60);
  assert.ok(Math.abs(positions.a.y-positions.d.y)<1e-6);
  assert.ok(positions.a.x<positions.b.x&&positions.b.x<positions.d.x);
});
test('shared lanes retain order across reversed corridor traversal',()=>{
  const c=harness(),signs=c.metroLaneSigns([{ids:['a','b'],lines:[0,1]},{ids:['c','b'],lines:[0,1]},{ids:['c','d'],lines:[0,1]}]);
  assert.deepEqual(Array.from(signs),[1,-1,1]);
});
test('parallel lines do not converge into eye-shaped loops at intermediate stations',()=>{
  const c=harness(),routes=[];
  for(const [line,y] of [[0,-4],[1,4]]){
    routes.push({line,ids:['a','b'],points:[{x:-100,y},{x:0,y}]});
    routes.push({line,ids:['d','b'],points:[{x:100,y},{x:0,y}]});
  }
  const positions={a:{x:-100,y:0},b:{x:0,y:0},d:{x:100,y:0}};
  const paths=c.metroJoinCorridors(routes,positions,{edges:[{a:'a',b:'b'},{a:'b',b:'d'}]},{gap:60});
  for(const path of paths)assert.ok(path.samples.every(p=>Math.abs(p.y-(path.line?4:-4))<1e-8));
  assert.equal(positions.b.y,0);
});
test('interchange choice changes only symbols, not station identity or original data',()=>{
  for(const style of ['circle','capsule']){
    const c=harness({'#map-transfer-style':style});c.drawMetroDiagram(lines,stations);
    const group=c.state.mapSvg.children.find(n=>n.tag==='g'),dots=group.children.filter(n=>n.attrs['data-station']);
    assert.equal(dots.length,4);
    assert.ok(dots.filter(n=>n.attrs['data-transfer']==='true').every(n=>n.tag===(style==='capsule'?'rect':'circle')));
    assert.ok(dots.filter(n=>n.attrs['data-transfer']==='false').every(n=>n.tag==='circle'));
    assert.equal(c.state.metroLayout.transfer_style,style);
    assert.equal(c.state.metroLayout.label_count,4);
  }
});
test('corridor joins have a continuous tangent at the station and at both ends',()=>{
  const c=harness(),a={x:-40,y:0},p={x:-10,y:10},b={x:0,y:40};
  const result=c.metroCubicJoin(a,{x:1,y:0},p,b,{x:0,y:1});
  const [left,right]=result.segments;
  const delta=(a,b)=>({x:b.x-a.x,y:b.y-a.y});
  const sameDirection=(a,b)=>{
    assert.ok(Math.abs(a.x*b.y-a.y*b.x)<1e-8);
    assert.ok(a.x*b.x+a.y*b.y>0);
  };
  sameDirection(delta(left[0],left[1]),{x:1,y:0});
  sameDirection(delta(left[2],left[3]),delta(right[0],right[1]));
  sameDirection(delta(right[2],right[3]),{x:0,y:1});
  assert.deepEqual(left[3],p);assert.deepEqual(right[0],p);
});
test('a bend at a station is joined, while an ambiguous three-arm branch is not guessed',()=>{
  const c=harness();
  const s={a:{name:'A',lon:0,lat:0},b:{name:'B',lon:1,lat:0},c:{name:'C',lon:1,lat:1},d:{name:'D',lon:2,lat:0},e:{name:'E',lon:0.5,lat:0},f:{name:'F',lon:1,lat:0.5}};
  c.drawMetroDiagram([{id:'bend',name:'Bend',stops:['a','e','b','f','c']}],s);
  let group=c.state.mapSvg.children.find(n=>n.tag==='g');
  assert.ok(group.children.some(n=>n.attrs['data-station-join']==='b'&&/[QC]/.test(n.attrs.d)));
  c.drawMetroDiagram([{id:'branch',name:'Branch',stops:['a','b','c','b','d']}],s);
  group=c.state.mapSvg.children.find(n=>n.tag==='g');
  assert.ok(!group.children.some(n=>n.attrs['data-station-join']==='b'));
});
test('missing stations never create phantom adjacency',()=>{
  const c=harness();const g=c.metroTopology([{stops:['a','missing','c']}],stations);
  assert.equal(g.edges.length,0);assert.equal(g.missing,1);
});
test('duplicate visits, coincident coordinates and disconnected routes remain finite',()=>{
  const c=harness();const s={a:{name:'同名',lat:0,lon:0},b:{name:'同名',lat:0,lon:0},c:{name:'孤立',lat:0,lon:0}};
  c.drawMetroDiagram([{id:'x',name:'环线',stops:['a','b','a'],color:'ff0000ff'},{id:'y',name:'支线',stops:['c'],color:'ffff0000'}],s);
  const p=Object.values(c.state.metroLayout.positions);
  assert.equal(new Set(p.map(p=>`${p.x},${p.y}`)).size,3);
  assert.ok(p.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
  assert.doesNotMatch(JSON.stringify(c.state.mapSvg),/NaN|Infinity/);
});
test('metro segments are exactly orthogonal or 45 degrees',()=>{
  const c=harness();for(const [x,y] of [[100,20],[-50,80],[0,40],[40,0]]){
    const p=c.metroSegment({x:0,y:0},{x,y});
    for(let i=1;i<p.length;i++){const dx=Math.abs(p[i].x-p[i-1].x),dy=Math.abs(p[i].y-p[i-1].y);assert.ok(dx===0||dy===0||Math.abs(dx-dy)<1e-9);}
  }
});
test('update rollback states have distinct honest messages',()=>{
  const c=vm.createContext({});vm.runInContext(between('function updateFailureMessage(', 'async function api('),c);
  assert.match(c.updateFailureMessage({rollback_complete:true}),/已恢复/);
  assert.match(c.updateFailureMessage({rollback_complete:false,backup_dir:'D:/backup'}),/恢复不完整.*D:\/backup/);
  assert.match(c.updateFailureMessage({}),/无法确认/);
});
test('all target headway calculations round up',()=>{
  assert.doesNotMatch(app,/Math\.round\((cycle \/ target|T \/ targetSec)\)/);
});
test('invalid peak windows are rejected, not silently ignored',()=>{
  const c=vm.createContext({});vm.runInContext(between('function ttdTime(', 'function ttdInPeak('),c);
  assert.equal(c.ttdTime('07:99'),null);
  assert.equal(c.ttdWindows('nonsense'),null);
  assert.equal(c.ttdWindows('07:00-09:00，16:00-18:00').length,2);
  assert.equal(c.ttdWindows('23:00-01:00')[0][1],25*3600);
});
test('a many-stop straight corridor is one continuous path, not per-edge kinks',()=>{
  const c=harness(),s={},stops=[];
  for(let i=0;i<20;i++){const id=String(i);stops.push(id);s[id]={name:`Station ${i}`,lon:i*0.01,lat:0};}
  c.drawMetroDiagram([{id:'long',name:'Line 1',color:'ff3366cc',stops}],s);
  const group=c.state.mapSvg.children.find(n=>n.tag==='g');
  assert.equal(group.children.filter(n=>n.attrs['data-line']).length,1);
  assert.equal(group.children.filter(n=>n.attrs['data-station-label']).length,20);
  assert.equal(c.state.metroLayout.label_conflicts,0);
  assert.doesNotMatch(JSON.stringify(c.state.mapSvg),/拥挤站名索引/);
});
test('closed loops preserve every station and produce rounded corners',()=>{
  const c=harness(),s={a:{name:'A',lon:0,lat:0},b:{name:'B',lon:1,lat:0},c:{name:'C',lon:1,lat:1},d:{name:'D',lon:0,lat:1}};
  c.drawMetroDiagram([{id:'loop',name:'Loop',stops:['a','b','c','d','a']}],s);
  assert.equal(Object.keys(c.state.metroLayout.positions).length,4);
  assert.equal(c.state.metroLayout.label_count,4);
  assert.ok(c.metroRounded([{x:0,y:0},{x:100,y:0},{x:100,y:100}],20).d.includes('Q'));
});
test('line search and natural ordering do not mutate selections or source data',()=>{
  const c=vm.createContext({Intl,Set});vm.runInContext(between('function filterMapLines(', 'function visibleMapLines('),c);
  const routes=[{id:'10',name:'Line 10',code:'10',stop_count:3,stops:['a']},{id:'2',name:'Line 2',code:'2',stop_count:8,stops:['b']},{id:'1',name:'Alpha',code:'1',stop_count:2,stops:['b']}];
  const selected=new Set(['10','2']),original=JSON.stringify(routes);
  const station={a:{name:'中央'},b:{name:'北站'}};
  const query=(q,order='name-asc',only=false)=>c.filterMapLines(routes,station,selected,q,order,only);
  assert.deepEqual(Array.from(query('').map(l=>l.id)),['1','2','10']);
  assert.deepEqual(Array.from(query('','name-desc').map(l=>l.id)),['10','2','1']);
  assert.deepEqual(Array.from(query('','code-asc').map(l=>l.id)),['1','2','10']);
  assert.deepEqual(Array.from(query('','stops-desc').map(l=>l.id)),['2','10','1']);
  assert.deepEqual(Array.from(query('中央').map(l=>l.id)),['10']);
  assert.deepEqual(Array.from(query('LINE 2').map(l=>l.id)),['2']);
  assert.equal(query('nonexistent').length,0);
  assert.equal(query('','name-asc',true).length,2);
  assert.deepEqual([...selected],['10','2']);assert.equal(JSON.stringify(routes),original);
});
