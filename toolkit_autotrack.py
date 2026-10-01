"""Conservative 1.19.10 blueprint writer. Never edits or connects existing tracks.

The paired-node encoding was checked against five game-created samples; a
Vandry–Dessane generated save was successfully loaded by the user. Construction,
terrain clearance and train operation are separate, required game acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from contextvars import ContextVar
from pathlib import Path

from toolkit_binary import Zstd, split_save, split_save_bytes, read_uvarint, uvarint, require_verified_save
from toolkit_coordedit import lonlat_to_mercator, mercator_to_lonlat
from toolkit_savereader import read_track_nodes

ROOT = Path(__file__).resolve().parent
MAX_POINTS = 4000
MAX_WAYPOINTS = 40
_SNAPSHOT_CACHE = ContextVar('autotrack_snapshot_cache', default=None)
# Zero-width lookahead retains overlapping candidates. Station IDs are exact
# eight-byte canonical varints ending in 0x02; metadata's fourth byte is 0x01.
_STATION_CANDIDATE = re.compile(rb'(?=[\x80-\xff]{7}\x02[\s\S]{3}\x01)')


def _snapshot(raw):
    """One immutable payload per dispatch, never a cross-request file cache.

    A patch produces a new bytes object and invalidates the old parsed layout.
    Its independent readback may then be reused by the next leg. ContextVar
    isolates concurrent/nested tasks; no save-derived cache survives dispatch.
    """
    cache = _SNAPSHOT_CACHE.get()
    if cache is None or not isinstance(raw, bytes):
        return {}
    if cache.get('raw') is not raw:
        cache.clear()
        cache['raw'] = raw
    return cache


def _track_nodes(raw):
    cache = _snapshot(raw)
    if 'nodes' not in cache:
        cache['nodes'] = read_track_nodes(raw, include_planned=True)
    return cache['nodes']


WARNINGS = [
    '仅生成待建双轨，不自动接站、不添加信号或安排列车。',
    '冲突检查基于轨道节点与直线近似，不代表曲线、地形、坡度或净空验收。',
    '桥梁按 +1、隧道按 -1 层预置；不是地形高程。加载成功不等于建造与行车通过。',
    '请保存当前游戏进度，加载新副本暂停检查；不要覆盖正式存档。',
]


def check(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ident_bytes(ident):
    return uvarint(ident * 2) if ident is not None else b'\0'


def number(value, low, high, name):
    check(not isinstance(value, bool), f'{name}无效')
    value = float(value)
    check(math.isfinite(value) and low <= value <= high, f'{name}须在 {low}–{high} 之间')
    return value


def route_data(request):
    data = request.get('geojson')
    if request.get('preset') == 'vandry-dessane':
        data = json.loads((ROOT/'web/assets/autotrack-vandry-dessane.json').read_text('utf-8'))
    check(isinstance(data, dict), '请选择内置路线或导入 GeoJSON')
    check(len(json.dumps(data, allow_nan=False)) < 500_000, '路线文件过大')
    features = data.get('features', []) if data.get('type') == 'FeatureCollection' else [
        data if data.get('type') == 'Feature' else {'type': 'Feature', 'geometry': data, 'properties': {}}]
    check(isinstance(features, list) and len(features) <= 1000, 'GeoJSON 要素过多')
    lines = [f for f in features if f.get('geometry', {}).get('type') == 'LineString'
             and f.get('properties', {}).get('kind') not in ('structure', 'existing_save_track_chord')]
    check(len(lines) == 1, '需要且只能有一条连续 LineString 中心线；不接受未排序的多段线网')
    points = lines[0]['geometry'].get('coordinates', [])
    check(2 <= len(points) <= MAX_POINTS, f'路线须有 2–{MAX_POINTS} 个节点')
    coords = []
    for point in points:
        check(isinstance(point, (list, tuple)) and len(point) == 2, '坐标须为 [经度, 纬度]，不支持高度维度')
        coords.append((number(point[0], -180, 180, '经度'), number(point[1], -80, 80, '纬度')))
    check(max(p[0] for p in coords)-min(p[0] for p in coords) < 180, '不支持跨日期线，请分段并选择不跨日期线的区间')
    lat = sum(p[1] for p in coords)/len(coords)
    scale = math.cos(math.radians(lat))
    xy = [tuple(v*scale for v in lonlat_to_mercator(*p)) for p in coords]
    lengths = [math.dist(a,b) for a,b in zip(xy,xy[1:])]
    check(all(0.05 <= length <= 2000 for length in lengths), '相邻节点须相距 0.05–2000 米；请先清理重复点或补充线形')
    check(sum(lengths) >= 100, '路线长度须至少 0.1 公里')
    chain = [0.0]
    for length in lengths:
        chain.append(chain[-1]+length)
    bridges = []
    for feature in features:
        prop = feature.get('properties', {})
        if prop.get('kind') != 'structure':
            continue
        check(prop.get('brunnel') in ('bridge', 'viaduct', 'movable', 'tunnel'), '不支持的结构标记')
        geometry = feature.get('geometry', {})
        check(geometry.get('type') == 'LineString', '桥梁须为 LineString')
        anchors = geometry.get('coordinates', [])
        check(len(anchors) >= 2, '桥梁缺少端点')
        indices = []
        for point in (anchors[0], anchors[-1]):
            check(len(point) == 2 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in point), '桥梁坐标无效')
            distances = [math.dist(p, point) for p in coords]
            index = min(range(len(coords)), key=distances.__getitem__)
            check(distances[index] < 1e-7, '桥梁两端必须已有对应中心线节点')
            indices.append(index)
        check(indices[0] != indices[1], '桥梁长度无效')
        bridges.append((*sorted(chain[i] for i in indices), 1 if prop.get('brunnel')=='tunnel' else 2))
    bridges.sort()
    check(all(a[1]<=b[0] for a,b in zip(bridges,bridges[1:])), '桥梁/隧道结构范围重叠，不能安全指定层级')
    return xy, chain, scale, bridges


def registry(raw, offset, kind):
    count, cursor = read_uvarint(raw, offset)
    check(0 < count <= 300_000, '对象表数量无效')
    ids = []
    for slot in range(count):
        value, cursor = read_uvarint(raw, cursor)
        # Station registries keep deleted slots as signed, type-FFFF IDs.
        # Do not extend this to Track: appending to a sparse Track allocator
        # needs a separately verified allocation policy.
        if kind == 2:
            check(value < 1 << 64, '车站索引超出 64 位范围')
            ident = ((value >> 1) ^ -(value & 1)) & ((1 << 64) - 1)
            check((ident >> 16 & 0xffffffff) == slot, '车站槽位顺序异常')
            check(ident & 0xffff, '车站槽位代数无效')
            if value & 1:
                check(ident >> 48 == 0xffff, '车站空槽标记无效')
                continue
        check(value % 2 == 0 and value//2 >> 48 == kind, '对象表 ID 类型不匹配')
        ids.append(value//2)
    objects, start = read_uvarint(raw, cursor)
    check(objects == len(ids) and len(set(ids)) == len(ids), '对象表有效索引、数量不一致')
    check(ids, '对象表没有有效对象')
    return ids, start


def layout(raw):
    cache = _snapshot(raw)
    if 'layout' in cache:
        return cache['layout']
    ids, start = registry(raw, 0, 1)
    check([x>>16 & 0xffffffff for x in ids] == list(range(len(ids))),
          '轨道槽位不连续，当前写入器不能安全扩展此存档')
    nodes = _track_nodes(raw)
    check(set(nodes) == set(ids), '存在尚未识别的轨道类型或记录，已禁止写入')
    check(len({n.position for n in nodes.values()}) == len(ids), '轨道记录重复')
    last = max(n.position for n in nodes.values())
    candidates = []
    # Only accept an independently validated Station registry + first object id.
    for offset in range(last+40, min(last+8192, len(raw)-20)):
        try:
            _, p = read_uvarint(raw, offset)
            first, _ = read_uvarint(raw, p)
            decoded = ((first >> 1) ^ -(first & 1)) & ((1 << 64) - 1)
            if decoded >> 48 not in (2, 0xffff):
                continue
            station_ids, records = registry(raw, offset, 2)
            ident, _ = read_uvarint(raw, records)
            if ident//2 == station_ids[0] and ident%2 == 0:
                candidates.append(offset)
        except (ValueError, IndexError):
            continue
    check(candidates, '未找到通过校验的车站表，无法确定轨道表结束位置；存档结构可能尚未兼容，已禁止写入')
    check(len(candidates) == 1, '找到多个候选车站表，不能唯一确定轨道表结束位置，已禁止写入')
    result = ids, start, candidates[0], nodes
    cache['layout'] = result
    return result


def clip_interval(a, b, p, q, width=15):
    """Clip an existing straight edge to a route segment's rectangular corridor."""
    length = math.dist(p,q)
    ux,uy = (q[0]-p[0])/length,(q[1]-p[1])/length
    def local(v):
        dx,dy = v[0]-p[0],v[1]-p[1]
        return dx*ux+dy*uy, -dx*uy+dy*ux
    x,y = local(a); x2,y2 = local(b)
    lo,hi = 0.0,1.0
    for v,d,mn,mx in ((x,x2-x,-width,length+width),(y,y2-y,-width,width)):
        if abs(d)<1e-12:
            if not mn<=v<=mx: return None
        else:
            t1,t2=sorted(((mn-v)/d,(mx-v)/d))
            lo,hi=max(lo,t1),min(hi,t2)
            if lo>hi: return None
    return sorted((max(0,min(length,x+(x2-x)*lo)),max(0,min(length,x+(x2-x)*hi))))


