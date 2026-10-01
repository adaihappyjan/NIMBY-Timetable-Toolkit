import json
from pathlib import Path

import pytest

import toolkit_autoroute as route
import toolkit_autotrack as at
from test_toolkit_autotrack import fixture_raw, save_fixture


def feature(points,subclass='rail',brunnel=None,layer=0):
    return {'x':8192,'y':8192,'extent':4096,'properties':{'subclass':subclass,'brunnel':brunnel,'layer':layer},
            'geometry':{'type':1,'coordinates':[[{'x':x,'y':y} for x,y in points]]}}


def ll(x,y):return route.lonlat((8192*4096+x,8192*4096+y))


def test_continuous_route_split_same_edge():
    data,info=route.route_graph([feature([(0,100),(4000,100)])],ll(200,100),ll(3800,100))
    points=data['features'][0]['geometry']['coordinates']
    assert points[0]==pytest.approx(ll(200,100))
    assert points[-1]==pytest.approx(ll(3800,100))
    assert info['snap_m']==[0,0]


def test_waypoint_near_existing_vertex_does_not_emit_microscopic_edge():
    data,info=route.route_graph([feature([(100,100),(2000,100),(4000,100)])],ll(2000.00001,100),ll(3800,100))
    points=data['features'][0]['geometry']['coordinates']
    assert len(points)==2
    assert points[0]==pytest.approx(ll(2000,100))
    at.route_data({'geojson':data})  # No sub-5 cm duplicate vertex remains.


def test_no_junction_invented_at_crossing():
    with pytest.raises(ValueError,match='没有连续'):
        route.route_graph([feature([(0,1000),(4000,1000)]),feature([(2000,0),(2000,4000)])],ll(100,1000),ll(2000,3900))


def test_no_join_across_layers():
    with pytest.raises(ValueError,match='没有连续'):
        route.route_graph([feature([(0,100),(1000,100)],layer=0),feature([(1000,100),(4000,100)],layer=1)],ll(100,100),ll(3900,100))


def test_bridge_head_can_meet_exact_ground_turnaround_vertex():
    ground=feature([(100,100),(2000,100),(100,120)])
    bridge=feature([(2000,100),(3000,100)],brunnel='bridge',layer=1)
    data,info=route.route_graph([ground,bridge],ll(200,100),ll(2900,100))
    assert info['structure_tip_joins']==1
    at.route_data({'geojson':data})


@pytest.mark.parametrize('change',['through','crossing','gap','layer','family','ambiguous'])
def test_structure_tip_stitch_does_not_invent_crossings(change):
    ground=feature([(100,100),(2000,100),(100,120)])
    bridge=feature([(2000,100),(3000,100)],brunnel='bridge',layer=1)
    if change=='through':ground=feature([(100,100),(2000,100),(4000,100)])
    if change=='crossing':ground=feature([(2000,-1000),(2000,100),(2000,1200)])
    if change=='gap':bridge=feature([(2000,100.1),(3000,100.1)],brunnel='bridge',layer=1)
    if change=='layer':bridge['properties']['layer']=2
    if change=='family':bridge['properties']['subclass']='tram'
    features=[ground,bridge]
    if change=='ambiguous':features.insert(1,feature([(100,80),(2000,100),(100,90)],layer=1))
    # Direct helper verification avoids coincident projection choosing a nearer
    # parallel edge and falsely reporting a successful end-to-end route.
    signature=lambda f:(f['properties']['subclass'],f['properties']['layer'],f['properties']['brunnel'] or '')
    nodes=[];edges=[]
    for f in features:
        offset=len(nodes);pts=f['geometry']['coordinates'][0]
        nodes.extend([((p['x'],p['y']),signature(f),i in (0,len(pts)-1)) for i,p in enumerate(pts)])
        edges.extend((offset+i,offset+i+1,f['properties']) for i in range(len(pts)-1))
    assert route.stitch_structure_tips(nodes,edges)[1]==0


def test_bridge_tunnel_and_all_rail_families():
    for family in sorted(route.RAIL_TYPES):
        features=[feature([(0,100),(1000,100)],family),feature([(1000,100),(2000,100)],family,'bridge',1),
                  feature([(2000,100),(3000,100)],family),feature([(3000,100),(4000,100)],family,'tunnel',-1)]
        data,info=route.route_graph(features,ll(100,100),ll(3900,100),family)
        assert [f['properties']['brunnel'] for f in data['features'][1:]]==['bridge','tunnel']
        assert info['rail_types']==[family]


