import math
import pytest
import toolkit_obstacles as ob
import toolkit_autoroute as ar

def coord(x,y):return ar.lonlat((x,y))

def feature(kind,parts,layer='water',props=None):
    return {'x':8192,'y':6000,'extent':4096,'layer':layer,'properties':props or {'class':'lake' if layer=='water' else 'minor'},'geometry':{'type':kind,'coordinates':[[{'x':x,'y':y} for x,y in p] for p in parts]}}

def coords(points):return [coord(8192*4096+x,6000*4096+y) for x,y in points]

def test_crossing_water_between_vertices_elevates_both_ends():
    water=feature(2,[[(400,0),(600,0),(600,1000),(400,1000),(400,0)]])
    result,report=ob.apply_features(coords([(0,500),(1000,500),(2000,500)]),[0,0,0],[water],'bridge')
    assert result==[2,2,0] and report['changed_nodes']==4 and report['water_segments']==1

def test_polygon_hole_and_outside_stay_ground():
    water=feature(2,[[(0,0),(1000,0),(1000,1000),(0,1000),(0,0)],[(100,100),(900,100),(900,900),(100,900),(100,100)]])
    assert ob.apply_features(coords([(300,500),(700,500)]),[0,0],[water],'bridge')[0]==[0,0]
    assert ob.apply_features(coords([(1500,500),(2000,500)]),[0,0],[water],'bridge')[0]==[0,0]

def test_road_tunnel_choice_and_preserve_existing_structures():
    road=feature(1,[[(500,0),(500,1000)]],'transportation')
    assert ob.apply_features(coords([(0,500),(1000,500)]),[0,0],[road],'tunnel')[0]==[1,1]
    assert ob.apply_features(coords([(0,500),(1000,500)]),[2,1],[road],'tunnel')[0]==[2,1]
    road['properties']['brunnel']='tunnel'
    assert ob.apply_features(coords([(0,500),(1000,500)]),[0,0],[road],'bridge')[0]==[0,0]

def test_collinear_road_overlap_and_waterway_detected():
    road=feature(1,[[(300,500),(700,500)]],'transportation')
    assert ob.apply_features(coords([(0,500),(1000,500)]),[0,0],[road],'bridge')[1]['road_segments']==1
    road['layer']='waterway';road['properties']={'class':'stream'}
    assert ob.apply_features(coords([(0,500),(1000,500)]),[0,0],[road],'bridge')[1]['water_segments']==1

def test_off_does_not_require_map_and_forced_mode_rejected():
    assert ob.avoid([[0,0],[1,1]],[0,0],{})==([0,0],None)
    with pytest.raises(ValueError,match='强制结构'):ob.avoid([[0,0],[1,1]],[0,0],{'obstacle_mode':'bridge','structure_mode':'ground'})

def test_invalid_geometry_and_deadline():
    f=feature(2,[[(0,0),(100,0),(100,100)]]);f['extent']=0
    with pytest.raises(ValueError,match='extent'):ob.apply_features(coords([(0,50),(200,50)]),[0,0],[f],'bridge')
    with pytest.raises(ValueError,match='120 秒'):ob.apply_features(coords([(0,50),(200,50)]),[0,0],[],'bridge',deadline=-1)


def test_map_changed_during_obstacle_scan_is_global_failure(tmp_path,monkeypatch):
    path=tmp_path/'osm400.pmtiles';path.write_bytes(b'map')
    monkeypatch.setattr(ob,'game_maps',lambda:[str(path)])
    def decode(*args,**kwargs):
        path.write_bytes(b'changed-map')
        return {'bytesRead':3,'features':[]}
    monkeypatch.setattr(ob,'decode_request',decode)
    with pytest.raises(RuntimeError,match='全部区间'):ob.avoid(coords([(0,50),(200,50)]),[0,0],{'obstacle_mode':'bridge'})


def test_layer_changes_use_bridge_speed_and_survive_binary_patch(monkeypatch):
    import toolkit_autotrack as at
    from test_toolkit_autotrack import fixture_raw
    monkeypatch.setattr(ob,'avoid',lambda coord,levels,request:([2]*len(levels),{'changed_nodes':len(levels)*2,'water_segments':1,'road_segments':0}))
    raw=fixture_raw()
    prepared=at.prepare(raw,{'preset':'vandry-dessane','bridge_variant':2,'variant':6,'obstacle_mode':'bridge'})
    assert all(v==2 for v in prepared[0]['variants'])
    patched=at.patch(raw,prepared)
    old=set(at.layout(raw)[0]);new=at.layout(patched)[3]
    assert all(n.level_code==2 and n.variant==2 for ident,n in new.items() if ident not in old)