def crop(xy, chain, start, end):
    def at(value):
        for i in range(len(chain)-1):
            if chain[i] <= value <= chain[i+1]:
                t=(value-chain[i])/(chain[i+1]-chain[i])
                return tuple(a+(b-a)*t for a,b in zip(xy[i],xy[i+1]))
        return xy[-1]
    result=[(start,at(start))]+[(s,p) for s,p in zip(chain,xy) if start<s<end]+[(end,at(end))]
    # Cropping beside an existing vertex must not produce a tiny extra segment.
    if len(result)>2 and result[1][0]-result[0][0]<2: result.pop(1)
    if len(result)>2 and result[-1][0]-result[-2][0]<2: result.pop(-2)
    return result


def safe_structure_crop(low,high,start,end,structures,margin):
    """Retreat automatic existing-track clearance outside whole structures.

    Never extend into occupied track, and never reinterpret a user's explicit
    cut inside a bridge/tunnel. Additional station-side gaps are reported.
    """
    original_start,original_end=start,end
    for _ in range(len(structures)*2+1):
        previous=start,end
        for a,b,_ in structures:
            if a<start<b:
                check(original_start>low and not a<low<b,'裁剪端点落在桥梁中，请调整里程范围')
                start=b+margin
            if a<end<b:
                check(original_end<high and not a<high<b,'裁剪端点落在桥梁中，请调整里程范围')
                end=a-margin
        check(end-start>=100,'避让既有轨道和完整桥隧后区间不足 100 米')
        if (start,end)==previous:break
    return start,end,{'start_extra_m':round(start-original_start,1),'end_extra_m':round(original_end-end,1)}


