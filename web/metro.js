/* Metro schematic: shared station identity, parallel colours on shared edges,
 * and orthogonal/45-degree segments. Display coordinates never modify saves. */
function metroBranchFamily(name) {
  return String(name||'').normalize('NFKC').trim()
    .replace(/\s+daily$/i,'')
    .replace(/[\s_-]*(?:支线|分支|branch)(?:\s*[^\s]+)?$/i,'')
    .replace(/(\d)[\s_-]*[a-z]$/i,'$1')
    .replace(/\s*\([^)]*\)\s*$/,'').trim().toLocaleLowerCase();
}
function metroDisplayLines(lines, mergeBranches=true, overrides={}) {
  const parent=lines.map((_,i)=>i),root=i=>parent[i]===i?i:(parent[i]=root(parent[i]));
  const data=lines.map(line=>{
    const edges=new Set(),degree=new Map(),stops=line.stops||[];
    for(let i=1;i<stops.length;i++){
      if(stops[i]==null||stops[i-1]==null||stops[i]===stops[i-1])continue;
      const a=String(stops[i-1]),b=String(stops[i]),key=JSON.stringify([a,b].sort());
      if(edges.has(key))continue;edges.add(key);degree.set(a,(degree.get(a)||0)+1);degree.set(b,(degree.get(b)||0)+1);
    }
    const ends=new Set([...degree].filter(([,n])=>n===1).map(([id])=>id));
    if(stops.length)ends.add(String(stops[0]));
    return {edges,ends,family:metroBranchFamily(line.name),code:String(line.code||'').trim().toLowerCase(),color:String(line.color||'').toLowerCase()};
  });
  if(mergeBranches)for(let i=0;i<lines.length;i++)for(let j=i+1;j<lines.length;j++){
    const oa=Object.hasOwn(overrides,String(lines[i].id))?overrides[String(lines[i].id)]:null;
    const ob=Object.hasOwn(overrides,String(lines[j].id))?overrides[String(lines[j].id)]:null;
    if(oa||ob){if(oa&&ob&&oa!=='!independent'&&oa===ob)parent[root(j)]=root(i);continue;}
    const a=data[i],b=data[j],shared=[...a.edges].filter(e=>b.edges.has(e)).length;
    const identity=(a.family&&a.family===b.family)||(a.code&&a.code===b.code);
    const commonEnd=[...a.ends].some(id=>b.ends.has(id));
    // A common origin by itself is NOT evidence of being the same line.
    if((identity&&shared>=1)||(a.color&&a.color===b.color&&commonEnd&&shared>=2))parent[root(j)]=root(i);
  }
  const groups=new Map();
  lines.forEach((line,i)=>{
    const key=root(i);
    if(!groups.has(key))groups.set(key,{...line,source_ids:[],source_names:[],routes:[],group_method:'independent'});
    const group=groups.get(key);group.source_ids.push(String(line.id));group.source_names.push(line.name);group.routes.push(line.stops||[]);
  });
  for(const group of groups.values())if(group.source_ids.length>1){
    const custom=Object.hasOwn(overrides,group.source_ids[0])?overrides[group.source_ids[0]]:null;
    group.group_method=custom?'manual':'automatic';
    group.name=custom||`${group.source_names[0]} · 分支组`;
  }
  return [...groups.values()];
}
function metroTopology(lines, stations) {
  const nodes = new Map(), edges = new Map(); let missing = 0;
  lines.forEach((line, index) => {
    (line.routes||[line.stops||[]]).forEach(stops=>{
    let previous = null;
    stops.forEach(value => {
      const id = String(value), station = stations[id];
      if (!station || !Number.isFinite(station.lon) || !Number.isFinite(station.lat)) {
        previous = null; missing++; return; // Never bridge a missing station.
      }
      if (!nodes.has(id)) nodes.set(id, {id, ...station, lines:new Set()});
      nodes.get(id).lines.add(index);
      if (previous !== null && previous !== id) {
        const pair = [previous, id].sort(), key = JSON.stringify(pair);
        if (!edges.has(key)) edges.set(key, {a:pair[0], b:pair[1], lines:new Set()});
        edges.get(key).lines.add(index);
      }
      previous = id;
    });
    });
  });
  return {nodes, edges:[...edges.values()], missing};
}
function metroEl(tag, attrs, text) {
  const element = svgEl(tag, attrs);
  if (text != null) element.textContent = text;
  return element;
}
function metroSegment(a, b) {
  const dx = b.x-a.x, dy = b.y-a.y, diagonal = Math.min(Math.abs(dx), Math.abs(dy));
  const sx = Math.sign(dx), sy = Math.sign(dy);
  if (Math.abs(dx) >= Math.abs(dy)) {
    const lead = (Math.abs(dx)-diagonal)/2;
    return [a, {x:a.x+sx*lead,y:a.y}, {x:a.x+sx*(lead+diagonal),y:b.y}, b];
  }
  const lead = (Math.abs(dy)-diagonal)/2;
  return [a, {x:a.x,y:a.y+sy*lead}, {x:b.x,y:a.y+sy*(lead+diagonal)}, b];
}
