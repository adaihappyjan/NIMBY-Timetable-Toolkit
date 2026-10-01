import json
import struct
from pathlib import Path

import pytest

import toolkit_autotrack as at
from toolkit_savereader import read_track_nodes, read_track_geometry


def fixture_raw():
    ids=[(1<<48)+(i<<16)+1 for i in range(4)]
    records=[]
    for i in range(4):
        neighbor=ids[i^2]
        records.append(at.record(ids[i],[None,neighbor] if i<2 else [neighbor,None],
                                 (10+i//2*0.001,20+i%2*0.00005),0,ids[i^1],bool(i%2)))
    station=(2<<48)+1
    definitions=b''.join(bytes([len(key)])+key.encode()+bytes([1,code,len(name)])+name.encode() for code,key,name in
                        [(2,'waw_track_hs_1','High speed'),(4,'waw_track_tram_1','Tram'),(6,'waw_track_mid_1','Medium speed')])
    return (at.uvarint(4)+b''.join(map(at.ident_bytes,ids))+at.uvarint(4)+b''.join(records)+
            at.uvarint(1)+at.ident_bytes(station)+at.uvarint(1)+at.ident_bytes(station)+bytes(100)+definitions)


def save_fixture(tmp_path):
    path=tmp_path/'source.nimbyrails5'
    path.write_bytes(bytes.fromhex('4e4d42590200010013000a00')+at.Zstd().compress(fixture_raw()))
    return path


def test_sample_suffixes_are_exact():
    # Independent bytes captured from the user-created middle-speed ground sample.
    primary=bytes.fromhex('000000010001000000000000000000000000000000000000000000000000020000a0400000000001')
    secondary_before=bytes.fromhex('000000010001000000000000000000000000000000000000')
    secondary_after=bytes.fromhex('0000000000020000a040000000000000000040')
    ident=(1<<48)+1; pair=ident+65536
    for secondary in (False,True):
        raw=at.record(ident,[None,pair],(-73.63,47.88),0,pair,secondary)
        expected=(secondary_before+at.ident_bytes(pair)+secondary_after if secondary else
                  primary+at.ident_bytes(pair)+struct.pack('<f',2))
        assert raw[50:]==expected
        assert len(raw)==(101 if secondary else 102)


def test_planned_opt_in_and_table_layout():
    raw=fixture_raw()
    assert read_track_geometry(raw).node_count==0
    assert len(read_track_nodes(raw,include_planned=True))==4
    ids,start,end,nodes=at.layout(raw)
    assert len(ids)==len(nodes)==4
    assert raw[end]==1


def test_append_preserves_source_and_blocks_repeat(tmp_path):
    source=save_fixture(tmp_path); original=source.read_bytes()
    request={'save':str(source),'preset':'vandry-dessane'}
    preview=at.dispatch(request)
    assert not list(tmp_path.glob('*.manifest.json'))
    assert preview['nodes']==84
    result=at.dispatch({**request,'apply':True,'fingerprint':preview['fingerprint'],'output':str(tmp_path/'new.nimbyrails5')})
    assert source.read_bytes()==original
    assert result['appended_nodes']==84
    new_raw=at.Zstd().decompress(at.split_save(Path(result['output_save']))[1])
    old_raw=fixture_raw()
    _,old_start,old_end,_=at.layout(old_raw)
    _,new_start,new_end,new_nodes=at.layout(new_raw)
    assert len(new_nodes)==88
    assert new_raw[new_start:new_start+old_end-old_start]==old_raw[old_start:old_end]
    assert new_raw[new_end:]==old_raw[old_end:]
    with pytest.raises(ValueError,match='中部'):
        at.dispatch({**request,'save':result['output_save']})


def test_changed_settings_or_source_refuse_write(tmp_path):
    source=save_fixture(tmp_path); request={'save':str(source),'preset':'vandry-dessane'}
    preview=at.dispatch(request)
    write={**request,'apply':True,'fingerprint':preview['fingerprint'],'output':str(tmp_path/'new.nimbyrails5')}
    with pytest.raises(ValueError,match='重新预览'):
        at.dispatch({**write,'variant':2})
    source.write_bytes(source.read_bytes()+b'changed')
    with pytest.raises((ValueError,RuntimeError)):
        at.dispatch(write)
    assert not (tmp_path/'new.nimbyrails5').exists()


def test_refuses_existing_output(tmp_path):
    source=save_fixture(tmp_path); request={'save':str(source),'preset':'vandry-dessane'}
    preview=at.dispatch(request)
    with pytest.raises(ValueError,match='不同'):
        at.dispatch({**request,'apply':True,'fingerprint':preview['fingerprint'],'output':str(source)})


@pytest.mark.parametrize('coords', [[], [[0,0]], [[0,0],[0,0]], [[0,0],[float('nan'),0]], [[179,0],[-179,0]]])
def test_invalid_routes(coords):
    with pytest.raises(ValueError):
        at.route_data({'geojson':{'type':'LineString','coordinates':coords}})


def test_bridge_crop_refused():
    xy,chain,scale,bridges=at.route_data({'preset':'vandry-dessane'})
    with pytest.raises(ValueError,match='桥梁'):
        at.prepare(fixture_raw(),{'preset':'vandry-dessane','start_m':sum(bridges[0][:2])/2})


def test_crossing_and_far_edges():
    assert at.clip_interval((50,-50),(50,50),(0,0),(100,0))==[50,50]
    assert at.clip_interval((0,100),(100,100),(0,0),(100,0)) is None


def test_zero_end_is_not_silently_full_route():
    with pytest.raises(ValueError,match='100 米'):
        at.prepare(fixture_raw(),{'preset':'vandry-dessane','end_m':0})


def test_web_task_request_and_output_guard(tmp_path,monkeypatch):
    import toolkit_webapp as web
    monkeypatch.setattr(web,'SAVE_DIR',tmp_path)
    monkeypatch.setattr(web,'TASK_DIR',tmp_path/'tasks')
    source=save_fixture(tmp_path)
    request={'save':str(source),'preset':'vandry-dessane'}
    args=web.TaskManager()._build_args('autotrack',request)
    assert args[0]=='autotrack'
    value=json.loads(Path(args[-1]).read_text('utf-8'))
    assert value['apply'] is False
    via = [{'coord': [30.005, 20]}]
    multi_args = web.TaskManager()._build_args('autotrack', {**request, 'preset': 'auto', 'via': via})
    assert json.loads(Path(multi_args[-1]).read_text('utf-8'))['via'] == via
    with pytest.raises(RuntimeError,match='预览'):
        web.TaskManager()._build_args('autotrack',{**request,'apply':True,'output':str(tmp_path/'new.nimbyrails5')})
    with pytest.raises(RuntimeError,match='存档目录'):
        web.TaskManager()._build_args('autotrack',{**request,'apply':True,'fingerprint':'x','output':str(tmp_path.parent/'elsewhere.nimbyrails5')})


def test_cleanup_recognizes_new_copies():
    from toolkit_cleanup import TOOL_COPY_RE, TOOL_PARTIAL_RE
    assert TOOL_COPY_RE.search('Route_Autotrack_20260930_030000.nimbyrails5')
    assert TOOL_PARTIAL_RE.search('Route_Autotrack_20260930_030000.nimbyrails5.partial')
    assert not TOOL_COPY_RE.search('Route.nimbyrails5')


def test_cleanup_protects_player_resaved_experiment(tmp_path):
    from toolkit_cleanup import _recognized_copy
    path=tmp_path/'Route_Autotrack_20260930_030000.nimbyrails5'
    path.write_bytes(b'generated')
    assert not _recognized_copy(path)
    path.with_suffix('.manifest.json').write_text(json.dumps({'operation':'autotrack',
        'output_save':str(path),'output_sha256':at.digest(b'generated')}),encoding='utf-8')
    assert _recognized_copy(path)
    path.write_bytes(b'new player work')
    assert not _recognized_copy(path)


def test_unknown_save_version(tmp_path):
    source=save_fixture(tmp_path)
    data=bytearray(source.read_bytes());data[10]=11;source.write_bytes(data)
    with pytest.raises(RuntimeError):
        at.dispatch({'save':str(source),'preset':'vandry-dessane'})


@pytest.fixture
def multi_route(monkeypatch):
    import toolkit_autoroute as ar
    calls = []
    def route(request, stations, progress=None):
        a, b = request['from_coord'], request['to_coord']
        calls.append((a, b))
        return {'type': 'LineString', 'coordinates': [a, b]}, {
            'snap_m': [0, 0], 'rail_types': ['rail'], 'tiles': 1,
            'map_path': 'fixture', 'map_size': 1, 'map_mtime_ns': 1}
    monkeypatch.setattr(ar, 'automatic_route', route)
    monkeypatch.setattr(at, 'station_catalog', lambda raw: [])
    return calls


def multi_request(tmp_path):
    return {'save': str(save_fixture(tmp_path)), 'preset': 'auto',
            'from_coord': [30, 20], 'via': [{'coord': [30.005, 20]}], 'to_coord': [30.01, 20]}


def test_multi_station_single_output_and_prior_leg_avoidance(tmp_path, multi_route):
    request = multi_request(tmp_path); before = Path(request['save']).read_bytes()
    progress = []
    preview = at.dispatch(request, progress=lambda *args: progress.append(args))
    assert preview['can_apply'] and preview['successful_legs'] == 2
    assert len(progress) == 2
    assert preview['legs'][1]['preview']['avoided_intervals'] > 0
    assert not list(tmp_path.glob('*.manifest.json'))
    output = tmp_path/'multi.nimbyrails5'
    result = at.dispatch({**request, 'apply': True, 'fingerprint': preview['fingerprint'], 'output': str(output)})
    assert output.is_file() and result['appended_nodes'] == preview['nodes']
    assert len(list(tmp_path.glob('*.manifest.json'))) == 1
    assert Path(request['save']).read_bytes() == before
    new_raw = at.Zstd().decompress(at.split_save(output)[1])
    _, _, old_end, _ = at.layout(fixture_raw())
    _, _, new_end, nodes = at.layout(new_raw)
    assert len(nodes) == 4+preview['nodes']
    assert new_raw[new_end:] == fixture_raw()[old_end:]


def test_bad_middle_station_reports_both_legs_but_keeps_other_preview(tmp_path, multi_route):
    request = multi_request(tmp_path)
    request.update(via=[{'station': 'missing'}, {'coord': [30.01, 20]}], to_coord=[30.015, 20])
    preview = at.dispatch(request)
    assert preview['failed_legs'] == 2 and preview['successful_legs'] == 1
    assert preview['waypoints'][1]['status'] == 'invalid'
    assert [leg['status'] for leg in preview['legs']] == ['error', 'error', 'ok']
    assert preview['legs'][0]['error'] == preview['legs'][1]['error']
    assert len(multi_route) == 1  # Never bridge over the missing station.
    output = tmp_path/'blocked.nimbyrails5'
    with pytest.raises(ValueError, match='仍有失败区间'):
        at.dispatch({**request, 'apply': True, 'fingerprint': preview['fingerprint'], 'output': str(output)})
    assert not output.exists() and not list(tmp_path.glob('*.partial'))
    request['via'].pop(0)
    assert at.dispatch(request)['can_apply']


def test_route_failure_is_local_and_does_not_skip_a_station(tmp_path, multi_route, monkeypatch):
    import toolkit_autoroute as ar
    route = ar.automatic_route
    def failing(request, stations):
        if request['from_coord'] == [30, 20]: raise ValueError('底图断线')
        return route(request, stations)
    monkeypatch.setattr(ar, 'automatic_route', failing)
    result = at.dispatch(multi_request(tmp_path))
    assert result['failed_legs'] == result['successful_legs'] == 1
    assert result['legs'][0]['error'] == '底图断线'
    assert multi_route == [([30.005, 20], [30.01, 20])]


def test_deleting_or_reordering_waypoint_invalidates_write(tmp_path, multi_route):
    request = multi_request(tmp_path); preview = at.dispatch(request)
    changed = {**request, 'via': [], 'apply': True, 'fingerprint': preview['fingerprint'], 'output': str(tmp_path/'no.nimbyrails5')}
    with pytest.raises(ValueError, match='重新预览'): at.dispatch(changed)
    assert not Path(changed['output']).exists()


def test_duplicate_waypoint_and_all_failed_plan(tmp_path, multi_route):
    request = multi_request(tmp_path); request['via'] = [{'coord': [30, 20]}]
    result = at.dispatch(request)
    assert result['failed_legs'] == 2 and not result['can_apply']
    assert '重复' in result['waypoints'][1]['errors'][0]
    assert result['nodes'] == 0


@pytest.mark.parametrize('via', [None, {}, [None]*39])
def test_multi_station_count_and_schema_bound(tmp_path, via):
    request = multi_request(tmp_path); request['via'] = via
    with pytest.raises(ValueError, match='40 站'): at.dispatch(request)


def test_multi_station_rejects_ambiguous_mileage_crop(tmp_path, multi_route):
    request = multi_request(tmp_path); request['start_m'] = 100
    with pytest.raises(ValueError, match='里程'): at.dispatch(request)


def test_later_leg_overlapping_earlier_leg_requires_partial_approval(tmp_path, multi_route):
    request = multi_request(tmp_path); request['to_coord'] = [30.001, 20]
    result = at.dispatch(request)
    assert result['successful_legs'] == 1 and result['failed_legs'] == 1
    assert '中部' in result['legs'][1]['error'] or '100 米' in result['legs'][1]['error']
    assert result['requires_partial_confirmation']


def test_partial_blueprint_writes_only_good_legs_and_preserves_gaps(tmp_path, multi_route, monkeypatch):
    import toolkit_autoroute as ar
    route = ar.automatic_route
    def failing(request, stations):
        if request['from_coord'] == [30.005, 20]: raise ValueError('中间区间底图断线')
        return route(request, stations)
    monkeypatch.setattr(ar, 'automatic_route', failing)
    request = multi_request(tmp_path)
    request.update(via=[{'coord': [30.005, 20]}, {'coord': [30.01, 20]}], to_coord=[30.015, 20])
    before = Path(request['save']).read_bytes()
    preview = at.dispatch(request)
    assert preview['can_apply'] and preview['requires_partial_confirmation']
    assert preview['included_legs'] == [0, 2]
    assert [leg['index'] for leg in preview['skipped_legs']] == [1]
    assert preview['skipped_legs'][0]['error'] == '中间区间底图断线'
    output = tmp_path/'partial-good.nimbyrails5'
    write = {**request, 'apply': True, 'fingerprint': preview['fingerprint'], 'output': str(output)}
    for consent in (False, None, 'true', 1):
        with pytest.raises(ValueError): at.dispatch({**write, 'allow_partial': consent})
        assert not output.exists()
    result = at.dispatch({**write, 'allow_partial': True})
    assert result['partial_output'] and result['appended_nodes'] == preview['nodes']
    assert Path(request['save']).read_bytes() == before
    manifest = json.loads(output.with_suffix('.manifest.json').read_text('utf-8'))
    assert manifest['included_legs'] == [0, 2] and manifest['skipped_legs'] == preview['skipped_legs']
    raw = at.Zstd().decompress(at.split_save(output)[1])
    _, _, end, nodes = at.layout(raw)
    old_ids, _, old_end, _ = at.layout(fixture_raw())
    assert raw[end:] == fixture_raw()[old_end:]
    added = {ident: node for ident, node in nodes.items() if ident not in old_ids}
    assert len(added) == preview['nodes']
    # No generated node or neighbor edge may bridge the deliberately absent leg.
    for node in added.values():
        assert node.lon <= 30.005001 or node.lon >= 30.009999
        for other in node.connections:
            if other in added:
                assert (node.lon < 30.0075) == (added[other].lon < 30.0075)


def test_all_failed_is_blocked_even_with_partial_consent(tmp_path, multi_route):
    request = multi_request(tmp_path); request['via'] = [{'station': 'missing'}]
    preview = at.dispatch(request)
    assert not preview['can_apply'] and not preview['requires_partial_confirmation']
    output = tmp_path/'no.nimbyrails5'
    with pytest.raises(ValueError, match='没有通过'):
        at.dispatch({**request, 'allow_partial': True, 'apply': True, 'fingerprint': preview['fingerprint'], 'output': str(output)})
    assert not output.exists()


def test_partial_selection_cannot_change_after_preview(tmp_path, multi_route, monkeypatch):
    import toolkit_autoroute as ar
    route = ar.automatic_route
    failing_index = [0]
    def changing(request, stations):
        if (request['from_coord'] == [30, 20]) == (failing_index[0] == 0): raise ValueError('局部失败')
        return route(request, stations)
    monkeypatch.setattr(ar, 'automatic_route', changing)
    request = multi_request(tmp_path); preview = at.dispatch(request)
    failing_index[0] = 1
    output = tmp_path/'stale.nimbyrails5'
    with pytest.raises(ValueError, match='重新预览'):
        at.dispatch({**request, 'allow_partial': True, 'apply': True, 'fingerprint': preview['fingerprint'], 'output': str(output)})
    assert not output.exists()


def test_map_change_during_plan_is_global_failure_not_skippable(tmp_path, multi_route, monkeypatch):
    import toolkit_autoroute as ar
    route = ar.automatic_route
    def changing(request, stations):
        geojson, info = route(request, stations)
        info['map_mtime_ns'] = len(multi_route)
        return geojson, info
    monkeypatch.setattr(ar, 'automatic_route', changing)
    request = multi_request(tmp_path)
    with pytest.raises(RuntimeError, match='底图.*改变'):
        at.dispatch({**request, 'allow_partial': True})
    assert not list(tmp_path.glob('*.partial')) and not list(tmp_path.glob('*.manifest.json'))


@pytest.mark.parametrize('multi', [False, True])
def test_over_150km_blueprint_preview_and_write(tmp_path, monkeypatch, multi):
    import math
    import toolkit_autoroute as ar

    def centerline(a, b):
        steps = math.ceil(abs(b[0]-a[0])/0.01)
        return {'type': 'LineString', 'coordinates': [
            [a[0]+(b[0]-a[0])*i/steps, a[1]] for i in range(steps+1)]}

    def route(request, stations):
        a, b = request['from_coord'], request['to_coord']
        ar.bounds_for(a, b, 3000)  # Each automatic leg still meets its own bound.
        return centerline(a, b), {'map_path': 'fixture', 'map_size': 1, 'map_mtime_ns': 1}

    source = save_fixture(tmp_path); original = source.read_bytes()
    request = {'save': str(source), 'geojson': centerline([30, 20], [32.01, 20])}
    if multi:
        monkeypatch.setattr(ar, 'automatic_route', route)
        monkeypatch.setattr(at, 'station_catalog', lambda raw: [])
        request = {'save': str(source), 'preset': 'auto', 'from_coord': [30, 20],
                   'via': [{'coord': [30.67, 20]}, {'coord': [31.34, 20]}], 'to_coord': [32.01, 20]}
    preview = at.dispatch(request)
    assert preview['length_m'] > 200_000
    if multi:
        assert preview['successful_legs'] == 3 and preview['failed_legs'] == 0
    output = tmp_path/'long.nimbyrails5'
    result = at.dispatch({**request, 'apply': True, 'fingerprint': preview['fingerprint'], 'output': str(output)})
    assert source.read_bytes() == original
    assert result['appended_nodes'] == preview['nodes']
    raw = at.Zstd().decompress(at.split_save(output)[1])
    ids, old_start, old_end, _ = at.layout(fixture_raw())
    _, start, end, nodes = at.layout(raw)
    assert len(nodes) == len(ids)+preview['nodes']
    assert raw[start:start+old_end-old_start] == fixture_raw()[old_start:old_end]
    assert raw[end:] == fixture_raw()[old_end:]


def test_distance_removal_preserves_minimum_spacing_and_point_limits():
    for coords, error in [([[30, 20], [30.0001, 20]], '至少'),
                          ([[30, 20], [30.03, 20]], '相邻节点'),
                          ([[30, 20]]*(at.MAX_POINTS+1), '节点')]:
        with pytest.raises(ValueError, match=error):
            at.route_data({'geojson': {'type': 'LineString', 'coordinates': coords}})


def test_total_node_budget_still_blocks_later_leg(tmp_path, multi_route, monkeypatch):
    monkeypatch.setattr(at, 'MAX_POINTS', 3)
    preview = at.dispatch(multi_request(tmp_path))
    assert preview['successful_legs'] == 1 and preview['failed_legs'] == 1
    assert '双轨节点' in preview['skipped_legs'][0]['error']


def test_distance_limit_help_matches_remaining_bounds():
    root = Path(__file__).resolve().parents[1]
    html = (root/'web/index.html').read_text('utf-8')
    assert '首尾距离和路线总长均不设公里数上限' in html and '0.1–100 公里' not in html
    assert '最多 150 公里' not in html


@pytest.fixture
def discovery_case(tmp_path, monkeypatch):
    import toolkit_autoroute as ar
    stations = [
        {'id': 'end', 'name': '终点', 'lon': 30.01, 'lat': 20.01},
        {'id': 'blueprint', 'name': '同名站', 'lon': 30.01, 'lat': 20.005},
        {'id': 'built', 'name': '同名站', 'lon': 30.005, 'lat': 20},
        {'id': 'start', 'name': '起点', 'lon': 30, 'lat': 20},
        {'id': 'diagonal', 'name': '直线附近但不沿铁路', 'lon': 30.005, 'lat': 20.005},
        {'id': 'nearby', 'name': '附近平行线待确认', 'lon': 30.005, 'lat': 20.001},
    ]
    monkeypatch.setattr(at, 'station_catalog', lambda raw: stations)
    monkeypatch.setattr(ar, 'automatic_route', lambda request, saved: (
        {'type': 'LineString', 'coordinates': [[30, 20], [30.01, 20], [30.01, 20.01]]},
        {'map_path': 'fixture', 'map_size': 1, 'map_mtime_ns': 1}))
    return {'save': str(save_fixture(tmp_path)), 'preset': 'auto', 'operation': 'discover',
            'from_station': 'start', 'to_station': 'end'}, stations


def test_discovery_uses_saved_stations_route_order_and_never_writes(discovery_case, tmp_path):
    request, stations = discovery_case
    before = Path(request['save']).read_bytes()
    result = at.dispatch(request)
    ids = [s['id'] for s in result['candidates']]
    assert ids == ['built', 'nearby', 'blueprint']
    assert set(ids) <= {s['id'] for s in stations}
    assert result['candidates'][0]['distance_m'] == 0
    assert 100 < result['candidates'][1]['distance_m'] < 120
    assert not result['candidates'][0]['ambiguous']
    assert result['source_sha256'] == at.digest(before)
    assert Path(request['save']).read_bytes() == before
    assert list(tmp_path.iterdir()) == [Path(request['save'])]
    with pytest.raises(ValueError, match='不能同时写入'):
        at.dispatch({**request, 'apply': True})


@pytest.mark.parametrize('changes', [{'from_station': None, 'from_coord': [30, 20]},
                                    {'to_station': 'missing'}, {'to_station': 'start'},
                                    {'preset': 'custom'}])
def test_discovery_requires_saved_distinct_endpoints(discovery_case, changes):
    request, _ = discovery_case
    with pytest.raises(ValueError): at.dispatch({**request, **changes})


def test_discovery_source_change_invalidates_followup(discovery_case):
    request, _ = discovery_case
    result = at.dispatch(request)
    source = Path(request['save'])
    source.write_bytes(source.read_bytes()+b'changed')
    with pytest.raises(ValueError, match='识别沿途站后改变'):
        at.dispatch({**request, 'operation': 'preview', 'discovery_source_sha256': result['source_sha256']})


def test_discovery_source_change_during_read_refused(discovery_case, monkeypatch):
    import toolkit_autoroute as ar
    request, _ = discovery_case
    route = ar.automatic_route
    def changing(*args):
        path = Path(request['save']); path.write_bytes(path.read_bytes()+b'changed')
        return route(*args)
    monkeypatch.setattr(ar, 'automatic_route', changing)
    with pytest.raises(ValueError, match='识别期间存档改变'): at.dispatch(request)


def test_discovery_loop_reports_ambiguous_mileage(discovery_case, monkeypatch):
    import toolkit_autoroute as ar
    request, _ = discovery_case
    monkeypatch.setattr(ar, 'automatic_route', lambda *args: (
        {'type': 'LineString', 'coordinates': [[30, 20], [30.01, 20], [30.01, 20.0001], [30, 20.0001]]}, {}))
    result = at.dispatch(request)
    assert next(s for s in result['candidates'] if s['id'] == 'built')['ambiguous']


def test_discovery_empty_candidates_do_not_invent_stations(discovery_case):
    request, stations = discovery_case
    stations[:] = [s for s in stations if s['id'] in ('start', 'end')]
    assert at.dispatch(request)['candidates'] == []


def test_worker_preserves_discovery_binding_and_partial_consent(tmp_path, monkeypatch):
    import toolkit_webapp as web
    monkeypatch.setattr(web, 'SAVE_DIR', tmp_path)
    monkeypatch.setattr(web, 'TASK_DIR', tmp_path/'tasks')
    source = save_fixture(tmp_path)
    request = {'save': str(source), 'preset': 'auto', 'operation': 'discover',
               'discovery_source_sha256': 'snapshot', 'allow_partial': True,
               'obstacle_mode': 'tunnel', 'player_obstacle_mode': 'bridge', 'player_station_radius_m': 80}
    args = web.TaskManager()._build_args('autotrack', request)
    forwarded = json.loads(Path(args[-1]).read_text('utf-8'))
    assert forwarded['operation'] == 'discover' and forwarded['apply'] is False
    assert forwarded['discovery_source_sha256'] == 'snapshot' and forwarded['allow_partial'] is True
    assert forwarded['obstacle_mode'] == 'tunnel'
    assert forwarded['player_obstacle_mode'] == 'bridge' and forwarded['player_station_radius_m'] == 80
