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