def prepare(raw, request, *, stations=None):
    xy,chain,scale,bridges = route_data(request)
    ids,start,end,nodes = layout(raw)
    low = number(request.get('start_m',0), 0, chain[-1], '起点里程')
    high = number(chain[-1] if request.get('end_m') is None else request['end_m'], 0, chain[-1], '终点里程')
    check(high-low >= 100, '铺设区间至少 100 米，终点须大于起点')
    margin = number(request.get('gap_m',50), 20, 200, '接轨预留')
    variant = request.get('variant',6)
    variants={0:variant,2:request.get('bridge_variant',variant),1:request.get('tunnel_variant',variant)}
    check(all(type(v) is int and v in (2,4,6) for v in variants.values()), '请选择中速、高速或电车轨道')
    for code in set(variants.values()):
        key,name={2:('waw_track_hs_1','High speed'),4:('waw_track_tram_1','Tram'),6:('waw_track_mid_1','Medium speed')}[code]
        signature=bytes([len(key)])+key.encode()+bytes([1,code,len(name)])+name.encode()
        check(raw.count(signature)==1,'存档内置轨道定义不唯一或类型编号不同，不能安全套用模板')
    mode=request.get('structure_mode','auto')
    check(mode in ('auto','ground','bridge','tunnel'), '结构模式无效')
    player_mode=request.get('player_obstacle_mode','off')
    check(player_mode in ('off','bridge','tunnel'),'玩家设施避让请选择关闭、向上或向下')
    check(player_mode=='off' or mode=='auto','玩家设施避让仅用于自动结构；强制结构时请关闭避让')
    # Existing built AND planned tracks, including edges whose endpoints are outside.
    projected = {ident:tuple(v*scale for v in lonlat_to_mercator(n.lon,n.lat)) for ident,n in nodes.items()}
    box=(min(p[0] for p in xy)-20,min(p[1] for p in xy)-20,max(p[0] for p in xy)+20,max(p[1] for p in xy)+20)
    hits=[]; seen=set()
    for ident,node in nodes.items():
        for other in node.connections:
            if other not in nodes: continue
            key=tuple(sorted((ident,other)))
            if key in seen: continue
            seen.add(key)
            a,b=projected[ident],projected[other]
            if max(a[0],b[0])<box[0] or min(a[0],b[0])>box[2] or max(a[1],b[1])<box[1] or min(a[1],b[1])>box[3]: continue
            for i,(p,q) in enumerate(zip(xy,xy[1:])):
                hit=clip_interval(a,b,p,q)
                if hit and chain[i]+hit[1]>=low and chain[i]+hit[0]<=high:
                    hits.append((max(low,chain[i]+hit[0]),min(high,chain[i]+hit[1])))
    zone=min(1500,(high-low)*0.25)
    for a,b in hits:
        check(player_mode!='off' or b<=low+zone or a>=high-zone,
              '区间中部已有轨道或待建蓝图；可能重复铺设或存在交叉。请缩小区间，不会强行覆盖。')
    trim_low=max([low]+[b+margin for a,b in hits if b<=low+zone])
    trim_high=min([high]+[a-margin for a,b in hits if a>=high-zone])
    check(trim_high-trim_low>=100, '避让既有轨道后区间不足 100 米')
    trim_low,trim_high,structure_trim=safe_structure_crop(low,high,trim_low,trim_high,bridges,margin)
    selected=crop(xy,chain,trim_low,trim_high)
    levels=[next((level for a,b,level in bridges if a-0.01<=s<=b+0.01),0) if mode=='auto' else {'ground':0,'bridge':2,'tunnel':1}[mode] for s,p in selected]
    from toolkit_obstacles import avoid
    coords=[mercator_to_lonlat(p[0]/scale,p[1]/scale) for s,p in selected]
    base_levels=list(levels)
    levels,obstacle_report=avoid(coords,levels,request)
    player_report=None
    if player_mode!='off':
        from toolkit_player_obstacles import avoid as avoid_players
        levels,player_report=avoid_players(selected,levels,base_levels,nodes,projected,
            station_catalog(raw) if stations is None else stations,scale,request,xy)
    node_variants=[variants[level] for level in levels]
    warnings=list(WARNINGS)
    if any(structure_trim.values()):
        warnings.append(f"接轨预留落在桥隧中，已回退至完整结构外：起点额外预留 {structure_trim['start_extra_m']} 米、终点额外预留 {structure_trim['end_extra_m']} 米。增加的空隙未自动补连，请在游戏内接轨。")
    if obstacle_report:
        warnings.append(f"水域道路预避让：{obstacle_report['water_segments']} 段涉及水域，{obstacle_report['road_segments']} 段涉及道路；调整 {obstacle_report['changed_nodes']} 个双轨节点。按整段两端控制点处理，可能比实际冲突范围更长。底图近似不是游戏冲突验收。")
    if player_report:
        warnings.append(f"玩家设施预避让：{player_report['track_segments']} 段接近已建/蓝图轨道（其中 {player_report['planned_track_segments']} 段涉及蓝图），{player_report['station_segments']} 段接近车站中心保护圈；调整 {player_report['changed_nodes']} 个双轨节点。已分层路段可保持不变。车站按地面中心 {player_report['station_radius_m']} 米近似，不包含完整站房轮廓；须游戏内检查坡度和净空。原有设施未改动。")
    radii=[]
    for (_,a),(_,b),(_,c) in zip(selected,selected[1:],selected[2:]):
        cross=abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
        if cross>1e-6: radii.append(math.dist(a,b)*math.dist(b,c)*math.dist(a,c)/(2*cross))
    if radii and min(radii)<150: warnings.append('参考折线有较急弯（估算半径小于 150 米）；请在游戏内调整曲线。')
    if any(math.dist(a,b)<2 for (_,a),(_,b) in zip(selected,selected[1:])):warnings.append('底图含间距小于 2 米的节点，请检查碎段和结构连接处。')
    if 4 in node_variants:warnings.append('电车类型已核对存档定义，新增双轨尚未在游戏内验收。')
    preview={'length_m':round(trim_high-trim_low,1),'full_length_m':round(chain[-1],1),
             'start_m':round(trim_low,1),'end_m':round(trim_high,1),'nodes':len(selected)*2,
             'avoided_intervals':len(hits),'planned_existing_nodes':sum(n.state_code==1 for n in nodes.values()),
             'bridge_nodes':sum(level==2 for level in levels)*2,'tunnel_nodes':sum(level==1 for level in levels)*2,'warnings':warnings,
             'coordinates':coords,
             'levels':levels,'variants':node_variants,'variant':variant,'spacing_m':5}
    if obstacle_report:preview['obstacle_avoidance']=obstacle_report
    if player_report:preview['player_obstacle_avoidance']=player_report
    if any(structure_trim.values()):preview['structure_trim']=structure_trim
    return preview,(ids,start,end,nodes),selected,scale


