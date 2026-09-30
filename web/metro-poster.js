/* Corridor-level schematic layout. No station names are replaced by an index. */
function metroChains(graph, raw) {
  const adj=new Map([...graph.nodes.keys()].map(id=>[id,[]]));
  graph.edges.forEach((e,i)=>{adj.get(e.a).push({id:e.b,edge:i});adj.get(e.b).push({id:e.a,edge:i});});
  const signature=e=>[...e.lines].sort().join(',');
  const junction=id=>{const a=adj.get(id);return a.length!==2||signature(graph.edges[a[0].edge])!==signature(graph.edges[a[1].edge]);};
  const seen=new Set(), chains=[];
  function walk(start,first) {
    const ids=[start], edges=[];let step=first;
    while(step&&!seen.has(step.edge)){
      seen.add(step.edge);edges.push(step.edge);ids.push(step.id);
      if(step.id===start||junction(step.id))break;
      step=adj.get(step.id).find(x=>!seen.has(x.edge));
    }
    if(edges.length)chains.push({ids,lines:[...graph.edges[edges[0]].lines].sort((a,b)=>a-b)});
  }
  [...adj.keys()].sort().filter(junction).forEach(id=>adj.get(id).forEach(e=>walk(id,e)));
  [...adj.keys()].sort().forEach(id=>adj.get(id).forEach(e=>walk(id,e)));
  const lengths=graph.edges.map(e=>Math.hypot(raw[e.a].x-raw[e.b].x,raw[e.a].y-raw[e.b].y)).filter(x=>x>0).sort((a,b)=>a-b);
  const unit=lengths[Math.floor(lengths.length/2)]||1;
  function bends(ids,lo,hi,result) {
    if(hi-lo<2)return;
    const a=raw[ids[lo]],b=raw[ids[hi]],dx=b.x-a.x,dy=b.y-a.y,len=dx*dx+dy*dy;
    let greatest=unit*0.85,index=-1;
    for(let i=lo+1;i<hi;i++){
      const p=raw[ids[i]],t=len?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/len)):0;
      const d=Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy);
      if(d>greatest){greatest=d;index=i;}
    }
    if(index!==-1){result.add(index);bends(ids,lo,index,result);bends(ids,index,hi,result);}
  }
  const parts=[];
  chains.forEach(c=>{
    const cuts=new Set([0,c.ids.length-1]);
    if(c.ids[0]===c.ids.at(-1)&&c.ids.length>3)cuts.add(Math.floor((c.ids.length-1)/2));
    const initial=[...cuts].sort((a,b)=>a-b);
    for(let i=1;i<initial.length;i++)bends(c.ids,initial[i-1],initial[i],cuts);
    const indices=[...cuts].sort((a,b)=>a-b);
    for(let i=1;i<indices.length;i++)parts.push({...c,ids:c.ids.slice(indices[i-1],indices[i]+1)});
  });
  return {parts,unit,adj};
}
function metroCorridorLayout(graph, raw, gap) {
  const {parts,unit,adj}=metroChains(graph,raw), anchors=new Set();
  parts.forEach(c=>{anchors.add(c.ids[0]);anchors.add(c.ids.at(-1));});
  adj.forEach((edges,id)=>{if(!edges.length)anchors.add(id);});
  const ids=[...anchors].sort(),positions={},origin={};
  const all=Object.values(raw),cx=all.reduce((s,p)=>s+p.x,0)/all.length,cy=all.reduce((s,p)=>s+p.y,0)/all.length;
  const span=Math.max(...all.map(p=>p.x))-Math.min(...all.map(p=>p.x))+Math.max(...all.map(p=>p.y))-Math.min(...all.map(p=>p.y));
  const initialScale=Math.min(gap/unit,Math.sqrt(graph.nodes.size)*gap*5/(span||1));
  ids.forEach(id=>{origin[id]={x:(raw[id].x-cx)*initialScale,y:(raw[id].y-cy)*initialScale};positions[id]={...origin[id]};});
  const constraints=parts.map((c,i)=>{
    const a=c.ids[0],b=c.ids.at(-1),dx=raw[b].x-raw[a].x,dy=raw[b].y-raw[a].y;
    const angle=(dx||dy)?Math.round(Math.atan2(dy,dx)/(Math.PI/4))*Math.PI/4:(i%8)*Math.PI/4;
    const length=(c.ids.length-1)*gap;
    c.direction={x:Math.cos(angle),y:Math.sin(angle)};
    return {a,b,dx:Math.cos(angle)*length,dy:Math.sin(angle)*length,ux:Math.cos(angle),uy:Math.sin(angle)};
  });
  for(let iteration=0;iteration<600;iteration++){
    const force={};ids.forEach(id=>{force[id]={x:(origin[id].x-positions[id].x)*0.002,y:(origin[id].y-positions[id].y)*0.002,n:0.15};});
    constraints.forEach(c=>{
      const ex=positions[c.b].x-positions[c.a].x-c.dx,ey=positions[c.b].y-positions[c.a].y-c.dy;
      const along=ex*c.ux+ey*c.uy,across=-ex*c.uy+ey*c.ux;
      // Direction takes priority over exact station spacing. Equal weighting
      // left small axis errors that turned into little hooks at every junction.
      const dx=(along*c.ux*0.08-across*c.uy*1.5)*0.5,dy=(along*c.uy*0.08+across*c.ux*1.5)*0.5;
      force[c.a].x+=dx;force[c.a].y+=dy;force[c.a].n++;
      force[c.b].x-=dx;force[c.b].y-=dy;force[c.b].n++;
    });
    for(let i=0;i<ids.length;i++)for(let j=i+1;j<ids.length;j++){
      const a=ids[i],b=ids[j],dx=positions[b].x-positions[a].x,dy=positions[b].y-positions[a].y,dist=Math.hypot(dx,dy),min=gap*0.9;
      if(dist>=min)continue;
      const ux=dist?dx/dist:Math.cos((i+j)*2.4),uy=dist?dy/dist:Math.sin((i+j)*2.4),push=(min-dist)*0.15;
      force[a].x-=ux*push;force[a].y-=uy*push;force[b].x+=ux*push;force[b].y+=uy*push;
    }
    ids.forEach(id=>{positions[id].x+=force[id].x/force[id].n;positions[id].y+=force[id].y/force[id].n;});
    // A short interchange link must never flip direction to satisfy its much
    // longer neighbours. That reversed Spadina / St. George in the old layout.
    constraints.forEach(c=>{
      const a=positions[c.a],b=positions[c.b],projected=(b.x-a.x)*c.ux+(b.y-a.y)*c.uy;
      const minimum=Math.hypot(c.dx,c.dy)*0.45,correction=Math.max(0,minimum-projected)/2;
      a.x-=c.ux*correction;a.y-=c.uy*correction;b.x+=c.ux*correction;b.y+=c.uy*correction;
    });
  }
  metroAlignAnchors(parts,positions,gap);
  return {parts,anchors:positions};
}
function metroAlignAnchors(parts,positions,gap) {
  // Remove small solver residuals at the node level, not by inserting tiny
  // horizontal/diagonal doglegs downstream. Roll back if alignment collapses an edge.
  const original=Object.fromEntries(Object.entries(positions).map(([id,p])=>[id,{...p}]));
  let constraints=parts.map(c=>{
    const a=c.ids[0],b=c.ids.at(-1),dx=positions[b].x-positions[a].x,dy=positions[b].y-positions[a].y;
    const angle=Math.round(Math.atan2(dy,dx)/(Math.PI/4))*Math.PI/4,nx=-Math.sin(angle),ny=Math.cos(angle);
    return {a,b,nx,ny,length:Math.hypot(dx,dy),error:Math.abs(dx*nx+dy*ny)};
  }).filter(c=>c.length>gap*0.7&&c.error<gap*0.3);
  for(let retry=0;retry<10;retry++){
    Object.entries(original).forEach(([id,p])=>Object.assign(positions[id],p));
    for(let pass=0;pass<1200;pass++){
      let maximum=0;
      constraints.forEach(c=>{
        const a=positions[c.a],b=positions[c.b],error=(b.x-a.x)*c.nx+(b.y-a.y)*c.ny;
        maximum=Math.max(maximum,Math.abs(error));
        a.x+=c.nx*error/2;a.y+=c.ny*error/2;b.x-=c.nx*error/2;b.y-=c.ny*error/2;
      });
      if(maximum<1e-7)break;
    }
    const unsafe=new Set();
    parts.forEach(c=>{
      const a=c.ids[0],b=c.ids.at(-1),before=Math.hypot(original[b].x-original[a].x,original[b].y-original[a].y);
      const dx=positions[b].x-positions[a].x,dy=positions[b].y-positions[a].y;
      if(Math.hypot(dx,dy)<before*0.65||(c.direction&&dx*c.direction.x+dy*c.direction.y<=0)){unsafe.add(a);unsafe.add(b);}
    });
    if(!unsafe.size)return;
    constraints=constraints.filter(c=>!unsafe.has(c.a)&&!unsafe.has(c.b));
  }
  Object.entries(original).forEach(([id,p])=>Object.assign(positions[id],p));
}
function metroLaneSigns(parts) {
  const ports=new Map(),signs=Array(parts.length).fill(0),adj=parts.map(()=>[]);
  parts.forEach((c,index)=>[c.ids[0],c.ids.at(-1)].forEach((id,end)=>{
    if(!ports.has(id))ports.set(id,[]);ports.get(id).push({index,end});
  }));
  ports.forEach(list=>list.forEach((a,i)=>list.slice(i+1).forEach(b=>{
    if(parts[a.index].lines.filter(l=>parts[b.index].lines.includes(l)).length<2)return;
    const relation=a.end===b.end?-1:1;
    adj[a.index].push({index:b.index,relation});adj[b.index].push({index:a.index,relation});
  })));
  parts.forEach((_,i)=>{
    if(signs[i])return;signs[i]=1;const queue=[i];
    for(let j=0;j<queue.length;j++)adj[queue[j]].forEach(next=>{
      if(!signs[next.index]){signs[next.index]=signs[queue[j]]*next.relation;queue.push(next.index);}
    });
  });
  return signs;
}
function metroRounded(points,radius) {
  const clean=[];
  points.forEach(p=>{if(!clean.length||Math.hypot(p.x-clean.at(-1).x,p.y-clean.at(-1).y)>0.001)clean.push({...p});});
  for(let i=clean.length-2;i>0;i--){
    const a=clean[i-1],b=clean[i],c=clean[i+1];
    if(Math.abs((b.x-a.x)*(c.y-b.y)-(b.y-a.y)*(c.x-b.x))<0.001&&(b.x-a.x)*(c.x-b.x)+(b.y-a.y)*(c.y-b.y)>0)clean.splice(i,1);
  }
  if(!clean.length)return {d:'',samples:[]};
  if(radius<=0)return {d:clean.map((p,i)=>`${i?'L':'M'}${p.x} ${p.y}`).join(' '),samples:clean};
  let d='M'+clean[0].x+' '+clean[0].y;const samples=[clean[0]];
  for(let i=1;i<clean.length-1;i++){
    const a=clean[i-1],b=clean[i],c=clean[i+1],ab=Math.hypot(b.x-a.x,b.y-a.y),bc=Math.hypot(c.x-b.x,c.y-b.y);
    const r=Math.min(radius,ab*0.42,bc*0.42);
    const before={x:b.x+(a.x-b.x)*r/ab,y:b.y+(a.y-b.y)*r/ab},after={x:b.x+(c.x-b.x)*r/bc,y:b.y+(c.y-b.y)*r/bc};
    d+=` L${before.x} ${before.y} Q${b.x} ${b.y} ${after.x} ${after.y}`;samples.push(before);
    for(let k=1;k<=16;k++){const t=k/16;samples.push({x:(1-t)**2*before.x+2*t*(1-t)*b.x+t*t*after.x,y:(1-t)**2*before.y+2*t*(1-t)*b.y+t*t*after.y});}
  }
  if(clean.length>1){d+=` L${clean.at(-1).x} ${clean.at(-1).y}`;samples.push(clean.at(-1));}
  return {d,samples};
}
function metroOffset(points,offset) {
  return points.map((p,i)=>{
    const prev=points[Math.max(0,i-1)],next=points[Math.min(points.length-1,i+1)];
    const l1=Math.hypot(p.x-prev.x,p.y-prev.y),l2=Math.hypot(next.x-p.x,next.y-p.y);
    const n1=l1?{x:-(p.y-prev.y)/l1,y:(p.x-prev.x)/l1}:null,n2=l2?{x:-(next.y-p.y)/l2,y:(next.x-p.x)/l2}:null;
    const n=n1&&n2?{x:n1.x+n2.x,y:n1.y+n2.y}:(n1||n2||{x:0,y:1});
    const div=n1&&n2?Math.max(0.35,1+n1.x*n2.x+n1.y*n2.y):1;
    return {x:p.x+n.x*offset/div,y:p.y+n.y*offset/div};
  });
}
function metroSampleAt(samples,fraction) {
  const lengths=samples.slice(1).map((p,i)=>Math.hypot(p.x-samples[i].x,p.y-samples[i].y));
  let remaining=lengths.reduce((a,b)=>a+b,0)*fraction;
  for(let i=0;i<lengths.length;i++){
    if(remaining<=lengths[i]||i===lengths.length-1){
      const a=samples[i],b=samples[i+1],len=lengths[i]||1,t=Math.max(0,Math.min(1,remaining/len));
      return {x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,tx:(b.x-a.x)/len,ty:(b.y-a.y)/len};
    }
    remaining-=lengths[i];
  }
  return {...samples[0],tx:1,ty:0};
}
// Trim both incident corridors before rounding their shared station. Previously
// every corridor ended at a hard vertex, so its neighbour could not share a tangent.
function metroTrim(points,start,end) {
  const trim=(pts,d)=>{
    const out=pts.map(p=>({...p}));
    while(out.length>1){
      const a=out[0],b=out[1],len=Math.hypot(b.x-a.x,b.y-a.y);
      if(len<=d+1e-8){d-=len;out.shift();continue;}
      out[0]={x:a.x+(b.x-a.x)*d/len,y:a.y+(b.y-a.y)*d/len};break;
    }
    return out;
  };
  return trim(trim(points,start).reverse(),end).reverse();
}
function metroRouteParts(parts,positions,gap,gridStep=0) {
  const clean=points=>{
    const out=[];
    points.forEach(p=>{if(!out.length||Math.hypot(p.x-out.at(-1).x,p.y-out.at(-1).y)>0.001)out.push(p);});
    return out;
  };
  const choices=parts.map(c=>{
    const a=positions[c.ids[0]],b=positions[c.ids.at(-1)],dx=b.x-a.x,dy=b.y-a.y;
    if(gridStep){
      const candidates=[[a,{x:b.x,y:a.y},b],[a,{x:a.x,y:b.y},b]];
      for(const distance of [gridStep,gridStep*2]){
        for(const x of [Math.min(a.x,b.x)-distance,Math.max(a.x,b.x)+distance])candidates.push([a,{x,y:a.y},{x,y:b.y},b]);
        for(const y of [Math.min(a.y,b.y)-distance,Math.max(a.y,b.y)+distance])candidates.push([a,{x:a.x,y},{x:b.x,y},b]);
      }
      return candidates.map(clean);
    }
    const residual=Math.min(Math.abs(dx),Math.abs(dy),Math.abs(Math.abs(dx)-Math.abs(dy))/Math.SQRT2);
    // Spread a tiny residual over the whole corridor instead of drawing a
    // visible stair-step. Strict right angles are available in grid mode.
    if(residual<gap*0.2&&residual/Math.max(1,Math.hypot(dx,dy))<0.04)return [[a,b]];
    const d=Math.min(Math.abs(dx),Math.abs(dy)),sx=Math.sign(dx),sy=Math.sign(dy);
    const minimum=Math.min(gap*0.35,Math.hypot(dx,dy)*0.3);
    const candidates=[[a,{x:a.x+sx*d,y:a.y+sy*d},b],[a,{x:b.x-sx*d,y:b.y-sy*d},b]].map(clean)
      .filter(points=>points.slice(1).every((p,i)=>Math.hypot(p.x-points[i].x,p.y-points[i].y)>=minimum-1e-7));
    // Never spend a tiny leg correcting a solver residual. A slightly slanted
    // straight corridor is preferable; strict orthogonal routing is grid mode.
    return candidates.length?candidates:[[a,b]];
  });
  const selected=parts.map(()=>0),ports=new Map();
  parts.forEach((c,index)=>c.lines.forEach(line=>[c.ids[0],c.ids.at(-1)].forEach((id,end)=>{
    const key=JSON.stringify([id,line]);if(!ports.has(key))ports.set(key,[]);ports.get(key).push({index,end});
  })));
  const pairs=[...ports.values()].filter(p=>p.length===2&&p[0].index!==p[1].index);
  const direction=port=>{
    const points=choices[port.index][selected[port.index]],a=port.end?points.at(-1):points[0],b=port.end?points.at(-2):points[1];
    const len=Math.hypot(b.x-a.x,b.y-a.y)||1;return {x:(b.x-a.x)/len,y:(b.y-a.y)/len};
  };
  const fixedCosts=choices.map((options,index)=>options.map(pts=>{
    let value=(pts.length-2)*0.08;
    if(gridStep){
      value+=(pts.slice(1).reduce((s,p,i)=>s+Math.hypot(p.x-pts[i].x,p.y-pts[i].y),0)/gridStep)*0.03;
      Object.entries(positions).forEach(([id,p])=>{
        if(parts[index].ids.includes(id))return;
        for(let i=1;i<pts.length;i++){
          const a=pts[i-1],b=pts[i],dx=b.x-a.x,dy=b.y-a.y,len=dx*dx+dy*dy;
          const t=len?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/len)):0;
          if(Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy)<gridStep*0.25){value+=10000;break;}
        }
      });
    }
    for(let i=1;i<pts.length;i++)value+=Math.max(0,0.3-Math.hypot(pts[i].x-pts[i-1].x,pts[i].y-pts[i-1].y)/gap)*0.2;
    return value;
  }));
  const localPairs=parts.map((_,index)=>pairs.filter(pair=>pair.some(p=>p.index===index)));
  const score=index=>{
    let value=fixedCosts[index][selected[index]];
    localPairs[index].forEach(pair=>{
      const a=direction(pair[0]),b=direction(pair[1]);
      const dot=a.x*b.x+a.y*b.y;
      value+=4*(1+dot);
      // Two outward ports in the same direction retrace the same track into
      // the station, making a through station look like a dead end (Union).
      // Do not trade this for a slightly straighter join at the opposite end.
      if(dot>0.98)value+=1000;
    });
    return value;
  };
  // Joint endpoint routing, rather than a fixed half-horizontal/diagonal stub
  // at every corridor. Grid routes use strictly orthogonal segments.
  for(let pass=0;pass<12;pass++){
    let changed=false;
    parts.forEach((_,i)=>{
      const old=selected[i];let best=old,cost=score(i);
      for(let option=0;option<choices[i].length;option++){selected[i]=option;const next=score(i);if(next<cost-1e-7){best=option;cost=next;}}
      selected[i]=best;changed ||= best!==old;
    });
    if(!changed)break;
  }
  return choices.map((c,i)=>c[selected[i]]);
}
function metroGridLayout(graph,raw,gap) {
  const base=metroCorridorLayout(graph,raw,gap),initial={...base.anchors};
  base.parts.forEach(c=>{
    const samples=metroRounded(metroSegment(base.anchors[c.ids[0]],base.anchors[c.ids.at(-1)]),0).samples;
    c.ids.forEach((id,i)=>{if(!initial[id])initial[id]=metroSampleAt(samples,i/(c.ids.length-1));});
  });
  const step=gap,occupied=new Set(),anchors={};
  const ids=[...graph.nodes.keys()].sort((a,b)=>graph.nodes.get(b).lines.size-graph.nodes.get(a).lines.size||a.localeCompare(b));
  ids.forEach(id=>{
    const p=initial[id],x=Math.round(p.x/step),y=Math.round(p.y/step);
    let best=null;
    for(let ring=0;!best;ring++){
      const options=[];
      for(let dx=-ring;dx<=ring;dx++)for(let dy=-ring;dy<=ring;dy++){
        if(Math.max(Math.abs(dx),Math.abs(dy))!==ring||occupied.has(`${x+dx},${y+dy}`))continue;
        options.push({x:x+dx,y:y+dy,d:Math.hypot((x+dx)*step-p.x,(y+dy)*step-p.y)});
      }
      options.sort((a,b)=>a.d-b.d||a.x-b.x||a.y-b.y);best=options[0];
    }
    occupied.add(`${best.x},${best.y}`);anchors[id]={x:best.x*step,y:best.y*step};
  });
  return {anchors,parts:graph.edges.map(e=>({ids:[e.a,e.b],lines:[...e.lines].sort((a,b)=>a-b)})),gridStep:step};
}
// Separate geometrically coincident corridors without changing the graph.
// A corridor may include several bend anchors. Move those anchors together;
// only actual junctions stay pinned and get a short fan-out connection.
function metroSeparateCorridors(parts,routes,positions,gap) {
  const ports=new Map(),parent=parts.map((_,i)=>i);
  const root=i=>parent[i]===i?i:(parent[i]=root(parent[i]));
  parts.forEach((part,index)=>[part.ids[0],part.ids.at(-1)].forEach(id=>{
    if(!ports.has(id))ports.set(id,[]);ports.get(id).push(index);
  }));
  const movable=new Set();
  ports.forEach((list,id)=>{
    if(list.length===2&&list[0]!==list[1]&&JSON.stringify(parts[list[0]].lines)===JSON.stringify(parts[list[1]].lines)){
      parent[root(list[1])]=root(list[0]);movable.add(id);
    }
    if(list.length===1)movable.add(id);
  });
  const groups=new Map();
  parts.forEach((_,i)=>{const key=root(i);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(i);});
  const clean=points=>points.filter((p,i)=>!i||Math.hypot(p.x-points[i-1].x,p.y-points[i-1].y)>1e-6);
  const candidates=[...groups.values()].map(indices=>{
    const pts=indices.flatMap(i=>routes[i]),bounds=metroBounds(pts);
    const normal=bounds.h>=bounds.w?{x:1,y:0}:{x:0,y:1};
    return [0,-1,1,-2,2,-3,3,-4,4].map(lane=>{
      const shift={x:normal.x*lane*gap,y:normal.y*lane*gap},paths=[],nodes=new Map();
      indices.forEach(index=>{
        const part=parts[index],original=routes[index].map(p=>({...p}));
        let points=original.map(p=>({x:p.x+shift.x,y:p.y+shift.y}));
        if(lane){
          // At a real shared node, fan out once instead of overlaying a whole
          // independent route. Do not relocate that node per colour.
          for(const end of [0,1]){
            const id=end?part.ids.at(-1):part.ids[0];if(movable.has(id))continue;
            if(end){points.reverse();original.reverse();}
            const a=original[0],b=original[1],len=Math.hypot(b.x-a.x,b.y-a.y)||1;
            const run=Math.min(Math.abs(lane)*gap,len*0.4);
            points[0]={x:points[0].x+(b.x-a.x)/len*run,y:points[0].y+(b.y-a.y)/len*run};
            points.unshift({...a});
            if(end){points.reverse();original.reverse();}
          }
        }
        points=clean(points);
        const samples=metroRounded(points,gap*0.4).samples;
        part.ids.forEach((id,i)=>{
          const p=metroSampleAt(samples,i/(part.ids.length-1));
          // Anchor markers belong at the exact meeting point of their parts.
          if(i===0||i===part.ids.length-1){const original=positions[id];nodes.set(id,{x:original.x+(movable.has(id)?shift.x:0),y:original.y+(movable.has(id)?shift.y:0)});}
          else nodes.set(id,p);
        });
        paths.push({index,points});
      });
      const segments=paths.flatMap(path=>path.points.slice(1).map((b,i)=>({a:path.points[i],b})));
      return {paths,nodes,segments,lane,shift,indices};
    });
  });
  const clearance=gap*0.62;
  const distance=(p,a,b)=>{const dx=b.x-a.x,dy=b.y-a.y,l=dx*dx+dy*dy,t=l?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/l)):0;return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy);};
  function conflict(a,b){
    let cost=0;
    for(const s of a.segments)for(const t of b.segments){
      const dx=s.b.x-s.a.x,dy=s.b.y-s.a.y,len=Math.hypot(dx,dy),ex=t.b.x-t.a.x,ey=t.b.y-t.a.y,other=Math.hypot(ex,ey);
      if(!len||!other||Math.abs(dx*ey-dy*ex)/(len*other)>0.08)continue;
      const ux=dx/len,uy=dy/len,sep=Math.abs((t.a.x-s.a.x)*uy-(t.a.y-s.a.y)*ux);
      if(sep>=clearance)continue;
      const q1=(t.a.x-s.a.x)*ux+(t.a.y-s.a.y)*uy,q2=(t.b.x-s.a.x)*ux+(t.b.y-s.a.y)*uy;
      const overlap=Math.min(len,Math.max(q1,q2))-Math.max(0,Math.min(q1,q2));
      if(overlap>gap*0.2)cost+=overlap/gap*(1-sep/clearance)**2*100;
    }
    for(const [first,second] of [[a,b],[b,a]])for(const [id,p] of first.nodes){
      if(second.nodes.has(id))continue;
      const d=Math.min(...second.segments.map(s=>distance(p,s.a,s.b)));
      if(d<clearance*0.5)cost+=80*(1-d/(clearance*0.5))**2;
    }
    return cost;
  }
  const chosen=candidates.map(()=>0),cache=new Map();
  const pairCost=(i,a,j,b)=>{
    if(i>j)return pairCost(j,b,i,a);
    const key=`${i}:${a}:${j}:${b}`;
    if(!cache.has(key))cache.set(key,conflict(candidates[i][a],candidates[j][b]));
    return cache.get(key);
  };
  for(let pass=0;pass<4;pass++){
    let changed=false;
    candidates.forEach((options,i)=>{
      const score=k=>Math.abs(options[k].lane)*0.6+chosen.reduce((sum,other,j)=>sum+(i===j?0:pairCost(i,k,j,other)),0);
      let best=chosen[i],cost=score(best);
      for(let k=0;k<options.length;k++){const next=score(k);if(next<cost-1e-7){best=k;cost=next;}}
      changed ||= best!==chosen[i];chosen[i]=best;
    });
    if(!changed)break;
  }
  const result=routes.slice();
  candidates.forEach((options,i)=>{
    const selected=options[chosen[i]];
    selected.paths.forEach(path=>result[path.index]=path.points);
    selected.nodes.forEach((p,id)=>{if(positions[id]&&movable.has(id))positions[id]={...positions[id],x:p.x,y:p.y};});
  });
  return result;
}
function metroCubicJoin(a,ta,p,b,tb) {
  const al=Math.hypot(p.x-a.x,p.y-a.y),bl=Math.hypot(b.x-p.x,b.y-p.y);
  const span=Math.hypot(b.x-a.x,b.y-a.y)||1,t={x:(b.x-a.x)/span,y:(b.y-a.y)/span};
  // Shared tangent at the station; the outer handles continue the exact tangent
  // of each trimmed corridor (including a corridor ending on a rounded turn).
  const handle=Math.min(al,bl)*0.42;
  const segments=[
    [a,{x:a.x+ta.x*al*0.45,y:a.y+ta.y*al*0.45},{x:p.x-t.x*handle,y:p.y-t.y*handle},p],
    [p,{x:p.x+t.x*handle,y:p.y+t.y*handle},{x:b.x-tb.x*bl*0.45,y:b.y-tb.y*bl*0.45},b]
  ];
  const samples=[a];let d=`M${a.x} ${a.y}`;
  segments.forEach(([s,c1,c2,e])=>{
    d+=` C${c1.x} ${c1.y} ${c2.x} ${c2.y} ${e.x} ${e.y}`;
    for(let i=1;i<=16;i++){const t=i/16,u=1-t;samples.push({x:u**3*s.x+3*u*u*t*c1.x+3*u*t*t*c2.x+t**3*e.x,y:u**3*s.y+3*u*u*t*c1.y+3*u*t*t*c2.y+t**3*e.y});}
  });
  return {d,samples,segments};
}
function metroCornerJoin(a,ta,b,tb) {
  const cross=(u,v)=>u.x*v.y-u.y*v.x,delta={x:b.x-a.x,y:b.y-a.y};
  const determinant=cross(ta,tb),span=Math.hypot(delta.x,delta.y);
  if(Math.abs(determinant)<1e-6){
    if(ta.x*tb.x+ta.y*tb.y>0.999&&Math.abs(cross(delta,ta))<0.01)
      return {d:`M${a.x} ${a.y} L${b.x} ${b.y}`,samples:[a,b],center:{x:(a.x+b.x)/2,y:(a.y+b.y)/2}};
    return null;
  }
  const t=cross(delta,tb)/determinant,u=cross(ta,delta)/determinant;
  if(t<0||u<0||Math.max(t,u)>span*3)return null;
  const control={x:a.x+ta.x*t,y:a.y+ta.y*t},samples=[];
  for(let i=0;i<=32;i++){const v=i/32,w=1-v;samples.push({x:w*w*a.x+2*w*v*control.x+v*v*b.x,y:w*w*a.y+2*w*v*control.y+v*v*b.y});}
  // One convex quadratic, not two curves pulled back to the old vertex.
  return {d:`M${a.x} ${a.y} Q${control.x} ${control.y} ${b.x} ${b.y}`,samples,center:samples[16],control};
}
function metroJoinCorridors(routes,positions,graph,style) {
  const ports=new Map(),degree=new Map();
  graph.edges.forEach(e=>[e.a,e.b].forEach(id=>degree.set(id,(degree.get(id)||0)+1)));
  routes.forEach((r,index)=>{
    r.trim=[0,0];
    [r.ids[0],r.ids.at(-1)].forEach((id,end)=>{
      const key=JSON.stringify([id,r.line]);
      if(!ports.has(key))ports.set(key,[]);
      ports.get(key).push({id,index,end});
    });
  });
  const joins=[];
  ports.forEach(pair=>{
    if(pair.length!==2||pair[0].index===pair[1].index)return; // branch or terminus
    const trim=Math.min(style.gap*0.65,...pair.map(port=>{
      const r=routes[port.index];
      const len=r.points.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p.x-r.points[i].x,p.y-r.points[i].y),0);
      return len/(r.ids.length-1)*0.35;
    }));
    if(trim<0.01)return;
    pair.forEach(port=>routes[port.index].trim[port.end]=trim);
    joins.push(pair);
  });
  const paths=routes.map(r=>({...metroRounded(metroTrim(r.points,...r.trim),style.gap*0.4),line:r.line}));
  const nodeCenters=new Map();
  joins.forEach(pair=>{
    const ends=pair.map(port=>{
      const route=paths[port.index],point=metroSampleAt(route.samples,port.end);
      return {point,t:{x:point.tx*(port.end?1:-1),y:point.ty*(port.end?1:-1)}};
    });
    const id=pair[0].id,original=positions[id],a=ends[0].point,b=ends[1].point;
    const offsets=pair.map(port=>{
      const r=routes[port.index],endpoint=port.end?r.points.at(-1):r.points[0];
      return {x:endpoint.x-original.x,y:endpoint.y-original.y};
    });
    // A non-branch station can sit on the rounded corner itself. Interchanges
    // with additional arms stay pinned, and every colour passes through it.
    const base=degree.get(id)===2?
      {x:original.x*0.5+(a.x+b.x-offsets[0].x-offsets[1].x)*0.25,y:original.y*0.5+(a.y+b.y-offsets[0].y-offsets[1].y)*0.25}:{x:original.x,y:original.y};
    // Keep each colour in its lane through the marker. Converging every line
    // to the node centre made a row of eye-shaped loops along shared corridors.
    const center={x:base.x+(offsets[0].x+offsets[1].x)/2,y:base.y+(offsets[0].y+offsets[1].y)/2};
    const outgoing={x:-ends[1].t.x,y:-ends[1].t.y};
    const corner=degree.get(id)===2?metroCornerJoin(a,ends[0].t,b,outgoing):null;
    const joined=corner||metroCubicJoin(a,ends[0].t,center,b,outgoing);
    if(corner){base.x=corner.center.x-(offsets[0].x+offsets[1].x)/2;base.y=corner.center.y-(offsets[0].y+offsets[1].y)/2;}
    if(!nodeCenters.has(id))nodeCenters.set(id,[]);nodeCenters.get(id).push(base);
    paths.push({...joined,line:routes[pair[0].index].line,join:id});
  });
  nodeCenters.forEach((points,id)=>Object.assign(positions[id],{x:points.reduce((s,p)=>s+p.x,0)/points.length,y:points.reduce((s,p)=>s+p.y,0)/points.length}));
  return paths;
}
function metroBounds(poly) {
  const xs=poly.map(p=>p.x),ys=poly.map(p=>p.y);
  return {x:Math.min(...xs),y:Math.min(...ys),w:Math.max(...xs)-Math.min(...xs),h:Math.max(...ys)-Math.min(...ys)};
}
function metroPolygonsOverlap(a,b) {
  if(!rectsOverlap(metroBounds(a),metroBounds(b)))return false;
  for(const poly of [a,b])for(let i=0;i<poly.length;i++){
    const p=poly[i],q=poly[(i+1)%poly.length],nx=-(q.y-p.y),ny=q.x-p.x;
    const aa=a.map(v=>v.x*nx+v.y*ny),bb=b.map(v=>v.x*nx+v.y*ny);
    if(Math.max(...aa)<=Math.min(...bb)||Math.max(...bb)<=Math.min(...aa))return false;
  }
  return true;
}
function metroBox(x,y,w,h) {return [{x,y},{x:x+w,y},{x:x+w,y:y+h},{x,y:y+h}];}
function metroCollisionIndex() {
  const bins=new Map(),size=150;
  const keys=poly=>{const b=metroBounds(poly),out=[];for(let x=Math.floor(b.x/size);x<=Math.floor((b.x+b.w)/size);x++)for(let y=Math.floor(b.y/size);y<=Math.floor((b.y+b.h)/size);y++)out.push(x+','+y);return out;};
  return {add(poly){keys(poly).forEach(key=>{if(!bins.has(key))bins.set(key,[]);bins.get(key).push(poly);});},
    collides(poly){const seen=new Set();for(const key of keys(poly))for(const other of bins.get(key)||[]){if(!seen.has(other)&&metroPolygonsOverlap(poly,other))return true;seen.add(other);}return false;}};
}
function metroMeasure(text,fs) {
  if(typeof document!=='undefined'&&document.createElement){
    const ctx=metroMeasure.context||(metroMeasure.context=document.createElement('canvas').getContext('2d'));
    if(ctx){ctx.font=`${fs}px "Microsoft YaHei","Segoe UI",sans-serif`;return ctx.measureText(text).width+5;}
  }
  return estTextWidth(text,fs)*1.12+5;
}
function metroPlaceLabels(graph,positions,paths,style,wanted,maxRing=3) {
  const index=metroCollisionIndex(),fs=style.font;
  Object.values(positions).forEach(p=>index.add(metroBox(p.x-p.r-3,p.y-p.r-3,p.r*2+6,p.r*2+6)));
  paths.forEach(path=>{
    const samples=path.samples;
    for(let i=1;i<samples.length;i++){
      const a=samples[i-1],b=samples[i],len=Math.hypot(b.x-a.x,b.y-a.y);if(!len)continue;
      const nx=-(b.y-a.y)/len*(style.line/2+3),ny=(b.x-a.x)/len*(style.line/2+3);
      index.add([{x:a.x+nx,y:a.y+ny},{x:b.x+nx,y:b.y+ny},{x:b.x-nx,y:b.y-ny},{x:a.x-nx,y:a.y-ny}]);
    }
  });
  const labels=[],unplaced=[];
  const sorted=[...wanted].sort((a,b)=>graph.nodes.get(b).lines.size-graph.nodes.get(a).lines.size||a.localeCompare(b));
  sorted.forEach(id=>{
    const p=positions[id],name=graph.nodes.get(id).name,w=metroMeasure(name,fs),off=p.r+7;
    let chosen=null,fallback=null;
    for(let ring=0;ring<maxRing&&!chosen;ring++){
      const dist=off+ring*(fs+8);
      const horizontal=Math.abs(p.tx)>0.85,tilt=horizontal&&w>style.gap*1.2;
      const candidates=horizontal?[
        ...(tilt?[[dist,-dist,-45],[-dist-w,dist+fs,-45]]:[]),
        [-w/2,-dist,0],[-w/2,dist+fs,0],[dist,-dist,0],[-dist-w,dist+fs,0]
      ]:[[dist,fs*0.32,0],[-dist-w,fs*0.32,0],[dist,-dist,0],[-dist-w,dist+fs,0],[-w/2,-dist,0],[-w/2,dist+fs,0]];
      for(const [dx,dy,angle] of candidates){
        const x=p.x+dx,y=p.y+dy,rad=angle*Math.PI/180,co=Math.cos(rad),si=Math.sin(rad);
        const poly=metroBox(-2,-fs*0.87,w+4,fs*1.15).map(q=>({x:x+q.x*co-q.y*si,y:y+q.x*si+q.y*co}));
        if(index.collides(poly))continue;
        let leaderPoly=null,leaderBlocked=false;
        if(ring>0){
          const box=metroBounds(poly),end={x:Math.max(box.x,Math.min(box.x+box.w,p.x)),y:Math.max(box.y,Math.min(box.y+box.h,p.y))};
          const dx=end.x-p.x,dy=end.y-p.y,len=Math.hypot(dx,dy),skip=p.r+style.line+5;
          if(len>skip){
            const start={x:p.x+dx/len*skip,y:p.y+dy/len*skip},nx=-dy/len,ny=dx/len;
            leaderPoly=[{x:start.x+nx,y:start.y+ny},{x:end.x+nx,y:end.y+ny},{x:end.x-nx,y:end.y-ny},{x:start.x-nx,y:start.y-ny}];
            leaderBlocked=index.collides(leaderPoly);
          }
        }
        const candidate={id,name,x,y,angle,poly,leader:ring>0,leaderBlocked};
        if(leaderBlocked){fallback ||= candidate;continue;}
        chosen=candidate;index.add(poly);if(leaderPoly)index.add(leaderPoly);break;
      }
    }
    if(!chosen&&fallback){chosen=fallback;index.add(chosen.poly);}
    if(chosen)labels.push(chosen);else unplaced.push(id);
  });
  return {labels,unplaced,leaderCrossings:labels.filter(l=>l.leaderBlocked).length};
}
function drawMetroDiagram(lines,stations) {
  const sourceLines=lines,mergeBranches=$('#map-merge-branches')?.checked!==false;
  lines=metroDisplayLines(lines,mergeBranches,state.mapBranchGroups||{});
  const graph=metroTopology(lines,stations),o=mapOpts(),canvas=$('#map-canvas');
  state.mapSvg=null;state.metroLayout=null;
  if(!graph.nodes.size){canvas.textContent='所选线路没有可用的车站坐标。';return;}
  const theme=$('#map-metro-theme')?.value==='atlas'?'atlas':'metro';
  const transferStyle=$('#map-transfer-style')?.value==='capsule'?'capsule':'circle';
  const grid=$('#map-metro-layout')?.value==='grid';
  const style={font:theme==='atlas'?Math.max(10,o.fontSize*0.82):o.fontSize,
    line:theme==='atlas'?Math.max(2,o.lineWidth*0.72):o.lineWidth,
    radius:(theme==='atlas'?3:4.2)*o.dotScale,gap:Math.max(42,o.gap)*(theme==='atlas'?0.84:1)};
  const ids=[...graph.nodes.keys()].sort(),meanLat=ids.reduce((s,id)=>s+graph.nodes.get(id).lat,0)/ids.length,k=Math.cos(meanLat*Math.PI/180);
  const raw={};ids.forEach(id=>{const n=graph.nodes.get(id);raw[id]={x:n.lon*k,y:-n.lat};});
  const layout=grid?metroGridLayout(graph,raw,style.gap):metroCorridorLayout(graph,raw,style.gap);
  const laneSigns=metroLaneSigns(layout.parts);
  const connected=new Set(layout.parts.flatMap(c=>c.ids));
  const isolated=ids.filter(id=>!connected.has(id));
  const linkedAnchors=Object.entries(layout.anchors).filter(([id])=>connected.has(id)).map(([,p])=>p);
  if(!grid&&linkedAnchors.length)isolated.forEach((id,i)=>{
    layout.anchors[id]={x:Math.min(...linkedAnchors.map(p=>p.x))-style.gap*2,y:Math.min(...linkedAnchors.map(p=>p.y))+i*style.gap};
  });
  const orientation=$('#map-metro-orientation')?.value || 'h',anchorBounds=metroBounds(Object.values(layout.anchors));
  const rotate=(orientation==='h'&&anchorBounds.h>anchorBounds.w)||(orientation==='v'&&anchorBounds.w>anchorBounds.h);
  if(rotate)Object.values(layout.anchors).forEach(p=>{const x=p.x;p.x=-p.y;p.y=x;});
  let baseRoutes;
  if(!grid){
    baseRoutes=metroRouteParts(layout.parts,layout.anchors,style.gap);
    baseRoutes=metroSeparateCorridors(layout.parts,baseRoutes,layout.anchors,style.gap);
  }
  const termini=new Set(sourceLines.flatMap(l=>[String(l.stops[0]),String(l.stops.at(-1))]));
  const wanted=ids.filter(id=>$('#map-all-labels').checked||termini.has(id)||graph.nodes.get(id).lines.size>1);
  let positions,paths,placement,expansion=1;
  for(let attempt=0;attempt<5;attempt++){
    expansion=1.4**attempt;positions={};paths=[];
    const routes=[];
    Object.entries(layout.anchors).forEach(([id,p])=>positions[id]={x:p.x*expansion,y:p.y*expansion,tx:0,ty:1,r:style.radius});
    const routedParts=grid?metroRouteParts(layout.parts,positions,style.gap,layout.gridStep*expansion):baseRoutes.map(points=>points.map(p=>({x:p.x*expansion,y:p.y*expansion})));
    layout.parts.forEach((c,partIndex)=>{
      const points=routedParts[partIndex];
      const central=metroRounded(points,grid?0:style.gap*0.4);
      c.ids.forEach((id,i)=>{
        const point=metroSampleAt(central.samples,i/(c.ids.length-1));
        const radius=graph.nodes.get(id).lines.size>1?Math.max(style.radius*1.85,(c.lines.length-1)*(style.line+2.5)/2+style.radius):style.radius;
        if(!positions[id]||!layout.anchors[id])positions[id]={...point,r:radius};
        else {positions[id].r=Math.max(positions[id].r,radius);}
        const score=c.lines.length*10000+c.ids.length;
        if(!positions[id].axisScore||score>positions[id].axisScore)Object.assign(positions[id],{tx:point.tx,ty:point.ty,axisScore:score});
      });
      c.lines.forEach((line,lane)=>{
        const offset=(lane-(c.lines.length-1)/2)*(style.line+2.5)*laneSigns[partIndex];
        routes.push({points:metroOffset(points,offset),line,ids:c.ids});
      });
    });
    paths=grid?routes.map(r=>({...metroRounded(r.points,0),line:r.line})):metroJoinCorridors(routes,positions,graph,style);
    // Expand the network before resorting to long, hard-to-follow leaders.
    placement=metroPlaceLabels(graph,positions,paths,style,wanted,attempt===4?32:6);
    if(!placement.unplaced.length&&(!placement.labels.some(l=>l.leaderBlocked)||attempt>=1))break;
  }
  placement.unplaced.forEach(id=>{
    const p=positions[id],name=graph.nodes.get(id).name,x=p.x+p.r+10,y=p.y-style.font;
    placement.labels.push({id,name,x,y,angle:0,poly:metroBox(x,y-style.font,metroMeasure(name,style.font),style.font*1.3),leader:true});
  });
  const contentPoints=[...Object.values(positions),...paths.flatMap(p=>p.samples),...placement.labels.flatMap(l=>l.poly)];
  const bounds=metroBounds(contentPoints),pad=54;
  const W=Math.max(o.width,bounds.w+pad*2),legendColumnWidth=Math.max(230,...lines.map(l=>metroMeasure(l.name,13)+70));
  const legendCols=Math.max(1,Math.floor((W-pad*2)/legendColumnWidth)),legendRows=Math.ceil(lines.length/legendCols);
  const header=125+legendRows*28,H=Math.max(o.height,bounds.h+header+pad+65);
  const dx=(W-bounds.w)/2-bounds.x,dy=header-bounds.y;
  const svg=metroEl('svg',{xmlns:SVG_NS,class:'transit-svg','data-map-style':'metro','data-metro-theme':theme,role:'img','aria-label':'地铁线网示意图',viewBox:`0 0 ${W} ${H}`});
  svg.appendChild(metroEl('rect',{width:W,height:H,fill:'#fff'}));
  const text=(x,y,value,fs=13,weight=400)=>metroEl('text',{x,y,fill:'#202b32','font-family':'Microsoft YaHei, Segoe UI, sans-serif','font-size':fs,'font-weight':weight},value);
  svg.appendChild(metroEl('rect',{x:pad,y:32,width:8,height:43,rx:2,fill:'#153d58'}));
  svg.appendChild(text(pad+22,61,theme==='atlas'?'铁路运营线路图':'地铁线网图',32,700));
  svg.appendChild(text(pad+23,84,theme==='atlas'?'RAIL NETWORK  /  SCHEMATIC ATLAS':'METRO NETWORK  /  SCHEMATIC MAP',11,600));
  lines.forEach((line,i)=>{
    const x=pad+(i%legendCols)*(W-pad*2)/legendCols,y=111+Math.floor(i/legendCols)*28;
    svg.appendChild(metroEl('path',{d:`M${x} ${y}h30`,stroke:lineColor(line.color),'stroke-width':style.line,'stroke-linecap':'round'}));
    svg.appendChild(text(x+40,y+4,line.name,13,600));
  });
  const group=metroEl('g',{transform:`translate(${dx} ${dy})`});svg.appendChild(group);
  paths.forEach(path=>{
    const p=metroEl('path',{d:path.d,stroke:lineColor(lines[path.line].color),'stroke-width':style.line,fill:'none','stroke-linecap':'round','stroke-linejoin':'round','data-line':String(lines[path.line].id),'data-source-lines':JSON.stringify(lines[path.line].source_ids),...(path.join?{'data-station-join':path.join}:{})});
    p.appendChild(metroEl('title',{},lines[path.line].name));group.appendChild(p);
  });
  ids.forEach(id=>{
    const p=positions[id],node=graph.nodes.get(id),transfer=node.lines.size>1;
    const attrs={fill:'#fff',stroke:'#26333b','stroke-width':transfer?2.4:1.7,'data-station':id,'data-transfer':transfer?'true':'false','data-marker':transfer?transferStyle:'circle','data-x':p.x,'data-y':p.y};
    let marker;
    if(transfer&&transferStyle==='capsule'){
      const width=p.r*2,height=style.radius*2.5,angle=Math.atan2(p.ty,p.tx)*180/Math.PI+90;
      marker=metroEl('rect',{...attrs,x:-width/2,y:-height/2,width,height,rx:height/2,ry:height/2,transform:`translate(${p.x} ${p.y}) rotate(${angle})`});
    }else marker=metroEl('circle',{...attrs,cx:p.x,cy:p.y,r:p.r});
    marker.appendChild(metroEl('title',{},node.name));group.appendChild(marker);
  });
  placement.labels.forEach(label=>{
    if(label.leader){
      const p=positions[label.id],b=metroBounds(label.poly),tx=Math.max(b.x,Math.min(b.x+b.w,p.x)),ty=Math.max(b.y,Math.min(b.y+b.h,p.y));
      group.appendChild(metroEl('path',{d:`M${p.x} ${p.y}L${tx} ${ty}`,fill:'none',stroke:'#88939b','stroke-width':0.6}));
    }
    const t=text(label.x,label.y,label.name,style.font,graph.nodes.get(label.id).lines.size>1?650:400);
    t.setAttribute('data-station-label',label.id);
    if(label.angle)t.setAttribute('transform',`rotate(${label.angle} ${label.x} ${label.y})`);
    t.setAttribute('paint-order','stroke');t.setAttribute('stroke','#fff');t.setAttribute('stroke-width',2);group.appendChild(t);
  });
  const footer=H-33;
  svg.appendChild(metroEl('path',{d:`M${pad} ${footer-23}H${W-pad}`,stroke:'#d6e0e5','stroke-width':1}));
  svg.appendChild(text(pad,footer,`○ 普通站    ${transferStyle==='capsule'?'胶囊形':'大圆'}：换乘站    示意图不按地理比例；无站点标记的交叉不表示换乘。`,12));
  if(graph.missing||placement.unplaced.length)svg.appendChild(text(pad,footer+21,`${graph.missing?`${graph.missing} 个站点引用缺坐标，已断开对应连接。`:''}${placement.unplaced.length?` ${placement.unplaced.length} 处站名仍较拥挤，请增加站间距或缩小字号。`:''}`,11));
  canvas.innerHTML='';canvas.appendChild(svg);state.mapSvg=svg;
  const absolute=Object.fromEntries(Object.entries(positions).map(([id,p])=>[id,{x:p.x+dx,y:p.y+dy}]));
  state.metroLayout={coordinate_space:'display-only',theme,layout:grid?'grid':'regular',merge_branches:mergeBranches,display_lines:lines.map(l=>({name:l.name,source_ids:l.source_ids,group_method:l.group_method})),grid_step:grid?layout.gridStep*expansion:null,grid_origin:grid?{x:dx,y:dy}:null,transfer_style:transferStyle,orientation,rotated:rotate,width:W,height:H,positions:absolute,
    label_count:placement.labels.length,label_conflicts:placement.unplaced.length,label_leader_crossings:placement.leaderCrossings,expansion,missing_references:graph.missing};
}
