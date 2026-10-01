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
import time
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent
N=16384*4096
RAIL_TYPES={'rail','light_rail','subway','tram','narrow_gauge','monorail','funicular'}
SEARCH_PADDINGS=(3000,8000,16000,32000)
MAX_SEARCH_TILES=4096
MAX_SEARCH_FEATURES=100000
MAX_SEARCH_BYTES=256*1024*1024
MAX_SEARCH_JSON=30_000_000
SEARCH_SECONDS=120
MAX_NETWORK_TILES=16384
NETWORK_SEARCH_SECONDS=240


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


def decode(path,bounds,*,timeout=90):
    return decode_request({'path':str(path),'bounds':bounds},timeout=timeout)


def decode_request(request,*,timeout=90):
    runtime=node_runtime()
    if not runtime:raise ValueError('自动读取底图需要 Node.js 22 或更新版。安装后重开工具箱；本地 GeoJSON 路线仍可使用。')
    # Fixed bundled program, no shell, no user-supplied executable or script.
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    try:
        proc=subprocess.run([runtime,'--max-old-space-size=512',str(ROOT/'third_party/autotrack/tiles.mjs')],
            input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=timeout,**options)
    except subprocess.TimeoutExpired as exc:raise ValueError('底图读取超时，请增加中间站分段生成') from exc
    if proc.returncode:raise ValueError('底图解码失败：'+proc.stderr[-1600:])
    if len(proc.stdout)>30_000_000:raise ValueError('底图结果过大，请分段')
    return json.loads(proc.stdout)