def record(ident, neighbors, point, level, pair, secondary, variant=6):
    x,y=lonlat_to_mercator(*point)
    prefix=(ident_bytes(ident)+bytes((1,variant,level,1))+b''.join(map(ident_bytes,neighbors))+
            bytes(5)+struct.pack('<ddff',x,y,0.0,0.5))
    # Exact constant suffixes from the game-created disconnected paired templates.
    shared=bytes.fromhex('000000010001')+bytes(18)
    if secondary:
        tail=shared+ident_bytes(pair)+bytes.fromhex('0000000000020000a040000000000000000040')
    else:
        tail=shared+bytes(6)+bytes.fromhex('020000a0400000000001')+ident_bytes(pair)+struct.pack('<f',2.0)
    return prefix+tail


def patch(raw, prepared):
    preview,(ids,start,end,nodes),selected,scale=prepared
    count=len(selected)*2
    new_ids=[(1<<48)+((len(ids)+i)<<16)+1 for i in range(count)]
    a_ids,b_ids=new_ids[::2],new_ids[1::2]
    xy=[p for s,p in selected]
    output=[]; expected={}
    for i,p in enumerate(xy):
        lo,hi=xy[max(0,i-1)],xy[min(len(xy)-1,i+1)]
        dx,dy=hi[0]-lo[0],hi[1]-lo[1]; length=math.hypot(dx,dy)
        check(length>0,'路线折返导致轨道偏移无定义')
        for secondary,own,other,sign in ((False,a_ids,b_ids,1),(True,b_ids,a_ids,-1)):
            point=mercator_to_lonlat((p[0]-dy/length*2.5*sign)/scale,(p[1]+dx/length*2.5*sign)/scale)
            neighbors=[own[i-1] if i else None,own[i+1] if i+1<len(xy) else None]
            if secondary: neighbors.reverse()
            output.append(record(own[i],neighbors,point,preview['levels'][i],other[i],secondary,preview['variants'][i]))
            expected[own[i]]=(neighbors,point,preview['levels'][i],preview['variants'][i])
    registry_ids=ids+new_ids
    prefix=uvarint(len(registry_ids))+b''.join(map(ident_bytes,registry_ids))+uvarint(len(registry_ids))
    result=prefix+raw[start:end]+b''.join(output)+raw[end:]
    found=_track_nodes(result)
    check(set(found)==set(registry_ids),'写后回读节点不一致')
    for ident,(neighbors,point,level,variant) in expected.items():
        node=found[ident]
        check(list(node.connections)==neighbors and node.state_code==1 and node.variant==variant
              and node.level_code==level and math.dist((node.lon,node.lat),point)<1e-6,'生成轨道回读不一致')
        check(all(n is None or ident in found[n].connections for n in neighbors),'邻接关系不对称')
    check(result[len(prefix):len(prefix)+end-start]==raw[start:end],'旧轨道数据发生变化')
    check(result[len(prefix)+end-start+sum(map(len,output)):] == raw[end:],'非轨道数据发生变化')
    return result


