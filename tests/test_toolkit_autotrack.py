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