def network_route(path,endpoints,rail_type='auto',progress=None):
    """Explore railway-bearing tile borders, then verify the actual track graph.

    Coarse tile adjacency is only a read hint: neither geometric crossings nor
    missing map links are joined. Work is bounded by actual inspected tiles.
    """
    if rail_type!='auto' and rail_type not in RAIL_TYPES:raise ValueError('未知铁路线路类型')
    before=path.stat();signature=(before.st_size,before.st_mtime_ns)
    anchors=[tuple(int(v//4096) for v in tile_point(p)) for p in endpoints]
    seeds=set()
    for point in endpoints:
        p=tile_point(point);scale=40075016.686/N*math.cos(math.radians(point[1]))
        # Include the whole 500 m endpoint snap neighbourhood and seam halo.
        radius=500/scale+2
        for x in range(max(0,int((p[0]-radius)//4096)),min(16383,int((p[0]+radius)//4096))+1):
            for y in range(max(0,int((p[1]-radius)//4096)),min(16383,int((p[1]+radius)//4096))+1):seeds.add((x,y))
    frontier=sorted(seeds);visited=set();features=[];tiles=0;bytes_read=0;json_size=0;batches=0
    deadline=time.monotonic()+NETWORK_SEARCH_SECONDS
    def check_inputs():
        current=path.stat()
        if signature!=(current.st_size,current.st_mtime_ns):raise ValueError('游戏底图在读取期间改变，请重试')
        if time.monotonic()>=deadline:raise ValueError('沿铁路分块寻路超过 240 秒；尚不能判断铁路是否连通，请增加途经站分段生成')
    last=None;next_graph_at=256;graph_attempts=0
    while frontier:
        check_inputs()
        remaining=MAX_NETWORK_TILES-len(visited)
        if remaining<=0:raise ValueError('沿铁路搜索已达到实际地图块处理上限；尚不能判断铁路是否连通，请增加途经站分段生成')
        if progress:progress(len(visited),MAX_NETWORK_TILES,f'沿铁路分块寻路：已检查 {len(visited)} 个地图块，待探索 {len(frontier)} 处；此为处理量，不是完成百分比…')
        decoded=decode_request({'path':str(path),'follow':True,'tiles':frontier,'visited':sorted(visited),
                                'anchors':anchors,'railType':rail_type,'limit':min(256,remaining)},
                               timeout=max(0.001,min(90,deadline-time.monotonic())))
        check_inputs()
        inspected={tuple(p) for p in decoded['inspected']}
        if not inspected or inspected & visited:raise ValueError('底图分块读取未推进或重复，请重试')
        visited.update(inspected);frontier=decoded['frontier']
        bytes_read+=decoded['bytesRead'];json_size+=len(json.dumps(decoded,ensure_ascii=False))
        if bytes_read>MAX_SEARCH_BYTES or json_size>MAX_SEARCH_JSON or len(features)+len(decoded['features'])>MAX_SEARCH_FEATURES:
            raise ValueError('累计底图数据过大，请增加中间站分段生成；尚不能判断铁路是否连通')
        features.extend(decoded['features']);tiles+=decoded['tiles'];batches+=1
        # Both endpoint neighbourhoods must have been read before trying snap.
        if not seeds<=visited:continue
        # Check frequently near the endpoints, then back off rebuilds as the
        # search grows. Always check the last batch, even below the threshold.
        if frontier and len(visited)<next_graph_at and len(visited)<MAX_NETWORK_TILES:continue
        graph_attempts+=1
        next_graph_at=len(visited)+max(256,len(visited)//2)
        try:
            data,info=choose_route(features,*endpoints,rail_type)
            check_inputs()
            info.update(map_path=str(path),map_size=before.st_size,map_mtime_ns=before.st_mtime_ns,
                        tiles=tiles,bytes_read=bytes_read,searched_tiles=len(visited),decode_batches=batches,
                        graph_attempts=graph_attempts,
                        search_method='railway-frontier')
            return data,info
        except ValueError as exc:
            if '没有连续铁路路径' not in str(exc):raise
            last=exc
    raise ValueError('已沿可见铁路探索，仍未找到连续铁路路径；底图可能缺少连接或站点贴合了不同支线，不会画直线补连') from last


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


def stitch_tile_seams(nodes,edges,seams):
    """Correct quantisation seams, not real-world railway gaps.

    Require opposing adjacent tile sides, identical type/layer/structure,
    near-collinear tangents and a unique, reciprocal continuation. For shallow
    border crossings, <=8 units along the border are allowed ONLY when lateral
    error against BOTH tangents is <=1 unit and heading differs by <=3 degrees.
    Normal feature endpoints retain the stricter 2-unit rule.
    """
    groups=defaultdict(list);matches=defaultdict(set)
    for node,axis,border,side,tile,tangent in seams:
        p=nodes[node][0];cell=math.floor(p[1-axis]/8)
        for offset in (-1,0,1):
            for other,other_side,other_tile,other_tangent in groups[(axis,border,cell+offset)]:
                if node==other or side==other_side or abs(tile[0]-other_tile[0])+abs(tile[1]-other_tile[1])!=1:continue
                q=nodes[other][0]
                distance=math.dist(p,q)
                if nodes[node][1]!=nodes[other][1] or distance>8:continue
                dot=sum(a*b for a,b in zip(tangent,other_tangent))
                if dot>-math.cos(math.radians(15)):continue
                if distance>3:
                    delta=(q[0]-p[0],q[1]-p[1])
                    lateral=max(abs(delta[0]*t[1]-delta[1]*t[0]) for t in (tangent,other_tangent))
                    if lateral>1 or dot>-math.cos(math.radians(3)):continue
                matches[node].add(other);matches[other].add(node)
        groups[(axis,border,cell)].append((node,side,tile,tangent))
    parent={};joined=0
    def root(n):
        while n in parent:n=parent[n]
        return n
    for node,others in sorted(matches.items()):
        if len(others)!=1:continue
        other=next(iter(others))
        if matches[other]!={node}:continue
        a,b=root(node),root(other)
        if a!=b:parent[max(a,b)]=min(a,b);joined+=1
    return [(root(a),root(b),props) for a,b,props in edges if root(a)!=root(b)],joined


def compact_alignment(coords,structures,scale):
    """Drop numerically collinear points (<=0.01 mm); keep structures.

    No curve straightening to meet a point quota: every removal must satisfy
    the same small geometric tolerance and 1500 m maximum edge independently.
    """
    protected={tuple(p) for f in structures for p in f['geometry']['coordinates']}
    # Exact collinearity avoids accumulating lateral drift along curved track.
    points=[tile_point(p) for p in coords];keep=[]
    for i,p in enumerate(points):
        while len(keep)>=2 and tuple(coords[keep[-1]]) not in protected:
            a,b=points[keep[-2]],points[keep[-1]]
            if math.dist(a,p)*scale>1500 or math.dist(a,p)<1e-9:break
            t,q=projection(b,a,p)
            if not 0<t<1 or math.dist(q,b)*scale>1e-5:break
            keep.pop()
        keep.append(i)
    return [coords[i] for i in keep]


def stitch_structure_tips(nodes,edges):
    """Join an explicit bridge/tunnel end to an exact ground turnaround vertex.

    Cartographic lines may fold two parallel approaches into one polyline at
    a bridge head, so the shared vertex is not a feature endpoint. Require a
    unique compatible ground vertex and ALL incident directions to oppose the
    structure by <=15 degrees. A through line/crossing necessarily fails this
    test. Never project onto an edge or stretch a gap to invent a junction.
    """
    adjacent=defaultdict(set);ground=defaultdict(list)
    for a,b,_ in edges:adjacent[a].add(b);adjacent[b].add(a)
    for i in adjacent:
        if not nodes[i][1][2]:ground[nodes[i][0]].append(i)
    parent={};joined=0;threshold=-math.cos(math.radians(15))
    def directions(i):
        p=nodes[i][0];result=[]
        for j in adjacent[i]:
            q=nodes[j][0];length=math.dist(p,q)
            if length<=1e-6:return []
            result.append(((q[0]-p[0])/length,(q[1]-p[1])/length))
        return result
    for i in adjacent:
        p,sig,terminal=nodes[i]
        if not sig[2] or not terminal:continue
        choices=[j for j in ground[p] if nodes[j][1][0]==sig[0]
                 and abs(float(nodes[j][1][1])-float(sig[1]))<=1]
        if len(choices)!=1:continue
        j=choices[0];left,right=directions(i),directions(j)
        if left and right and all(a[0]*b[0]+a[1]*b[1]<=threshold for a in left for b in right):
            parent[i]=j;joined+=1
    return [(parent.get(a,a),parent.get(b,b),p) for a,b,p in edges
            if parent.get(a,a)!=parent.get(b,b)],joined


def route_graph(features,start,end,rail_type='auto'):
    if rail_type!='auto' and rail_type not in RAIL_TYPES:raise ValueError('未知铁路线路类型')
    nodes=[];buckets=defaultdict(list);edges=[];seen=set();seams=[]
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
                for node,tip,inside in ((u,p,q),(v,q,p)):
                    length=math.dist(tip,inside)
                    tangent=tuple((inside[k]-tip[k])/length for k in (0,1))
                    for axis in (0,1):
                        for side,border in ((1,box[axis]),(-1,box[axis+2])):
                            if abs(tip[axis]-border)<1e-6:seams.append((node,axis,int(border//4096),side,(x,y),tangent))
                key=(min(u,v),max(u,v),props.get('brunnel') or '')
                if u!=v and key not in seen:
                    edges.append((u,v,props));seen.add(key)
    if not edges:raise ValueError('此范围没有所选类型的铁路底图；不会以直线代替')
    edges,seam_joins=stitch_tile_seams(nodes,edges,seams)
    edges,structure_joins=stitch_structure_tips(nodes,edges)
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
    coords=compact_alignment(coords,structures,scale)
    data={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'kind':'reference_alignment'},'geometry':{'type':'LineString','coordinates':coords}}]+structures}
    return data,{'snap_m':snap,'rail_types':sorted(classes),'route_length_m':round(cost[target]*scale,1),
                'tile_seam_joins':seam_joins,'structure_tip_joins':structure_joins}


def choose_route(features,start,end,rail_type='auto'):
    try:return route_graph(features,start,end,rail_type)
    except ValueError as original:
        if rail_type!='auto' or '没有连续铁路路径' not in str(original):raise
        # A metro and an adjacent regional line may be closer at opposite ends.
        # Retry a common family, never fabricate a link between those networks.
        candidates=[]
        families=sorted({f.get('properties',{}).get('subclass') for f in features} & RAIL_TYPES)
        if len(families)<2:raise original  # The sole-family graph is identical.
        for kind in families:
            try:
                data,info=route_graph(features,start,end,kind)
                score=(max(info['snap_m']),sum(info['snap_m']),info['route_length_m'],kind)
                candidates.append((score,data,info))
            except ValueError:continue
        if not candidates:raise original
        _,data,info=min(candidates,key=lambda c:c[0])
        info['auto_family_fallback']=True
        return data,info


def unread_batches(bounds,previous=None):
    """Disjoint border strips: reuse inner tiles, limit each decoder to 1024."""
    west,north,east,south=bounds
    if previous is None:
        regions=[bounds]
    else:
        w,n,e,s=previous
        if not (west<=w<=e<=east and north<=n<=s<=south):
            raise ValueError('底图搜索范围必须逐步扩大')
        regions=[(west,north,east,n-1),(west,s+1,east,south),
                 (west,n,w-1,s),(e+1,n,east,s)]
    for w,n,e,s in regions:
        if w>e or n>s:continue
        for x in range(w,e+1,1024):
            right=min(e,x+1023);rows=max(1,1024//(right-x+1))
            for y in range(n,s+1,rows):
                yield [x,y,right,min(s,y+rows-1)]


def automatic_route(request,stations,progress=None):
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
    last=None;previous=None;features=[];tiles=0;bytes_read=0;json_size=0;batches=0
    deadline=time.monotonic()+SEARCH_SECONDS
    def check_inputs():
        after=p.stat()
        if signature!=(after.st_size,after.st_mtime_ns):raise ValueError('游戏底图在读取期间改变，请重试')
        if time.monotonic()>=deadline:raise ValueError('底图寻路超过 120 秒，请增加中间站分段生成')
    for padding in SEARCH_PADDINGS:
        bounds=bounds_for(*endpoints,padding)
        requested_tiles=(bounds[2]-bounds[0]+1)*(bounds[3]-bounds[1]+1)
        if requested_tiles>MAX_SEARCH_TILES:
            return network_route(p,endpoints,request.get('rail_type','auto'),progress)
        for batch in unread_batches(bounds,previous):
            check_inputs()
            decoded=decode(p,batch,timeout=max(0.001,min(90,deadline-time.monotonic())))
            check_inputs()
            bytes_read+=decoded['bytesRead'];json_size+=len(json.dumps(decoded,ensure_ascii=False))
            if bytes_read>MAX_SEARCH_BYTES or json_size>MAX_SEARCH_JSON or len(features)+len(decoded['features'])>MAX_SEARCH_FEATURES:
                raise ValueError('累计底图数据过大，请增加中间站分段生成；尚不能判断铁路是否连通')
            features.extend(decoded['features']);tiles+=decoded['tiles'];batches+=1
        previous=bounds
        try:
            data,info=choose_route(features,*endpoints,request.get('rail_type','auto'))
            check_inputs()
            info.update(map_path=str(p),map_size=before.st_size,map_mtime_ns=before.st_mtime_ns,
                        tiles=tiles,bytes_read=bytes_read,search_padding_m=padding,
                        searched_tiles=requested_tiles,decode_batches=batches)
            return data,info
        except ValueError as exc:
            if '没有连续铁路路径' not in str(exc):raise
            last=exc
    return network_route(p,endpoints,request.get('rail_type','auto'),progress)