def test_tile_seam_snap_and_buffer_clipping():
    a=feature([(3000,100),(4160,100)])
    b=feature([(-64,100.4),(1000,100.4)]);b['x']+=1
    data,_=route.route_graph([a,b],ll(3100,100),ll(5000,100.4))
    assert len(data['features'][0]['geometry']['coordinates'])==3


def test_filters_and_distance_limits():
    with pytest.raises(ValueError,match='没有所选'):
        route.route_graph([feature([(0,100),(4000,100)])],ll(100,100),ll(3000,100),'tram')
    with pytest.raises(ValueError,match='500 米'):
        route.route_graph([feature([(0,100),(4000,100)])],ll(100,3000),ll(3000,100))
    with pytest.raises(ValueError,match='日期线'):
        route.bounds_for([179,0],[-179,0],3000)


def test_over_100km_bounds_are_allowed_but_short_and_dateline_are_not():
    bounds = route.bounds_for([30, 20], [32, 20], 3000)
    assert bounds[2] > bounds[0]
    with pytest.raises(ValueError, match='至少'):
        route.bounds_for([30, 20], [30.00001, 20], 3000)


def test_auto_retries_common_family_without_linking_distinct_networks():
    features=[feature([(0,100),(1000,100)],'subway'),feature([(0,300),(4000,300)],'light_rail')]
    data,info=route.choose_route(features,ll(100,100),ll(3900,300))
    assert info['rail_types']==['light_rail']
    assert info['auto_family_fallback'] is True
    assert 100<info['snap_m'][0]<150


def test_three_track_types_and_structures_write_roundtrip():
    for variant in (2,4,6):
        for mode,level in [('ground',0),('bridge',2),('tunnel',1)]:
            prepared=at.prepare(fixture_raw(),{'preset':'vandry-dessane','variant':variant,'structure_mode':mode})
            result=at.patch(fixture_raw(),prepared)
            nodes=at.read_track_nodes(result,include_planned=True)
            new=list(nodes.values())[4:]
            assert all(n.variant==variant and n.level_code==level for n in new)


def test_independent_bridge_tunnel_types_and_unknown_definition():
    coords=[ll(x,100) for x in (0,500,1500,2000,3000,4000)]
    data={'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'LineString','coordinates':coords}}]}
    for brunnel,a,b in [('bridge',1,2),('tunnel',3,4)]:
        data['features'].append({'type':'Feature','properties':{'kind':'structure','brunnel':brunnel},'geometry':{'type':'LineString','coordinates':[coords[a],coords[b]]}})
    prepared=at.prepare(fixture_raw(),{'geojson':data,'variant':6,'bridge_variant':2,'tunnel_variant':4})
    assert prepared[0]['variants']==[6,2,2,4,4,6]
    at.patch(fixture_raw(),prepared)
    with pytest.raises(ValueError,match='轨道定义'):
        at.prepare(fixture_raw().replace(b'waw_track_mid_1',b'custom_track_01'),{'preset':'vandry-dessane'})


def test_automatic_file_discovery_and_stale_file(tmp_path):
    source=save_fixture(tmp_path)
    path=tmp_path/'route.geojson'
    data={'type':'LineString','coordinates':[ll(0,0),ll(2000,0)]}
    path.write_text(json.dumps(data),encoding='utf-8')
    (tmp_path/'export.json').write_text('{"schedules":[]}',encoding='utf-8')
    assert at.route_files(tmp_path)[0]['name']=='route.geojson'
    request={'save':str(source),'preset':'file','route_path':str(path)}
    preview=at.dispatch(request)
    data['coordinates'][1]=ll(3000,0);path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='重新预览'):
        at.dispatch({**request,'apply':True,'fingerprint':preview['fingerprint'],'output':str(tmp_path/'new.nimbyrails5')})


