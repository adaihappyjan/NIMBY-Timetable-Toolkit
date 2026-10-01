"""Local cartographic obstacle avoidance for NEW track only, not game validation."""
import math
import json
import time
from pathlib import Path
from collections import defaultdict

from toolkit_autoroute import tile_point, decode_request, game_maps

ROADS={'motorway','trunk','primary','secondary','tertiary','minor','service','track','path'}


def point_distance(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


def segment_distance(a,b,c,d):
    u=(b[0]-a[0],b[1]-a[1]);v=(d[0]-c[0],d[1]-c[1]);w=(c[0]-a[0],c[1]-a[1])
    cross=lambda x,y:x[0]*y[1]-x[1]*y[0]
    den=cross(u,v)
    if abs(den)>1e-12 and 0<=cross(w,v)/den<=1 and 0<=cross(w,u)/den<=1:return 0
    return min(point_distance(a,c,d),point_distance(b,c,d),point_distance(c,a,b),point_distance(d,a,b))


def inside(p,rings):
    # Even/odd parity preserves polygon holes and disjoint multipolygon rings.
    result=False
    for ring in rings:
        for a,b in zip(ring,ring[1:]+ring[:1]):
            if (a[1]>p[1])!=(b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:result=not result
    return result


def cells(a,b,padding):
    return [(x,y) for x in range(max(0,int((min(a[0],b[0])-padding)//4096)),min(16383,int((max(a[0],b[0])+padding)//4096))+1)
            for y in range(max(0,int((min(a[1],b[1])-padding)//4096)),min(16383,int((max(a[1],b[1])+padding)//4096))+1)]


def obstacle(feature,scale):
    layer=feature.get('layer');props=feature.get('properties',{});kind=props.get('class','')
    if layer=='transportation':
        if kind not in ROADS or props.get('subclass') in ('platform','steps','corridor'):return None
        reason='road';width=18 if kind in ('motorway','trunk','primary') else 12
    elif layer in ('water','waterway'):
        if kind=='swimming_pool':return None
        reason='water';width=6
    else:return None
    # An already grade-separated road/culvert is not a surface obstacle.
    if props.get('brunnel') or props.get('layer',0) not in (None,0,'0'):return None
    geometry=feature['geometry'];polygon=geometry['type'] in (2,5)
    if geometry['type'] not in (1,2,4,5):return None
    extent=feature['extent']
    if not isinstance(extent,(int,float)) or not math.isfinite(extent) or extent<=0:raise ValueError('障碍底图 extent 无效')
    rings=[[(feature['x']*4096+p['x']*4096/extent,feature['y']*4096+p['y']*4096/extent) for p in part] for part in geometry['coordinates']]
    rings=[p for p in rings if len(p)>=2]
    if not rings:return None
    flat=[p for ring in rings for p in ring]
    if any(not all(math.isfinite(v) for v in p) for p in flat):raise ValueError('障碍底图坐标无效')
    edges=[(a,b) for ring in rings for a,b in zip(ring,ring[1:]+(ring[:1] if polygon else []))]
    return {'reason':reason,'rings':rings,'edges':edges,'polygon':polygon,'padding':width/scale,
            'box':(min(p[0] for p in flat),min(p[1] for p in flat),max(p[0] for p in flat),max(p[1] for p in flat))}


def touches(a,b,o):
    r=o['padding'];west,north,east,south=o['box']
    if max(a[0],b[0])+r<west or min(a[0],b[0])-r>east or max(a[1],b[1])+r<north or min(a[1],b[1])-r>south:return False
    if o['polygon'] and (inside(a,o['rings']) or inside(b,o['rings'])):return True
    return any(segment_distance(a,b,c,d)<=r for c,d in o['edges'])


def apply_features(coords,levels,features,mode,*,deadline=None):
    if mode not in ('bridge','tunnel'):raise ValueError('避让模式无效')
    points=[tile_point(p) for p in coords]
    scale=40075016.686/(16384*4096)*math.cos(math.radians(sum(p[1] for p in coords)/len(coords)))
    by_tile=defaultdict(list)
    for feature in features:
        o=obstacle(feature,scale)
        if o:by_tile[(feature['x'],feature['y'])].append(o)
    changed=set();hits=[];target=2 if mode=='bridge' else 1
    for i,(a,b) in enumerate(zip(points,points[1:])):
        if deadline and time.monotonic()>deadline:raise ValueError('水域道路检查超过 120 秒，请分段')
        if levels[i]!=0 and levels[i+1]!=0:continue
        reasons=set()
        for cell in cells(a,b,20/scale):
            for o in by_tile[cell]:
                if o['reason'] not in reasons and touches(a,b,o):reasons.add(o['reason'])
        if reasons:
            changed.update(j for j in (i,i+1) if levels[j]==0)
            hits.append({'segment':i,'reasons':sorted(reasons),'length_m':round(math.dist(a,b)*scale,1)})
    return [target if i in changed else v for i,v in enumerate(levels)],{'changed_nodes':len(changed)*2,'segments':hits,
        'water_segments':sum('water' in h['reasons'] for h in hits),'road_segments':sum('road' in h['reasons'] for h in hits),
        'mode':mode,'game_validated':False}


def avoid(coords,levels,request):
    mode=request.get('obstacle_mode','off')
    if mode=='off':return levels,None
    if mode not in ('bridge','tunnel'):raise ValueError('请选择关闭、升高一格或降低一格')
    if request.get('structure_mode','auto')!='auto':raise ValueError('水域道路自动避让仅用于自动结构；强制结构时请关闭避让')
    paths=game_maps()
    if not request.get('map_path') and len(paths)!=1:raise ValueError('请为水域道路避让指定唯一的游戏底图')
    path=Path(request.get('map_path') or paths[0]).resolve()
    if not path.is_file() or path.name.lower()!='osm400.pmtiles':raise ValueError('水域道路避让需要游戏本地 osm400.pmtiles，请重新读取底图')
    before=path.stat();signature=(before.st_size,before.st_mtime_ns)
    deadline=time.monotonic()+120
    points=[tile_point(p) for p in coords]
    scale=40075016.686/(16384*4096)*min(math.cos(math.radians(p[1])) for p in coords)
    required=sorted({cell for a,b in zip(points,points[1:]) for cell in cells(a,b,20/scale)})
    if len(required)>4096:raise ValueError('沿线障碍检查超过 4096 个实际地图块，请分段')
    features=[];size=0;json_size=0
    for i in range(0,len(required),64):
        if time.monotonic()>=deadline:raise ValueError('水域道路检查超过 120 秒，请分段')
        decoded=decode_request({'path':str(path),'obstacles':True,'tiles':required[i:i+64]},timeout=max(.001,min(60,deadline-time.monotonic())))
        size+=decoded['bytesRead'];features.extend(decoded['features'])
        json_size+=len(json.dumps(decoded))
        if len(features)>100000 or size>256*1024*1024 or json_size>30_000_000:raise ValueError('沿线障碍数据过大，请分段')
    result,report=apply_features(coords,levels,features,mode,deadline=deadline)
    after=path.stat()
    if signature!=(after.st_size,after.st_mtime_ns):raise RuntimeError('障碍底图在读取期间变化，请重新预览全部区间')
    report.update(map_path=str(path),map_size=before.st_size,map_mtime_ns=before.st_mtime_ns,tiles=len(required))
    return result,report
