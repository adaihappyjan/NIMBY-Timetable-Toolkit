// Local-only PMTiles/MLT decoder. Bundled for distribution; never fetches URLs.
import fs from 'node:fs';
import {PMTiles} from 'pmtiles';
import {decodeTile} from '@maplibre/mlt';
import {TileFrontier} from './autotrack/frontier.mjs';

const input=JSON.parse(fs.readFileSync(0,'utf8'));
const families=['rail','light_rail','subway','tram','narrow_gauge','monorail','funicular'];
const validTile=p=>Array.isArray(p)&&p.length===2&&p.every(v=>Number.isInteger(v)&&v>=0&&v<16384);
const key=p=>p.join(',');
const follow=input.follow===true;
const obstacles=input.obstacles===true;
let pending=[],visited=new Set(),anchors=[];
const limit=follow?input.limit:1024;
if(follow){
  if(!Number.isInteger(limit)||limit<1||limit>1024||!Array.isArray(input.tiles)||input.tiles.length>16384||!input.tiles.every(validTile)||
     !Array.isArray(input.visited)||input.visited.length>16384||!input.visited.every(validTile)||
     !Array.isArray(input.anchors)||input.anchors.length!==2||!input.anchors.every(validTile)||
     !['auto',...families].includes(input.railType))throw Error('铁路分块搜索参数无效');
  visited=new Set(input.visited.map(key));anchors=input.anchors;
  pending=input.tiles.filter(p=>!visited.has(key(p)));
}else if(obstacles){
  if(!Array.isArray(input.tiles)||input.tiles.length>1024||!input.tiles.every(validTile))throw Error('障碍读取范围无效');
  pending=input.tiles;
}else{
  const [west,north,east,south]=input.bounds;
  if (![west,north,east,south].every(Number.isInteger) || west<0 || north<0 || east>=16384 || south>=16384 || east<west || south<north || (east-west+1)*(south-north+1)>1024) throw Error('读取范围超过 1024 个瓦片，请分段');
  for(let x=west;x<=east;x++)for(let y=north;y<=south;y++)pending.push([x,y]);
}
const queued=new Set(pending.map(key));pending=[...queued].map(k=>k.split(',').map(Number));
if(follow)pending=new TileFrontier(pending,anchors);
function enqueue(p){if(validTile(p)&&!visited.has(key(p))&&!queued.has(key(p))){pending.push(p);queued.add(key(p));}}
// Tile-level exploration only. This never creates a track edge or a junction:
// the Python graph still verifies exact compatible track continuity afterwards.
function exits(geometry,extent,x,y){
  for(const part of geometry.coordinates)for(let i=1;i<part.length;i++){
    const a=[part[i-1].x/extent*4096,part[i-1].y/extent*4096],b=[part[i].x/extent*4096,part[i].y/extent*4096];
    let lo=0,hi=1;
    for(let k=0;k<2;k++){
      const d=b[k]-a[k];
      if(Math.abs(d)<1e-12){if(a[k]<0||a[k]>4096){hi=-1;break;}}
      else{const ts=[-a[k]/d,(4096-a[k])/d].sort((u,v)=>u-v);lo=Math.max(lo,ts[0]);hi=Math.min(hi,ts[1]);}
    }
    if(lo>=hi)continue;
    for(const t of [lo,hi]){
      const p=a.map((v,k)=>v+(b[k]-v)*t),dx=[0],dy=[0];
      if(p[0]<=2)dx.push(-1);if(p[0]>=4094)dx.push(1);
      if(p[1]<=2)dy.push(-1);if(p[1]>=4094)dy.push(1);
      for(const u of dx)for(const v of dy)if(u||v)enqueue([x+u,y+v]);
    }
  }
}
const fd=fs.openSync(input.path,'r'), size=fs.fstatSync(fd).size;
let bytesRead=0;
const source={getKey:()=>input.path,async getBytes(offset,length){
  if(!Number.isSafeInteger(offset)||!Number.isSafeInteger(length)||offset<0||length<0||length>32*1024*1024||offset+length>size)throw Error('底图索引范围无效');
  bytesRead+=length;if(bytesRead>256*1024*1024)throw Error('本次底图读取超过 256 MB，请缩小范围');
  const data=Buffer.alloc(length);if(fs.readSync(fd,data,0,length,offset)!==length)throw Error('底图读取不完整');
  return {data:data.buffer};
}};
try {
  const reader=new PMTiles(source), header=await reader.getHeader();
  if(header.tileType!==6||header.maxZoom<14)throw Error('需要游戏的 z14 MLT 矢量底图（osm400.pmtiles）');
  const features=[],inspected=[];let tiles=0;
  while(pending.length&&inspected.length<limit){
    const [x,y]=pending.pop();queued.delete(key([x,y]));visited.add(key([x,y]));inspected.push([x,y]);
    const tile=await reader.getZxy(14,x,y);if(!tile)continue;tiles++;
    for(const table of decodeTile(new Uint8Array(tile.data))){
      if(!['transportation',...(obstacles?['water','waterway']:[])].includes(table.name))continue;
      for(const feature of table.getFeatures()){
        const p=feature.properties;
        if(obstacles){
          if(table.name==='transportation'&&(families.includes(p.subclass)||p.class==='rail'))continue;
          features.push({x,y,extent:table.extent,layer:table.name,properties:p,geometry:feature.geometry});
          if(features.length>100000)throw Error('障碍要素过多，请分段');
          continue;
        }
        if(!families.includes(p.subclass))continue;
        if(follow&&(input.railType!=='auto'&&p.subclass!==input.railType))continue;
        if(follow&&![undefined,null,'','bridge','viaduct','movable','tunnel'].includes(p.brunnel))continue;
        features.push({x,y,extent:table.extent,properties:{subclass:p.subclass,brunnel:p.brunnel,layer:p.layer,service:p.service},geometry:feature.geometry});
        if(follow)exits(feature.geometry,table.extent,x,y);
        if(features.length>100000)throw Error('区域路网过密，请缩小区间');
      }
    }
  }
  process.stdout.write(JSON.stringify({features,tiles,bytesRead,...(follow?{inspected,frontier:pending.tiles()}: {})},(_,v)=>typeof v==='bigint'?String(v):v));
} finally { fs.closeSync(fd); }