def station_catalog(raw, *, include_offsets=False):
    """Registry-filtered stations, including southern/equatorial coordinates.

    The older analytic reader intentionally restricted coordinate magnitudes.
    Here the verified registry and exact metadata/record shape replace that
    geographical heuristic. Ambiguous records are omitted, never guessed.
    """
    from toolkit_coordedit import _read_name
    _,_,end,_=layout(raw)
    station_ids,records=registry(raw,end,2)
    allowed={ident_bytes(ident):ident for ident in station_ids}
    found={}
    for match in _STATION_CANDIDATE.finditer(raw,records):
        position=match.start();ident=allowed.get(raw[position:position+8])
        if ident is None:continue
        offset=position+12
        if offset+17>len(raw):continue
        x,y=struct.unpack_from('<dd',raw,offset)
        if not all(math.isfinite(v) and abs(v)<20_100_000 for v in (x,y)):continue
        name=_read_name(raw,offset+16,min_len=1,max_len=512)
        # A name or the empty-name length byte must follow the coordinates.
        if not name and raw[offset+16]!=0:continue
        lon,lat=mercator_to_lonlat(x,y)
        row={'id':hex(ident),'name':name[0] if name else f'未命名站 {hex(ident)}','lon':lon,'lat':lat}
        if include_offsets:row['coord_off']=offset
        # More than one validated location stays ambiguous, never last-wins.
        found[ident]=None if ident in found else row
    result=[row for row in found.values() if row is not None]
    return sorted(result,key=lambda s:(s['name'].casefold(),s['id']))


def route_files(save_dir):
    result=[];seen=set()
    for directory in (save_dir,save_dir/'routes',ROOT/'routes'):
        if not directory.is_dir():continue
        for path in directory.iterdir():
            if len(result)>=200:return result
            if path.suffix.lower() not in ('.geojson','.json') or not path.is_file():continue
            full=str(path.resolve())
            if full in seen or path.stat().st_size>500000:continue
            seen.add(full)
            try:
                data=json.loads(path.read_text('utf-8-sig'))
                if not isinstance(data,dict) or data.get('type') not in ('LineString','Feature','FeatureCollection'):continue
                result.append({'path':full,'name':path.name,'mtime':path.stat().st_mtime})
            except (OSError,ValueError):continue
    return sorted(result,key=lambda r:r['mtime'],reverse=True)