@pytest.mark.parametrize('point',[(0,0),(150,-30),(-70,-20),(120,30)])
def test_station_catalog_not_northern_hemisphere_only(point):
    import struct
    raw=fixture_raw();station=(2<<48)+1
    old=at.ident_bytes(station)+bytes(100)
    new=at.ident_bytes(station)+bytes.fromhex('84c00201')+struct.pack('<dd',*at.lonlat_to_mercator(*point))+b'\x04Test'+bytes(75)
    raw=raw.replace(old,new)
    stations=at.station_catalog(raw)
    assert len(stations)==1
    assert (stations[0]['lon'],stations[0]['lat'])==pytest.approx(point,abs=1e-8)


def test_missing_runtime_is_actionable(monkeypatch):
    monkeypatch.setattr(route,'node_runtime',lambda:None)
    with pytest.raises(ValueError,match='Node.js'):
        route.decode(Path('osm400.pmtiles'),[0,0,0,0])


def test_single_character_station_name():
    import struct
    station=(2<<48)+1
    raw=fixture_raw().replace(at.ident_bytes(station)+bytes(100),
        at.ident_bytes(station)+bytes.fromhex('84c00201')+struct.pack('<dd',*at.lonlat_to_mercator(10,-30))+b'\x01A'+bytes(78))
    assert at.station_catalog(raw)[0]['name']=='A'


def tile_set(bounds):
    w,n,e,s=bounds
    return {(x,y) for x in range(w,e+1) for y in range(n,s+1)}


@pytest.mark.parametrize('bounds,previous',[
    ([0,0,2048,1],None),([0,0,80,80],[10,20,30,40]),
    ([0,0,12,12],[0,0,10,10]),([10,10,20,20],[10,10,20,20]),
])
def test_unread_batches_cover_only_new_tiles_without_duplicates(bounds,previous):
    seen=set()
    for batch in route.unread_batches(bounds,previous):
        cells=tile_set(batch)
        assert len(cells)<=1024
        assert not seen & cells
        seen.update(cells)
    assert seen==tile_set(bounds)-(tile_set(previous) if previous else set())


def mock_local_map(tmp_path,monkeypatch):
    path=tmp_path/'osm400.pmtiles';path.write_bytes(b'test map')
    monkeypatch.setattr(route,'game_maps',lambda:[str(path)])
    return path


def test_automatic_route_follows_long_detour_beyond_eight_km(tmp_path,monkeypatch):
    mock_local_map(tmp_path,monkeypatch)
    # Both ends are on the same longitude, but the continuous track bends
    # 12 km east. The old 3/8 km rectangle clipped this into two components.
    pixels=[(100,100),(20100,40100),(20100,240100),(100,280100)]
    origin=8192*4096
    world=[(origin+x,origin+y) for x,y in pixels]
    seen=set();calls=[]
    def decode(path,bounds,**kwargs):
        cells=tile_set(bounds)
        assert not cells & seen
        assert len(cells)<=1024
        assert 0<kwargs['timeout']<=90
        seen.update(cells);calls.append(bounds)
        features=[]
        for x,y in sorted(cells):
            box=(x*4096,y*4096,(x+1)*4096,(y+1)*4096)
            if not any(route.clip(a,b,box) for a,b in zip(world,world[1:])):continue
            f=feature([(px-x*4096,py-y*4096) for px,py in world])
            f.update(x=x,y=y);features.append(f)
        return {'features':features,'tiles':len(cells),'bytesRead':len(cells)*10}
    monkeypatch.setattr(route,'decode',decode)
    data,info=route.automatic_route({'from_coord':ll(*pixels[0]),'to_coord':ll(*pixels[-1])},[])
    assert info['search_padding_m']==16000
    assert 1024<info['searched_tiles']==len(seen)<=4096
    assert info['decode_batches']==len(calls)
    assert info['bytes_read']==len(seen)*10
    assert info['snap_m']==[0,0]
    assert info['route_length_m']>85000
    # Still a real graph path, suitable for the blueprint geometry reader.
    at.route_data({'geojson':data})


