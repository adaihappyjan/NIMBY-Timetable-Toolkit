"""Bounded local railway routing; no network, straight-line fallback or save writes.

The game map is cartographic, not an authoritative topological/engineering graph.
Only coincident vertices and very close compatible endpoints are joined; crossings
are never intersected to manufacture junctions. A route still needs game review.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent
N=16384*4096
RAIL_TYPES={'rail','light_rail','subway','tram','narrow_gauge','monorail','funicular'}


def game_maps():
    roots=[]
    if os.name=='nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam') as key:
                roots.append(Path(winreg.QueryValueEx(key,'SteamPath')[0]))
        except OSError:
            pass
        roots += [Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Steam']
        roots += [Path(f'{d}:/SteamLibrary') for d in 'CDEFGHIJKLMNOPQRSTUVWXYZ']
    else:
        roots += [Path.home()/'.steam/steam',Path.home()/'.local/share/Steam',Path.home()/'Library/Application Support/Steam']
    for root in list(roots):
        library=root/'steamapps/libraryfolders.vdf'
        if library.is_file():
            roots += [Path(p.replace('\\\\','\\')) for p in re.findall(r'"path"\s+"([^"]+)"',library.read_text('utf-8',errors='replace'))]
    found=[]
    for root in roots:
        path=root/'steamapps/common/NIMBY Rails/resources/maps/osm400.pmtiles'
        if path.is_file() and str(path.resolve()) not in found:found.append(str(path.resolve()))
    return found


def node_runtime():
    # Optional private runtime may be supplied by portable distributors.
    for p in (Path(sys.executable).parent.parent/'node.exe',ROOT/'runtime/node.exe',ROOT/'runtime/node',Path(os.environ.get('ProgramFiles','C:/Program Files'))/'nodejs/node.exe'):
        if p.is_file():return str(p)
    return shutil.which('node')


def tile_point(point):
    lon,lat=map(float,point)
    if not math.isfinite(lon+lat) or not -180<lon<180 or not -80<lat<80:raise ValueError('站点坐标超出可用地图范围（纬度 ±80°）')
    return ((lon+180)/360*N,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*N)


def lonlat(p):
    return [p[0]/N*360-180,math.degrees(math.atan(math.sinh(math.pi*(1-2*p[1]/N))))]


def bounds_for(a,b,padding_m):
    scale=40075016.686/N*math.cos(math.radians((a[1]+b[1])/2))
    p,q=tile_point(a),tile_point(b)
    distance=math.dist(p,q)*scale
    if abs(a[0]-b[0])>180:raise ValueError('不支持跨日期线，请选择不跨日期线的区间')
    if distance<100:raise ValueError('两站直线距离须至少 0.1 公里')
    pad=padding_m/scale
    return [max(0,int((min(p[0],q[0])-pad)//4096)),max(0,int((min(p[1],q[1])-pad)//4096)),
            min(16383,int((max(p[0],q[0])+pad)//4096)),min(16383,int((max(p[1],q[1])+pad)//4096))]


def decode(path,bounds):
    runtime=node_runtime()
    if not runtime:raise ValueError('自动读取底图需要 Node.js 22 或更新版。安装后重开工具箱；本地 GeoJSON 路线仍可使用。')
    # Fixed bundled program, no shell, no user-supplied executable or script.
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    try:
        proc=subprocess.run([runtime,'--max-old-space-size=512',str(ROOT/'third_party/autotrack/tiles.mjs')],
            input=json.dumps({'path':str(path),'bounds':bounds}),capture_output=True,text=True,encoding='utf-8',timeout=90,**options)
    except subprocess.TimeoutExpired as exc:raise ValueError('底图读取超过 90 秒，请缩小区间') from exc
    if proc.returncode:raise ValueError('底图解码失败：'+proc.stderr[-1600:])
    if len(proc.stdout)>30_000_000:raise ValueError('底图结果过大，请分段')
    return json.loads(proc.stdout)


def clip(a,b,box):
    lo,hi=0.,1.
    for value,delta,mn,mx in ((a[0],b[0]-a[0],box[0],box[2]),(a[1],b[1]-a[1],box[1],box[3])):
        if abs(delta)<1e-12:
            if not mn<=value<=mx:return None
        else:
            t,u=sorted(((mn-value)/delta,(mx-value)/delta));lo=max(lo,t);hi=min(hi,u)
            if lo>=hi:return None
    return tuple(a[i]+(b[i]-a[i])*lo for i in (0,1)),tuple(a[i]+(b[i]-a[i])*hi for i in (0,1))


def projection(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return t,(a[0]+dx*t,a[1]+dy*t)


def route_graph(features,start,end,rail_type='auto'):
    if rail_type!='auto' and rail_type not in RAIL_TYPES:raise ValueError('未知铁路线路类型')
    nodes=[];buckets=defaultdict(list);edges=[];seen=set()
    # Endpoint snapping <= 2 z14 tile units, under 1.2 m even at equator.
    def vertex(p,props,terminal):
        layer=props.get('layer') or 0
        signature=(props.get('subclass'),layer,props.get('brunnel') or '')
        cell=(math.floor(p[0]/2),math.floor(p[1]/2))
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for i in buckets[(cell[0]+dx,cell[1]+dy)]:
                    q,sig,term=nodes[i]
                    # Different structures may meet only at feature ends, same rail family.
                    compatible=sig==signature or (term and terminal and sig[0]==signature[0] and bool(sig[2])!=bool(signature[2]) and abs(float(sig[1])-float(signature[1]))<=1)
                    if compatible and math.dist(p,q)<=(2 if term and terminal else 1e-6):return i
        i=len(nodes);nodes.append((p,signature,terminal));buckets[cell].append(i);return i
    for feature in features:
        props=feature.get('properties',{})
        if props.get('subclass') not in RAIL_TYPES or (rail_type!='auto' and props.get('subclass')!=rail_type):continue
        if props.get('brunnel') not in (None,'','bridge','viaduct','movable','tunnel'):continue
        extent=feature['extent'];x,y=feature['x'],feature['y']
        if not isinstance(extent,(int,float)) or extent<=0:raise ValueError('底图 extent 无效')
        box=(x*4096,y*4096,(x+1)*4096,(y+1)*4096)
        for part in feature['geometry']['coordinates']:
            points=[((x+p['x']/extent)*4096,(y+p['y']/extent)*4096) for p in part]
            for j,(a,b) in enumerate(zip(points,points[1:])):
                pair=clip(a,b,box)
                if pair is None or math.dist(*pair)<1e-6:continue
                p,q=pair
                u=vertex(p,props,j==0 or math.dist(p,a)>1e-6)
                v=vertex(q,props,j==len(points)-2 or math.dist(q,b)>1e-6)
                key=(min(u,v),max(u,v),props.get('brunnel') or '')
                if u!=v and key not in seen:
                    edges.append((u,v,props));seen.add(key)
    if not edges:raise ValueError('此范围没有所选类型的铁路底图；不会以直线代替')
    scale=40075016.686/N*math.cos(math.radians((start[1]+end[1])/2))
    splits=defaultdict(list);snap=[];terminals=[]
    for endpoint in (start,end):
        p=tile_point(endpoint)
        choices=[]
        for idx,(u,v,props) in enumerate(edges):
            t,q=projection(p,nodes[u][0],nodes[v][0]);choices.append((math.dist(p,q),idx,t,q))
        distance,idx,t,q=min(choices)
        # A station/waypoint rounded to decimal degrees may project a fraction
        # of a millimetre beside an existing vertex. Reuse that vertex instead
        # of emitting a tiny extra segment rejected by the blueprint writer.
        u,v,_=edges[idx]
        if math.dist(q,nodes[u][0])*scale<0.05:
            t,q=0,nodes[u][0]
        elif math.dist(q,nodes[v][0])*scale<0.05:
            t,q=1,nodes[v][0]
        distance=math.dist(p,q)
        if distance*scale>500:raise ValueError(f'站点离所选铁路约 {distance*scale:.0f} 米，超过 500 米；请选择对应线路类型或准确坐标')
        node=len(nodes);nodes.append((q,(),True));splits[idx].append((t,node));terminals.append(node);snap.append(round(distance*scale,1))
    adj=defaultdict(list)
    for idx,(u,v,props) in enumerate(edges):
        sequence=sorted([(0,u),(1,v)]+splits[idx])
        for (_,a),(_,b) in zip(sequence,sequence[1:]):
            distance=math.dist(nodes[a][0],nodes[b][0])
            adj[a].append((b,distance,props));adj[b].append((a,distance,props))
    source,target=terminals;cost={source:0};previous={};queue=[(0,source)]
    while queue:
        distance,node=heapq.heappop(queue)
        if distance!=cost.get(node):continue
        if node==target:break
        for neighbor,length,props in adj[node]:
            candidate=distance+length
            if candidate<cost.get(neighbor,float('inf')):
                cost[neighbor]=candidate;previous[neighbor]=(node,props);heapq.heappush(queue,(candidate,neighbor))
    if target not in cost:raise ValueError('两站之间没有连续铁路路径：可能底图断线、类型不一致或路线绕出范围；不会画直线代替')
    order=[target];properties=[]
    while order[-1]!=source:
        before,props=previous[order[-1]];order.append(before);properties.append(props)
    order.reverse();properties.reverse()
    # Collapse zero-length virtual splits; retain every structural transition.
    coords=[lonlat(nodes[order[0]][0])];structures=[];classes=set()
    for a,b,props in zip(order,order[1:],properties):
        length=math.dist(nodes[a][0],nodes[b][0])*scale
        if length<1e-5:continue
        p,q=nodes[a][0],nodes[b][0];parts=max(1,math.ceil(length/1500))
        first=coords[-1]
        for i in range(1,parts+1):coords.append(lonlat(tuple(p[k]+(q[k]-p[k])*i/parts for k in (0,1))))
        brunnel=props.get('brunnel');classes.add(props.get('subclass'))
        if brunnel:
            if structures and structures[-1]['properties']['brunnel']==brunnel and structures[-1]['geometry']['coordinates'][-1]==first:
                structures[-1]['geometry']['coordinates'].append(coords[-1])
            else:structures.append({'type':'Feature','properties':{'kind':'structure','brunnel':brunnel},'geometry':{'type':'LineString','coordinates':[first,coords[-1]]}})
    data={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'kind':'reference_alignment'},'geometry':{'type':'LineString','coordinates':coords}}]+structures}
    return data,{'snap_m':snap,'rail_types':sorted(classes),'route_length_m':round(cost[target]*scale,1)}


def choose_route(features,start,end,rail_type='auto'):
    try:return route_graph(features,start,end,rail_type)
    except ValueError as original:
        if rail_type!='auto' or '没有连续铁路路径' not in str(original):raise
        # A metro and an adjacent regional line may be closer at opposite ends.
        # Retry a common family, never fabricate a link between those networks.
        candidates=[]
        for kind in sorted({f.get('properties',{}).get('subclass') for f in features} & RAIL_TYPES):
            try:
                data,info=route_graph(features,start,end,kind)
                score=(max(info['snap_m']),sum(info['snap_m']),info['route_length_m'],kind)
                candidates.append((score,data,info))
            except ValueError:continue
        if not candidates:raise original
        _,data,info=min(candidates,key=lambda c:c[0])
        info['auto_family_fallback']=True
        return data,info


def automatic_route(request,stations):
    endpoints=[]
    for key in ('from','to'):
        ident=request.get(key+'_station')
        if ident:
            found=[s for s in stations if s['id']==ident]
            if len(found)!=1:raise ValueError('所选站点不在当前存档，请重新自动读取')
            endpoints.append([found[0]['lon'],found[0]['lat']])
        else:
            point=request.get(key+'_coord')
            if not isinstance(point,list) or len(point)!=2:raise ValueError('请选择起终站，或填写经度、纬度')
            tile_point(point);endpoints.append(point)
    paths=game_maps()
    requested=request.get('map_path')
    if requested:
        p=Path(requested).resolve()
        if p.name.lower()!='osm400.pmtiles' or not p.is_file():raise ValueError('底图须为游戏本地 osm400.pmtiles 文件')
    elif len(paths)==1:p=Path(paths[0])
    else:raise ValueError('未找到唯一游戏底图，请在底图路径栏指定 osm400.pmtiles')
    before=p.stat();signature=(before.st_size,before.st_mtime_ns)
    last=None
    for padding in (3000,8000):
        bounds=bounds_for(*endpoints,padding)
        if (bounds[2]-bounds[0]+1)*(bounds[3]-bounds[1]+1)>1024:
            if last:raise last
            raise ValueError('两站范围超过 1024 瓦片，请增加中间站分段生成')
        decoded=decode(p,bounds)
        try:
            data,info=choose_route(decoded['features'],*endpoints,request.get('rail_type','auto'))
            after=p.stat()
            if signature!=(after.st_size,after.st_mtime_ns):raise ValueError('游戏底图在读取期间改变，请重试')
            info.update(map_path=str(p),map_size=before.st_size,map_mtime_ns=before.st_mtime_ns,tiles=decoded['tiles'],bytes_read=decoded['bytesRead'],search_padding_m=padding)
            return data,info
        except ValueError as exc:
            if '没有连续铁路路径' not in str(exc):raise
            last=exc
    raise last