def waypoint_plan(raw, request, stations, progress=None):
    """Stage independent legs in memory; never silently skip failed sections."""
    from toolkit_autoroute import automatic_route, tile_point
    via = request.get('via')
    check(isinstance(via, list) and len(via) <= MAX_WAYPOINTS-2, f'最多添加 {MAX_WAYPOINTS-2} 个途经站（共 {MAX_WAYPOINTS} 站）')
    check(not via or (request.get('start_m', 0) == 0 and request.get('end_m') is None),
          '多站模式按各区间全长生成，不支持起终里程裁剪；请清空里程设置')
    entries = [{'station': request.get('from_station'), 'coord': request.get('from_coord')},
               *via, {'station': request.get('to_station'), 'coord': request.get('to_coord')}]
    waypoints = []; seen = set()
    for index, entry in enumerate(entries):
        point = {'index': index, 'label': f'第 {index+1} 站', 'status': 'ready', 'errors': []}
        try:
            check(isinstance(entry, dict), '站点格式无效，请重新选择')
            ident = entry.get('station')
            if ident:
                check(isinstance(ident, str), '站点 ID 无效')
                matches = [s for s in stations if s['id'] == ident]
                check(len(matches) == 1, '所选站点不在当前存档，请重新自动读取或删除此站')
                station = matches[0]
                point.update(label=station['name'], station_id=ident, coord=[station['lon'], station['lat']])
            else:
                coord = entry.get('coord')
                check(isinstance(coord, list) and len(coord) == 2 and all(type(v) in (int, float) for v in coord),
                      '请选择完整站名，或输入 经度,纬度')
                point.update(coord=list(coord), label=', '.join(map(str, coord)))
            tile_point(point['coord'])
            key = tuple(point['coord'])
            check(key not in seen, '重复站点或坐标：请删除重复项，不支持往返重叠铺设')
            seen.add(key)
        except (ValueError, TypeError, OverflowError) as exc:
            point.update(status='invalid', errors=[str(exc)], validation_error=str(exc))
        waypoints.append(point)
    legs = []; candidate = raw; total_nodes = 0; total_length = 0; map_signature = None
    for index, (a, b) in enumerate(zip(waypoints, waypoints[1:])):
        leg = {'index': index, 'from_index': index, 'to_index': index+1,
               'from_name': a['label'], 'to_name': b['label'], 'status': 'error'}
        if progress:
            progress(index+1, len(waypoints)-1, f"检查区间 {index+1}/{len(waypoints)-1}：{a['label']} → {b['label']}")
        try:
            invalid = [p for p in (a, b) if p['status'] == 'invalid']
            check(not invalid, '；'.join(f"第 {p['index']+1} 站：{p['validation_error']}" for p in invalid))
            single = {k: v for k, v in request.items() if k not in ('via', 'from_station', 'to_station', 'from_coord', 'to_coord')}
            single.update(from_coord=a['coord'], to_coord=b['coord'])
            geojson, info = automatic_route(single, stations, progress=progress) if progress else automatic_route(single, stations)
            signature = tuple(info.get(k) for k in ('map_path', 'map_size', 'map_mtime_ns'))
            # A changed input invalidates the entire plan, not just one leg.
            # Partial output must never mix routes from different map snapshots.
            if map_signature is not None and signature != map_signature:
                raise RuntimeError('底图在分段读取期间改变，请重新预览全部区间')
            map_signature = signature
            single['geojson'] = geojson
            prepared = prepare(candidate, single, stations=stations)
            detail = dict(prepared[0]); detail['routing'] = info
            obstacle_info=detail.get('obstacle_avoidance')
            if obstacle_info and tuple(obstacle_info.get(k) for k in ('map_path','map_size','map_mtime_ns'))!=signature:
                raise RuntimeError('寻路与障碍检查使用的底图不同或已变化，请重新预览全部区间')
            check(total_nodes + detail['nodes'] <= MAX_POINTS*2, '整条方案超过 8000 个双轨节点，请减少站点、分批生成')
            updated = patch(candidate, prepared)
            candidate = updated
            total_nodes += detail['nodes']; total_length += detail['length_m']
            if info.get('auto_family_fallback'):
                detail['warnings'].append('本区间回退到共同铁路类型：'+', '.join(info['rail_types'])+'，请核对路线。')
            if info.get('search_padding_m',0)>8000:
                detail['warnings'].append(f"本区间已扩大底图搜索至两站外侧 {info['search_padding_m']//1000} 公里，找到绕行路径，请核对预览。")
            if info.get('search_method')=='railway-frontier':
                detail['warnings'].append(f"本区间沿铁路分块搜索，实际检查 {info['searched_tiles']} 个地图块；未扫描整个两站矩形。请核对路线。")
            leg.update(status='ok', preview=detail)
        except (ValueError, OSError) as exc:
            leg['error'] = str(exc)
            for point in (a, b):
                if point['status'] != 'invalid': point['status'] = 'warning'
                point['errors'].append(f'区间 {index+1} 未通过：{exc}')
        legs.append(leg)
    good = [leg['preview'] for leg in legs if leg['status'] == 'ok']
    failed = len(legs)-len(good)
    warnings = list(dict.fromkeys(message for detail in good for message in detail['warnings'])) or list(WARNINGS)
    warnings.append('逐段生成待建双轨；各站附近可能保留接轨空隙，不会自动连接站台。')
    if failed:
        warnings.append(f'{failed} 个区间未通过；确认跳过后可仅生成 {len(good)} 个通过区间，缺口不会自动补连。' if good else '没有通过检查的区间，不能生成蓝图。请调整站点或路线后重新预览。')
    skipped = [{k: leg[k] for k in ('index', 'from_index', 'to_index', 'from_name', 'to_name', 'error')}
               for leg in legs if leg['status'] != 'ok']
    result = {'multi_station': True, 'waypoints': waypoints, 'legs': legs, 'can_apply': bool(good),
              'requires_partial_confirmation': bool(failed and good),
              'included_legs': [leg['index'] for leg in legs if leg['status'] == 'ok'], 'skipped_legs': skipped,
              'successful_legs': len(good), 'failed_legs': failed, 'length_m': round(total_length, 1),
              'nodes': total_nodes, 'warnings': warnings, 'coordinates': [], 'levels': [], 'routing': {}}
    for key in ('bridge_nodes', 'tunnel_nodes', 'avoided_intervals', 'full_length_m'):
        result[key] = sum(detail[key] for detail in good)
    return result, candidate


