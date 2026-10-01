"""Conservative saved-player-facility clearance for NEW blueprint nodes only.

Only verified level codes 0 (ground), 1 (-1), 2 (+1) are interpreted. Stations
are ground-plane centre protection circles, NOT building footprints. Rail
edges are chords; differing endpoint levels split at the midpoint like preview.
"""
import math
import time
from collections import defaultdict

from toolkit_coordedit import lonlat_to_mercator
from toolkit_obstacles import segment_distance


def halves(a,b,la,lb):
    if la==lb:return [(a,b,la)]
    mid=((a[0]+b[0])/2,(a[1]+b[1])/2)
    return [(a,mid,la),(mid,b,lb)]


def bounds(a,b,pad=0):
    return min(a[0],b[0])-pad,min(a[1],b[1])-pad,max(a[0],b[0])+pad,max(a[1],b[1])+pad


def overlaps(a,b):
    return not (a[2]<b[0] or a[0]>b[2] or a[3]<b[1] or a[1]>b[3])


class Index:
    """Bounded broad phase; unusually long edges stay in an overflow list."""
    def __init__(self):self.rows=[];self.cells=defaultdict(list);self.wide=[]

    @staticmethod
    def keys(box):
        w,n,e,s=(math.floor(v/512) for v in box)
        if (e-w+1)*(s-n+1)>256:return None
        return [(x,y) for x in range(w,e+1) for y in range(n,s+1)]

    def add(self,row):
        row['box']=bounds(row['a'],row['b'],row['padding'])
        i=len(self.rows);self.rows.append(row);keys=self.keys(row['box'])
        if keys is None:self.wide.append(i)
        else:
            for k in keys:self.cells[k].append(i)

    def query(self,a,b):
        box=bounds(a,b);keys=self.keys(box)
        candidates=range(len(self.rows)) if keys is None else sorted(set(self.wide).union(*(self.cells.get(k,[]) for k in keys)))
        return [self.rows[i] for i in candidates if overlaps(box,self.rows[i]['box'])]


def collides(a,b,la,lb,row):
    return any(level==row['level'] and segment_distance(p,q,row['a'],row['b'])<=row['padding']
               for p,q,level in halves(a,b,la,lb))


def avoid(selected,levels,base_levels,nodes,projected,stations,scale,request,original_xy):
    mode=request.get('player_obstacle_mode','off')
    if mode=='off':return levels,None
    if mode not in ('bridge','tunnel'):raise ValueError('玩家设施避让请选择关闭、向上或向下')
    if request.get('structure_mode','auto')!='auto':raise ValueError('玩家设施避让仅用于自动结构；强制结构时请关闭避让')
    radius=request.get('player_station_radius_m',60)
    if type(radius) not in (int,float) or not math.isfinite(radius) or not 10<=radius<=200:
        raise ValueError('车站中心保护范围须为 10–200 米')
    target=2 if mode=='bridge' else 1;deadline=time.monotonic()+120
    points=[p for _,p in selected];index=Index();seen=set();connected=set()
    box=(min(p[0] for p in points)-radius-20,min(p[1] for p in points)-radius-20,
         max(p[0] for p in points)+radius+20,max(p[1] for p in points)+radius+20)
    def add(row):
        if overlaps(bounds(row['a'],row['b'],row['padding']),box):index.add(row)
    for ident,node in nodes.items():
        if time.monotonic()>deadline:raise ValueError('玩家设施检查超过 120 秒，请分段')
        for other in node.connections:
            if other not in nodes:continue
            connected.update((ident,other));key=tuple(sorted((ident,other)))
            if key in seen:continue
            seen.add(key);peer=nodes[other]
            for a,b,level in halves(projected[ident],projected[other],node.level_code,peer.level_code):
                add({'a':a,'b':b,'level':level,'padding':15,'reason':'player_track',
                     'ids':tuple(hex(i) for i in key),'planned':node.state_code==1 or peer.state_code==1})
    for ident,node in nodes.items():
        if ident not in connected:
            add({'a':projected[ident],'b':projected[ident],'level':node.level_code,'padding':15,
                 'reason':'player_track','ids':(hex(ident),),'planned':node.state_code==1})
    # Explicit endpoint station/coordinate identity, not every station near the
    # start: intermediate stations remain obstacles unless made waypoints.
    endpoints=[]
    for key,fallback in (('from',original_xy[0]),('to',original_xy[-1])):
        coord=request.get(key+'_coord')
        endpoints.append(tuple(v*scale for v in lonlat_to_mercator(*coord)) if coord else fallback)
    excluded={request.get('from_station'),request.get('to_station')}
    for station in stations:
        p=tuple(v*scale for v in lonlat_to_mercator(station['lon'],station['lat']))
        if station['id'] in excluded or any(math.dist(p,q)<=20 for q in endpoints):continue
        if overlaps(bounds(p,p,radius),box):
            index.add({'a':p,'b':p,'level':0,'padding':radius,'reason':'player_station',
                       'ids':(station['id'],),'planned':None})
    hits=[];result=list(levels)
    for i,(a,b) in enumerate(zip(points,points[1:])):
        if time.monotonic()>deadline:raise ValueError('玩家设施检查超过 120 秒，请分段')
        rows=[r for r in index.query(a,b) if segment_distance(a,b,r['a'],r['b'])<=r['padding']]
        if not rows:continue
        if any(r['level'] not in (0,1,2) for r in rows):
            raise ValueError(f'第 {i+1} 段附近玩家轨道含未验证的高度层级，不能自动保证避让；请手动分段处理')
        hits.append((i,rows))
        if not any(collides(a,b,result[i],result[i+1],r) for r in rows):continue
        for j in (i,i+1):
            if result[j]==target:continue
            if base_levels[j]!=0:raise ValueError('玩家设施与底图原有桥隧冲突；不会覆盖既定桥隧高度，请换方向或分段')
            if result[j]!=0:raise ValueError('水域/道路与玩家设施避让方向冲突；请统一方向或分段设置')
            result[j]=target
    # A raised/lowered endpoint also changes its neighbouring half-segment.
    # Recheck EVERY geometric contact, including initially separated tracks.
    for i,rows in hits:
        if time.monotonic()>deadline:raise ValueError('玩家设施检查超过 120 秒，请分段')
        if any(collides(points[i],points[i+1],result[i],result[i+1],r) for r in rows):
            raise ValueError(f'第 {i+1} 段的目标高度仍被玩家设施占用；请切换向上/向下或分段，未强行生成')
    segments=[{'segment':i,'reasons':sorted({r['reason'] for r in rows}),
               'object_ids':sorted({ident for r in rows for ident in r['ids']})[:12],
               'adjusted':any(result[j]!=levels[j] for j in (i,i+1))} for i,rows in hits]
    return result,{'mode':mode,'station_radius_m':radius,'changed_nodes':sum(a!=b for a,b in zip(levels,result))*2,
                   'track_segments':sum(any(r['reason']=='player_track' for r in rows) for _,rows in hits),
                   'station_segments':sum(any(r['reason']=='player_station' for r in rows) for _,rows in hits),
                   'planned_track_segments':sum(any(r['reason']=='player_track' and r['planned'] for r in rows) for _,rows in hits),
                   'segments':segments,'station_geometry':'ground-centre-circle','game_validated':False}
