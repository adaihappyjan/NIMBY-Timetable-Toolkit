"""Optimization contracts: never trade snapshot/record validation for speed."""
import inspect
import random
import struct

import pytest

import toolkit_autotrack as at
import toolkit_savereader as sr
from test_toolkit_autotrack import fixture_raw, multi_request, multi_route


def test_dispatch_reads_each_payload_once_and_drops_cache(tmp_path,monkeypatch,multi_route):
    original=at.read_track_nodes;calls=[]
    def counted(raw,**kwargs):
        calls.append(raw)
        return original(raw,**kwargs)
    monkeypatch.setattr(at,'read_track_nodes',counted)
    request=multi_request(tmp_path)
    first=at.dispatch(request)
    assert first['successful_legs']==2
    assert len(calls)==3  # Initial layout, then independent readback of each patch.
    assert at._SNAPSHOT_CACHE.get() is None
    second=at.dispatch(request)
    assert first==second and len(calls)==6
    assert at._SNAPSHOT_CACHE.get() is None


def test_cache_identity_not_path_length_or_equality(monkeypatch):
    raw=fixture_raw();calls=[];original=at.read_track_nodes
    def counted(value,**kwargs):
        calls.append(value)
        return original(value,**kwargs)
    monkeypatch.setattr(at,'read_track_nodes',counted)
    token=at._SNAPSHOT_CACHE.set({})
    try:
        a=at.layout(raw)
        assert at.layout(raw) is a and len(calls)==1
        equal_copy=bytes(bytearray(raw))
        assert equal_copy is not raw
        assert at.layout(equal_copy)==a and len(calls)==2
        assert at._SNAPSHOT_CACHE.get()['raw'] is equal_copy
        # Returning to an older snapshot revalidates it, not an unbounded LRU.
        at.layout(raw)
        assert len(calls)==3
        changed=bytearray(raw);changed[0]=0
        with pytest.raises(ValueError):at.layout(bytes(changed))
        assert 'layout' not in at._SNAPSHOT_CACHE.get()
    finally:
        at._SNAPSHOT_CACHE.reset(token)


def test_failed_dispatch_restores_outer_context(monkeypatch):
    outer={'sentinel':True};token=at._SNAPSHOT_CACHE.set(outer)
    def fail(*args):
        assert at._SNAPSHOT_CACHE.get()=={}
        raise RuntimeError('test failure')
    monkeypatch.setattr(at,'_dispatch',fail)
    try:
        with pytest.raises(RuntimeError,match='test failure'):at.dispatch({})
        assert at._SNAPSHOT_CACHE.get() is outer
    finally:
        at._SNAPSHOT_CACHE.reset(token)


def legacy_geometry_reader():
    # Keep an independent byte-by-byte prefilter as a correctness oracle.
    # The rest of the record/geometry validation is identical by construction.
    source=inspect.getsource(sr.read_track_geometry)
    start=source.index('        # Fast pre-filter:')
    end=source.index('        j = e + 4',start)
    legacy='''        if i + 7 >= end:
            break
        if raw[i + 7] != TYPE_TRACK:
            i += 1
            continue
        r = _is_id(raw, i, {TYPE_TRACK})
        if not r or r[1] - i < 7:
            i += 1
            continue
        e = r[1]
        if e + 4 > end:
            break
        if not (
            raw[e] in ((0, 1) if include_planned else (0,))
            and raw[e + 1] in (2, 4, 6)
            and raw[e + 2] <= 31
            and raw[e + 3] in (1, 255)
        ):
            i += 1
            continue

'''
    scope=dict(vars(sr));exec(source[:start]+legacy+source[end:],scope)
    return scope['read_track_geometry']


@pytest.mark.parametrize('seed',range(8))
def test_fast_scan_matches_legacy_with_noise_duplicates_and_truncation(seed):
    rng=random.Random(seed);legacy=legacy_geometry_reader()
    raw=bytearray(rng.randbytes(700)+fixture_raw()+b'\x01'*60+fixture_raw()+rng.randbytes(800))
    for _ in range(20):raw[rng.randrange(len(raw))]=rng.randrange(256)
    raw=bytes(raw)
    for planned in (False,True):
        for begin,end in ((0,len(raw)),(3,len(raw)-17),(700,850),(0,7)):
            actual_nodes={};expected_nodes={}
            args=dict(region_start=begin,region_end=end,include_planned=planned)
            assert sr.read_track_geometry(raw,**args,_node_sink=actual_nodes)==legacy(raw,**args,_node_sink=expected_nodes)
            assert actual_nodes==expected_nodes


def legacy_station_catalog(raw,include_offsets=False):
    from toolkit_coordedit import _read_name
    _,_,end,_=at.layout(raw)
    station_ids,records=at.registry(raw,end,2)
    result=[]
    for ident in station_ids:
        encoded=at.ident_bytes(ident);position=records;found=[]
        while True:
            position=raw.find(encoded,position)
            if position<0:break
            offset=position+len(encoded)+4;position+=len(encoded)
            if offset+17>len(raw) or raw[offset-1]!=1:continue
            x,y=struct.unpack_from('<dd',raw,offset)
            if not all(at.math.isfinite(v) and abs(v)<20_100_000 for v in (x,y)):continue
            name=_read_name(raw,offset+16,min_len=1,max_len=512)
            if not name and raw[offset+16]!=0:continue
            lon,lat=at.mercator_to_lonlat(x,y)
            row={'id':hex(ident),'name':name[0] if name else f'未命名站 {hex(ident)}','lon':lon,'lat':lat}
            if include_offsets:row['coord_off']=offset
            found.append(row)
        if len(found)==1:result.append(found[0])
    return sorted(result,key=lambda s:(s['name'].casefold(),s['id']))


@pytest.mark.parametrize('case',['single','empty-name','ambiguous','truncated','invalid-coord','unregistered'])
def test_single_pass_station_scan_matches_legacy(case):
    raw=fixture_raw();station=(2<<48)+1
    name=b'' if case=='empty-name' else '测试站'.encode('utf-8')
    coords=(float('nan'),0) if case=='invalid-coord' else at.lonlat_to_mercator(-85,49)
    ident=station+65536 if case=='unregistered' else station
    record=at.ident_bytes(ident)+b'\x84\xc0\x02\x01'+struct.pack('<dd',*coords)+at.uvarint(len(name))+name
    if case=='unregistered':raw+=record
    else:raw=raw.replace(at.ident_bytes(station)+bytes(100),record+bytes(100))
    if case=='ambiguous':raw+=record
    if case=='truncated':raw+=record[:20]
    for offsets in (False,True):
        actual=at.station_catalog(raw,include_offsets=offsets)
        assert actual==legacy_station_catalog(raw,offsets)
        assert len(actual)==(0 if case in ('ambiguous','invalid-coord','unregistered') else 1)
