// Local-only PMTiles/MLT decoder. Bundled for distribution; never fetches URLs.
import fs from 'node:fs';
import {PMTiles} from 'pmtiles';
import {decodeTile} from '@maplibre/mlt';

const input=JSON.parse(fs.readFileSync(0,'utf8'));
const [west,north,east,south]=input.bounds;
if (![west,north,east,south].every(Number.isInteger) || west<0 || north<0 || east>=16384 || south>=16384 || east<west || south<north || (east-west+1)*(south-north+1)>1024) throw Error('读取范围超过 1024 个瓦片，请分段');
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
  const features=[];let tiles=0;
  for(let x=west;x<=east;x++)for(let y=north;y<=south;y++){
    const tile=await reader.getZxy(14,x,y);if(!tile)continue;tiles++;
    for(const table of decodeTile(new Uint8Array(tile.data))){
      if(table.name!=='transportation')continue;
      for(const feature of table.getFeatures()){
        const p=feature.properties;
        if(!['rail','light_rail','subway','tram','narrow_gauge','monorail','funicular'].includes(p.subclass))continue;
        features.push({x,y,extent:table.extent,properties:{subclass:p.subclass,brunnel:p.brunnel,layer:p.layer,service:p.service},geometry:feature.geometry});
        if(features.length>100000)throw Error('区域路网过密，请缩小区间');
      }
    }
  }
  process.stdout.write(JSON.stringify({features,tiles,bytesRead},(_,v)=>typeof v==='bigint'?String(v):v));
} finally { fs.closeSync(fd); }