def test_automatic_route_stops_after_first_success(tmp_path,monkeypatch):
    mock_local_map(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(route,'decode',lambda path,bounds,**kw: (
        calls.append(bounds) or {'features':[feature([(0,100),(4000,100)])],'tiles':1,'bytesRead':10}))
    _,info=route.automatic_route({'from_coord':ll(100,100),'to_coord':ll(3900,100)},[])
    assert len(calls)==1 and info['search_padding_m']==3000


@pytest.mark.parametrize('limit,value,decoded',[
    ('MAX_SEARCH_BYTES',5,{'features':[],'tiles':1,'bytesRead':10}),
    ('MAX_SEARCH_JSON',5,{'features':[],'tiles':1,'bytesRead':1}),
    ('MAX_SEARCH_FEATURES',0,{'features':[feature([(0,100),(4000,100)])],'tiles':1,'bytesRead':1}),
])
def test_automatic_route_enforces_aggregate_data_limits(tmp_path,monkeypatch,limit,value,decoded):
    mock_local_map(tmp_path,monkeypatch)
    monkeypatch.setattr(route,limit,value)
    monkeypatch.setattr(route,'decode',lambda *a,**kw:decoded)
    with pytest.raises(ValueError,match='累计底图数据过大'):
        route.automatic_route({'from_coord':ll(100,100),'to_coord':ll(3900,100)},[])


def test_rectangle_limit_switches_to_network_search(tmp_path,monkeypatch):
    mock_local_map(tmp_path,monkeypatch)
    first=route.bounds_for(ll(100,100),ll(3900,100),3000)
    monkeypatch.setattr(route,'MAX_SEARCH_TILES',len(tile_set(first)))
    monkeypatch.setattr(route,'decode',lambda *a,**kw:{'features':[],'tiles':1,'bytesRead':1})
    def disconnected(*args):raise ValueError('没有连续铁路路径')
    monkeypatch.setattr(route,'choose_route',disconnected)
    calls=[]
    monkeypatch.setattr(route,'network_route',lambda *args:calls.append(args) or ('sparse',{}))
    assert route.automatic_route({'from_coord':ll(100,100),'to_coord':ll(3900,100)},[])==('sparse',{})
    assert len(calls)==1


def test_data_budget_is_shared_by_expansion_batches(tmp_path,monkeypatch):
    mock_local_map(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(route,'MAX_SEARCH_BYTES',10)
    def decode(*args,**kwargs):
        calls.append(args)
        return {'features':[],'tiles':1,'bytesRead':6}
    def disconnected(*args):raise ValueError('没有连续铁路路径')
    monkeypatch.setattr(route,'decode',decode)
    monkeypatch.setattr(route,'choose_route',disconnected)
    with pytest.raises(ValueError,match='累计底图数据过大'):
        route.automatic_route({'from_coord':ll(100,100),'to_coord':ll(3900,100)},[])
    assert len(calls)==2


def test_search_deadline_stops_further_batches(tmp_path,monkeypatch):
    mock_local_map(tmp_path,monkeypatch);clock=[0];calls=[]
    monkeypatch.setattr(route.time,'monotonic',lambda:clock[0])
    def decode(*args,**kwargs):
        calls.append(args);clock[0]=121
        return {'features':[],'tiles':1,'bytesRead':1}
    monkeypatch.setattr(route,'decode',decode)
    with pytest.raises(ValueError,match='120 秒'):
        route.automatic_route({'from_coord':ll(100,100),'to_coord':ll(3900,100)},[])
    assert len(calls)==1


def test_map_change_between_batches_rejects_mixed_snapshot(tmp_path,monkeypatch):
    path=mock_local_map(tmp_path,monkeypatch)
    def decode(*args,**kwargs):
        path.write_bytes(b'changed map snapshot')
        return {'features':[],'tiles':1,'bytesRead':1}
    monkeypatch.setattr(route,'decode',decode)
    with pytest.raises(ValueError,match='底图在读取期间改变'):
        route.automatic_route({'from_coord':ll(100,100),'to_coord':ll(3900,100)},[])


def test_unconnected_rectangle_switches_to_rail_frontier(tmp_path,monkeypatch):
    mock_local_map(tmp_path,monkeypatch)
    monkeypatch.setattr(route,'decode',lambda *a,**kw:{'features':[],'tiles':1,'bytesRead':1})
    def disconnected(*args):raise ValueError('没有连续铁路路径')
    monkeypatch.setattr(route,'choose_route',disconnected)
    calls=[]
    monkeypatch.setattr(route,'network_route',lambda *args:calls.append(args) or ('sparse',{}))
    assert route.automatic_route({'from_coord':ll(100,100),'to_coord':ll(3900,100)},[])==('sparse',{})
    assert len(calls)==1


def test_small_quantisation_gap_at_adjacent_tile_seam_is_joined():
    a=feature([(3000,100),(4160,100)])
    b=feature([(-64,102.5),(1000,102.5)]);b['x']+=1
    data,info=route.route_graph([a,b],ll(3100,100),ll(5000,102.5))
    assert info['tile_seam_joins']==1
    at.route_data({'geojson':data})


@pytest.mark.parametrize('change',['layer','structure','angle','gap','same-tile'])
def test_extra_seam_tolerance_never_bridges_unrelated_railways(change):
    a=feature([(3000,100),(4160,100)])
    b=feature([(-64,102.5),(1000,102.5)]);b['x']+=1
    end=ll(5000,102.5)
    if change=='layer':b['properties']['layer']=1
    if change=='structure':b['properties']['brunnel']='bridge'
    if change=='angle':b=feature([(0,102.5),(1000,2000)]);b['x']+=1;end=ll(5000,1800)
    if change=='gap':b=feature([(-64,104),(1000,104)]);b['x']+=1;end=ll(5000,104)
    if change=='same-tile':a=feature([(100,100),(2000,100)]);b=feature([(2000,102.5),(4000,102.5)]);end=ll(3900,102.5)
    start=ll(200,100) if change=='same-tile' else ll(3100,100)
    with pytest.raises(ValueError,match='没有连续'):
        route.route_graph([a,b],start,end)


def test_ambiguous_parallel_seam_continuations_are_not_joined():
    a=feature([(3000,100),(4096,100)])
    b=feature([(0,102.5),(1000,102.5)]);b['x']+=1
    c=feature([(0,97.5),(1000,97.5)]);c['x']+=1
    with pytest.raises(ValueError,match='没有连续'):
        route.route_graph([a,b,c],ll(3100,100),ll(5000,102.5))


def test_shallow_border_crossing_quantisation_is_measured_across_track():
    # A 5-unit border offset is <1 unit perpendicular to this shallow track.
    a=feature([(100,3900),(1080,4096)])
    b=feature([(1085,0),(2085,200)]);b['y']+=1
    data,info=route.route_graph([a,b],ll(100,3900),ll(2085,4296))
    assert info['tile_seam_joins']==1
    at.route_data({'geojson':data})


@pytest.mark.parametrize('gap,angle,heading,joined',[
    (5,10,0,1), (8,5,0,1), (8.01,5,0,0),
    (5,15,0,0), (5,5,4,0),
])
def test_shallow_seam_retains_distance_lateral_and_heading_guards(gap,angle,heading,joined):
    def tangent(degrees):
        return (route.math.cos(route.math.radians(degrees)),route.math.sin(route.math.radians(degrees)))
    signature=('rail',0,'')
    nodes=[((100,4096),signature,True),((100+gap,4096),signature,True)]
    t=tangent(angle);u=tangent(angle+heading)
    seams=[(0,1,1,-1,(0,0),tuple(-v for v in t)),(1,1,1,1,(0,1),u)]
    assert route.stitch_tile_seams(nodes,[],seams)[1]==joined


def test_single_family_disconnect_does_not_rebuild_identical_graph(monkeypatch):
    calls=[]
    def disconnected(*args):
        calls.append(args)
        raise ValueError('没有连续铁路路径')
    monkeypatch.setattr(route,'route_graph',disconnected)
    with pytest.raises(ValueError,match='没有连续'):
        route.choose_route([feature([(0,0),(100,100)])],ll(0,0),ll(100,100))
    assert len(calls)==1


@pytest.mark.parametrize('budget_end',[False,True])
@pytest.mark.parametrize('batches',[4,7])
def test_graph_backoff_checks_last_batch_even_below_threshold(tmp_path,monkeypatch,budget_end,batches):
    path=mock_local_map(tmp_path,monkeypatch)
    calls=[];attempts=[]
    monkeypatch.setattr(route,'MAX_NETWORK_TILES',256*batches if budget_end else 16384)
    def decode(request,**kwargs):
        used={tuple(p) for p in request['visited']}
        cells=list(request['tiles'])
        for x in range(10000):
            p=[x,0]
            if tuple(p) not in used and p not in cells:cells.append(p)
            if len(cells)>=256:break
        cells=cells[:256];calls.append(cells)
        return {'features':[],'tiles':len(cells),'bytesRead':1,'inspected':cells,
                'frontier':[[12000+len(calls),0]] if len(calls)<batches or budget_end else []}
    def choose(*args):
        attempts.append(len(calls))
        if len(calls)<batches:raise ValueError('没有连续铁路路径')
        return {},{}
    monkeypatch.setattr(route,'decode_request',decode)
    monkeypatch.setattr(route,'choose_route',choose)
    _,info=route.network_route(path,[ll(100,100),ll(3000,100)])
    assert attempts==([1,2,3,4] if batches==4 else [1,2,3,5,7])
    assert info['graph_attempts']==len(attempts)


def test_collinear_compaction_preserves_bends_structures_and_edge_length():
    coords=[ll(x,100) for x in range(0,4001,100)]+[ll(4000,1000)]
    structure={'geometry':{'coordinates':[coords[3],coords[5]]}}
    result=route.compact_alignment(coords,[structure],40075016.686/route.N)
    assert result[0]==coords[0] and result[-1]==coords[-1]
    assert coords[3] in result and coords[5] in result and coords[-2] in result
    assert len(result)<10
    assert all(route.math.dist(route.tile_point(a),route.tile_point(b))*40075016.686/route.N<=1500.001 for a,b in zip(result,result[1:]))


def test_large_rectangle_routes_with_small_actual_tile_budget(tmp_path,monkeypatch):
    mock_local_map(tmp_path,monkeypatch)
    start,end=[-79.335,44.748],[-81.724,47.676]
    assert len(tile_set(route.bounds_for(start,end,3000)))>20000
    calls=[];progress=[]
    def decode(request,**kw):
        assert request['follow'] is True and request['railType']=='auto'
        assert request['limit']<=256 and 0<kw['timeout']<=90
        calls.append(request)
        return {'features':[],'tiles':len(request['tiles']),'bytesRead':100,'inspected':request['tiles'],'frontier':[]}
    monkeypatch.setattr(route,'decode_request',decode)
    monkeypatch.setattr(route,'choose_route',lambda *args:({'type':'FeatureCollection'},{}))
    _,info=route.automatic_route({'from_coord':start,'to_coord':end},[],progress=lambda *args:progress.append(args))
    assert len(calls)==1 and info['search_method']=='railway-frontier'
    assert info['searched_tiles']<20 and progress


def test_network_exhaustion_does_not_fabricate_a_route(tmp_path,monkeypatch):
    path=mock_local_map(tmp_path,monkeypatch)
    monkeypatch.setattr(route,'decode_request',lambda request,**kw:{'features':[],'tiles':len(request['tiles']),
        'bytesRead':1,'inspected':request['tiles'],'frontier':[]})
    def disconnected(*args):raise ValueError('没有连续铁路路径')
    monkeypatch.setattr(route,'choose_route',disconnected)
    with pytest.raises(ValueError,match='不会画直线补连'):
        route.network_route(path,[ll(100,100),ll(3000,100)])


@pytest.mark.parametrize('failure',['tile-budget','bytes','map-change','duplicate','timeout'])
def test_network_search_guards(tmp_path,monkeypatch,failure):
    path=mock_local_map(tmp_path,monkeypatch);clock=[0];calls=[]
    monkeypatch.setattr(route.time,'monotonic',lambda:clock[0])
    if failure=='tile-budget':monkeypatch.setattr(route,'MAX_NETWORK_TILES',1)
    if failure=='bytes':monkeypatch.setattr(route,'MAX_SEARCH_BYTES',0)
    def decode(request,**kw):
        calls.append(request)
        if failure=='map-change':path.write_bytes(b'changed')
        if failure=='timeout':clock[0]=241
        return {'features':[],'tiles':1,'bytesRead':1,
                'inspected':[] if failure=='duplicate' else request['tiles'][:request['limit']], 'frontier':[[1,1]]}
    monkeypatch.setattr(route,'decode_request',decode)
    def disconnected(*args):raise ValueError('没有连续铁路路径')
    monkeypatch.setattr(route,'choose_route',disconnected)
    expected={'tile-budget':'实际地图块处理上限','bytes':'累计底图数据过大','map-change':'底图在读取期间改变','duplicate':'未推进或重复','timeout':'240 秒'}[failure]
    with pytest.raises(ValueError,match=expected):route.network_route(path,[ll(100,100),ll(3000,100)])