def discover_stations(request, stations, progress=None):
    """Suggest saved stations near a routed centerline; never infer membership."""
    from toolkit_autoroute import automatic_route, projection
    check(request.get('preset') == 'auto', '沿途站识别只适用于自动寻路')
    endpoints = [request.get(key+'_station') for key in ('from', 'to')]
    check(all(ident and sum(s['id'] == ident for s in stations) == 1 for ident in endpoints),
          '识别沿途站前，请选择存档中的完整起点站和终点站，不使用坐标或未建站')
    check(endpoints[0] != endpoints[1], '起点和终点不能是同一站')
    if progress: progress(0, 1, '沿首尾站寻找铁路路径，再识别存档中的沿途站…')
    geojson, routing = automatic_route(request, stations, progress=progress) if progress else automatic_route(request, stations)
    xy, chain, scale, _ = route_data({'geojson': geojson})
    radius = 200
    bounds = (min(p[0] for p in xy)-radius, min(p[1] for p in xy)-radius,
              max(p[0] for p in xy)+radius, max(p[1] for p in xy)+radius)
    candidates = []
    for index, station in enumerate(stations):
        if station['id'] in endpoints: continue
        point = tuple(v*scale for v in lonlat_to_mercator(station['lon'], station['lat']))
        if not (bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]): continue
        hits = []
        for i, (a, b) in enumerate(zip(xy, xy[1:])):
            t, foot = projection(point, a, b)
            distance = math.dist(point, foot)
            if distance <= radius:
                hits.append((distance, chain[i]+t*(chain[i+1]-chain[i])))
        if not hits: continue
        distance, mileage = min(hits)
        if not 1 < mileage < chain[-1]-1: continue
        ambiguous = any(abs(m-mileage) > 500 and d <= distance+20 for d, m in hits)
        candidates.append({**station, 'distance_m': round(distance, 1), 'along_m': round(mileage, 1),
                           'ambiguous': ambiguous})
        if progress and index % 50 == 0: progress(index+1, len(stations), '正在按路线里程排列候选站…')
    candidates.sort(key=lambda s: (s['along_m'], s['id']))
    return {'action': 'autotrack', 'operation': 'discover', 'candidates': candidates,
            'length_m': round(chain[-1], 1), 'radius_m': radius, 'routing': routing,
            'warnings': ['仅列出当前存档中距路径 200 米内的车站对象，包含已建站和蓝图站；不创建车站。',
                         '距离近不代表属于这条铁路，平行线、换乘站及分支请逐项确认；候选默认不勾选。',
                         '按首尾站路径识别，暂不使用手动途经站；确认后替换途经站列表，仍需重新预览并在游戏内接轨。']}


def dispatch(request, progress=None):
    token = _SNAPSHOT_CACHE.set({})
    try:
        return _dispatch(request, progress)
    finally:
        _SNAPSHOT_CACHE.reset(token)


