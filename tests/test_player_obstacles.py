from types import SimpleNamespace

import pytest

import toolkit_player_obstacles as ob
import toolkit_autotrack as at
from toolkit_coordedit import mercator_to_lonlat
from test_toolkit_autotrack import fixture_raw, save_fixture


def run(edges=(), *, stations=(), levels=None, base=None, points=None, **request):
    points=points or [(-100, 0), (100, 0)]
    nodes={}; projected={}
    for i,(a,b,la,lb,state) in enumerate(edges):
        first,second=2*i+1,2*i+2
        nodes[first]=SimpleNamespace(connections=[second],level_code=la,state_code=state)
        nodes[second]=SimpleNamespace(connections=[first],level_code=lb,state_code=state)
        projected[first],projected[second]=a,b
    return ob.avoid(list(enumerate(points)),levels or [0]*len(points),base or [0]*len(points),
                    nodes,projected,stations,1,{'player_obstacle_mode':'bridge',**request},points)


@pytest.mark.parametrize('state',[0,1])
@pytest.mark.parametrize('mode,target',[('bridge',2),('tunnel',1)])
def test_built_and_planned_crossings(state,mode,target):
    result,report=run([((0,-100),(0,100),0,0,state)],player_obstacle_mode=mode)
    assert result==[target,target] and report['changed_nodes']==4
    assert report['planned_track_segments']==state and not report['game_validated']


def test_occupied_target_refuses_and_other_direction_works():
    edges=[((0,-100),(0,100),0,0,0),((20,-100),(20,100),2,2,1)]
    with pytest.raises(ValueError,match='目标高度'):run(edges)
    assert run(edges,player_obstacle_mode='tunnel')[0]==[1,1]


def test_separated_track_preserved_and_unknown_layer_refused():
    assert run([((0,-100),(0,100),2,2,0)])[0]==[0,0]
    with pytest.raises(ValueError,match='未验证'):run([((0,-100),(0,100),4,4,0)])


def test_mixed_existing_heights_are_split_at_midpoint():
    edge=[((0,-100),(0,100),0,2,0)]
    assert run(edge,points=[(-100,70),(100,70)])[0]==[0,0]
    assert run(edge,points=[(-100,-70),(100,-70)])[0]==[2,2]


def test_recheck_neighbour_contacts_after_later_elevation():
    edges=[((-70,-100),(-70,100),2,2,0),((70,-100),(70,100),0,0,0)]
    # Raising middle endpoint moves the end half of previous segment too.
    with pytest.raises(ValueError,match='目标高度'):
        run(edges,points=[(-200,0),(0,0),(200,0)])


def test_conflicting_water_choice_and_existing_map_structure_not_overridden():
    edge=[((0,-100),(0,100),1,1,0)]
    with pytest.raises(ValueError,match='方向冲突'):run(edge,levels=[1,1])
    with pytest.raises(ValueError,match='原有桥隧'):run(edge,levels=[1,1],base=[1,1])


def station(x=0,y=0,ident='station'):
    lon,lat=mercator_to_lonlat(x,y)
    return {'id':ident,'lon':lon,'lat':lat}


def test_station_circle_radius_and_endpoint_exclusions():
    s=station(0,50)
    assert run(stations=[s])[0]==[2,2]
    assert run(stations=[s],player_station_radius_m=30)[0]==[0,0]
    assert run(stations=[s],from_station='station')[0]==[0,0]
    assert run(stations=[s],from_coord=[s['lon'],s['lat']])[0]==[0,0]
    assert run(stations=[station(-100,0)])[0]==[0,0]
    report=run(stations=[s])[1]
    assert report['station_segments']==1 and report['station_geometry']=='ground-centre-circle'


@pytest.mark.parametrize('radius',[0,201,True,None,float('nan'),'60'])
def test_radius_validation(radius):
    with pytest.raises(ValueError,match='10–200'):run(player_station_radius_m=radius)


def test_isolated_node_and_overflow_edge():
    node=SimpleNamespace(connections=[],level_code=0,state_code=1)
    assert ob.avoid([(0,(-100,0)),(1,(100,0))],[0,0],[0,0],{1:node},{1:(0,0)},[],1,
                    {'player_obstacle_mode':'bridge'},[(-100,0),(100,0)])[0]==[2,2]
    assert run([((0,-100000),(0,100000),0,0,0)])[0]==[2,2]


def test_off_and_forced_structure():
    assert run(player_obstacle_mode='off')==([0,0],None)
    with pytest.raises(ValueError,match='强制结构'):run(structure_mode='bridge')


def request():
    # Fixture rail goes east-west at lon 10..10.001, lat 20. New line crosses
    # it centrally, far outside the endpoint reservation zones.
    return {'geojson':{'type':'LineString','coordinates':[[10.0005,19.99],[10.0005,20.0],[10.0005,20.01]]},
            'player_obstacle_mode':'bridge','bridge_variant':2,'tunnel_variant':4}


def test_actual_patch_preserves_old_objects_and_uses_selected_speed():
    raw=fixture_raw(); req=request()
    with pytest.raises(ValueError,match='中部'):at.prepare(raw,{**req,'player_obstacle_mode':'off'})
    prepared=at.prepare(raw,req,stations=[])
    assert prepared[0]['player_obstacle_avoidance']['planned_track_segments']>0
    patched=at.patch(raw,prepared)
    ids,start,end,old=at.layout(raw); _,new_start,new_end,new=at.layout(patched)
    assert patched[new_start:new_start+end-start]==raw[start:end]
    assert patched[new_end:]==raw[end:]
    added=[n for ident,n in new.items() if ident not in old]
    assert any(n.level_code==2 for n in added)
    assert all(n.variant=={0:6,2:2}[n.level_code] for n in added)


def test_worker_preview_apply_roundtrip_and_changed_direction_refused(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    import toolkit_webapp as web
    monkeypatch.setattr(web,'TASK_DIR',tmp_path/'tasks')
    monkeypatch.setattr(web,'SAVE_DIR',tmp_path)
    source=save_fixture(tmp_path); original=source.read_bytes()
    req={**request(),'preset':'custom','save':str(source),'obstacle_mode':'off'}
    args=web.TaskManager()._build_args('autotrack',req)
    forwarded=json.loads(Path(args[-1]).read_text('utf-8'))
    preview=at.dispatch(forwarded)
    output=tmp_path/'result.nimbyrails5'
    write={**forwarded,'apply':True,'fingerprint':preview['fingerprint'],'output':str(output)}
    with pytest.raises(ValueError,match='重新预览'):at.dispatch({**write,'player_obstacle_mode':'tunnel'})
    assert not output.exists()
    result=at.dispatch(write)
    assert source.read_bytes()==original and result['appended_nodes']==6
    new=at.layout(at.Zstd().decompress(at.split_save(output)[1]))[3]
    assert len(new)==10
