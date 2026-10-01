import random
from pathlib import Path

import pytest
import toolkit_binary as binary
import toolkit_savereader as sr
import toolkit_autotrack as at
from test_toolkit_autotrack import fixture_raw, multi_request, multi_route


@pytest.mark.parametrize('payload',[b'',b'\0'*100000,bytes(range(256))*1000,random.Random(13).randbytes(100001)],
                         ids=['empty','zeros','all-bytes','random'])
def test_native_bytes_pointer_roundtrip_preserves_nuls_and_exact_length(payload):
    z=binary.Zstd()
    compressed=z.compress(payload)
    assert z.decompress(compressed)==payload
    assert payload==z.decompress(z.compress(payload,level=1))


def test_corrupt_frame_and_missing_magic_still_rejected():
    z=binary.Zstd()
    with pytest.raises(RuntimeError):z.decompress(b'not a frame')
    with pytest.raises(RuntimeError):z.decompress(z.compress(b'abcd')[:-2])
    with pytest.raises(RuntimeError,match='magic'):binary.split_save_bytes(b'not a save')


def test_split_already_read_snapshot_matches_file(tmp_path):
    data=b'NMBY'+b'\0'*8+binary.Zstd().compress(fixture_raw())
    path=tmp_path/'sample';path.write_bytes(data)
    assert binary.split_save(path)==binary.split_save_bytes(data)


def test_node_only_adapter_preserves_all_records_without_discarded_geometry(monkeypatch):
    raw=fixture_raw();expected={}
    sr.read_track_geometry(raw,include_planned=True,_node_sink=expected)
    def unexpected(*args):raise AssertionError('node-only reader computed cartographic distances')
    monkeypatch.setattr(sr,'_haversine_m',unexpected)
    assert sr.read_track_nodes(raw,include_planned=True)==expected


def test_longitude_span_over_six_degrees_is_not_a_dateline_crossing():
    points=[[-89-i*.01,50] for i in range(811)]
    _,chain,_,_=at.route_data({'geojson':{'type':'LineString','coordinates':points}})
    assert chain[-1]>570000
    with pytest.raises(ValueError,match='日期线'):
        at.route_data({'geojson':{'type':'LineString','coordinates':[[179.999,50],[-179.999,50]]}})


def test_twenty_one_stations_fit_one_plan(tmp_path,multi_route):
    req=multi_request(tmp_path)
    req.update(from_coord=[30,20],via=[{'coord':[30+i*.005,20]} for i in range(1,20)],to_coord=[30.1,20])
    result=at.dispatch(req)
    assert len(result['waypoints'])==21 and result['successful_legs']==20
    assert result['nodes']<=8000


def test_automatic_clearance_retreats_outside_whole_structures_only():
    start,end,info=at.safe_structure_crop(0,1000,100,950,[(900,970,2)],50)
    assert (start,end)==(100,850) and info['end_extra_m']==100
    start,end,info=at.safe_structure_crop(0,1000,100,950,[(80,150,1)],50)
    assert (start,end)==(200,950) and info['start_extra_m']==100
    with pytest.raises(ValueError,match='桥梁'):
        at.safe_structure_crop(100,1000,100,950,[(80,150,2)],50)
    with pytest.raises(ValueError,match='100 米'):
        at.safe_structure_crop(0,1000,100,950,[(80,920,2)],50)


def test_structure_retreat_handles_nearby_bridges_without_extending_into_track():
    start,end,info=at.safe_structure_crop(0,1000,50,950,[(820,880,2),(900,970,2)],50)
    assert start==50 and end==770 and info['end_extra_m']==180