def _dispatch(request, progress=None):
    check(type(request.get('allow_partial', False)) is bool, '跳过失败区间的确认值无效')
    source=Path(request['save']).resolve()
    original=source.read_bytes(); source_hash=digest(original)
    check(not request.get('discovery_source_sha256') or request['discovery_source_sha256'] == source_hash,
          '存档在识别沿途站后改变，请重新自动读取并识别')
    header,frame,_=split_save_bytes(original)
    check(digest(source.read_bytes())==source_hash,'读取期间存档改变，请重试')
    require_verified_save(header)
    raw=Zstd().decompress(frame)
    operation=request.get('operation','preview')
    check(operation in ('catalog','preview','discover'), '自动铺轨操作无效')
    check(not (operation in ('catalog','discover') and request.get('apply')), '读取列表或识别沿途站不能同时写入')
    stations=station_catalog(raw) if operation in ('catalog','discover') or request.get('preset')=='auto' else []
    if operation=='catalog':
        from toolkit_autoroute import game_maps,node_runtime
        routes=route_files(source.parent)
        return {'action':'autotrack','operation':'catalog','stations':stations,'maps':game_maps(),
                'node_ready':bool(node_runtime()),'routes':routes,'save':str(source),'source_sha256':source_hash}
    if operation == 'discover':
        result = discover_stations(request, stations, progress)
        check(digest(source.read_bytes()) == source_hash, '识别期间存档改变，请重新识别')
        return dict(result, source_sha256=source_hash)
    resolved=dict(request);route_info={}
    batch = 'via' in request
    check(not batch or request.get('preset') == 'auto', '途经站只适用于自动寻路模式')
    if batch:
        layout(raw)  # Global binary-format failures cannot become skippable leg errors.
        result, batch_raw = waypoint_plan(raw, request, stations, progress)
    elif request.get('preset')=='auto':
        from toolkit_autoroute import automatic_route
        resolved['geojson'],route_info=automatic_route(request,stations,progress=progress) if progress else automatic_route(request,stations)
    elif request.get('preset')=='file':
        selected=Path(request.get('route_path','')).resolve()
        check(str(selected) in {r['path'] for r in route_files(source.parent)}, '路线文件已移动或不在自动发现的目录中，请重新读取')
        data=selected.read_bytes();check(len(data)<500000,'路线文件过大')
        resolved['geojson']=json.loads(data)
        route_info={'route_path':str(selected),'route_sha256':digest(data)}
    if not batch:
        prepared=prepare(raw,resolved)
        result=dict(prepared[0])
        result['routing']=route_info
        obstacle_info=result.get('obstacle_avoidance')
        if obstacle_info and request.get('preset')=='auto' and any(obstacle_info.get(k)!=route_info.get(k) for k in ('map_path','map_size','map_mtime_ns')):
            raise RuntimeError('寻路与障碍检查使用的底图不同或已变化，请重新预览')
    if route_info.get('auto_family_fallback'):
        result['warnings']=result['warnings']+['最近轨道不在同一网络；已回退选择两端均可接入的 '+', '.join(route_info['rail_types'])+'。请核对是否为你要建的线路。']
    if route_info.get('search_padding_m',0)>8000:
        result['warnings']=result['warnings']+[f"已扩大底图搜索至两站外侧 {route_info['search_padding_m']//1000} 公里，找到绕行路径，请核对预览。"]
    if route_info.get('search_method')=='railway-frontier':
        result['warnings']=result['warnings']+[f"沿铁路分块搜索，实际检查 {route_info['searched_tiles']} 个地图块；未扫描整个两站矩形。请核对路线。"]
    # Approval is not a geometry setting: it is given after inspecting the
    # fingerprinted success/skip list and is rechecked on every write.
    settings={k:v for k,v in request.items() if k not in ('apply','output','fingerprint','save','allow_partial')}
    token=digest(json.dumps({'save':source_hash,'settings':settings,'preview':result},sort_keys=True,allow_nan=False).encode())
    result.update(action='autotrack',fingerprint=token,source_sha256=source_hash)
    if not request.get('apply'): return result
    check(request.get('fingerprint')==token,'存档或参数已变化，请重新预览后再生成')
    check(result.get('can_apply', True), '没有通过检查的区间，未写入任何存档。请调整站点或路线后重新预览')
    check(not result.get('requires_partial_confirmation') or request.get('allow_partial') is True,
          '仍有失败区间，未写入任何存档。请确认“仅生成通过区间，保留缺口”后再生成')
    output=Path(request['output']).resolve()
    check(output!=source and output.suffix.lower()=='.nimbyrails5','输出须为不同的新存档')
    manifest=output.with_suffix('.manifest.json')
    partial=output.with_name(output.name+'.partial')
    check(not any(p.exists() for p in (output,manifest,partial)), '输出或清单已存在，请换一个名称')
    patched=batch_raw if batch else patch(raw,prepared)
    packed=Zstd().compress(patched)
    check(Zstd().decompress(packed)==patched,'压缩回读失败')
    check(digest(source.read_bytes())==source_hash,'生成期间原存档改变，请重新预览')
    data=header+packed
    result.update(output_save=str(output),output_sha256=digest(data),game_validated=False,
                  operation='autotrack',source=str(source),appended_nodes=result['nodes'],
                  partial_output=bool(result.get('requires_partial_confirmation')))
    # Stage bytes then publish with an exclusive hard link; no overwrite race.
    # Failed staging remains a recognizable .partial, never a loadable broken save.
    with partial.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    try:
        os.link(partial,output)
    except OSError as exc:
        raise ValueError('无法安全发布新存档；未覆盖目标，请检查目录或文件系统权限') from exc
    partial.unlink()
    with manifest.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    return result
