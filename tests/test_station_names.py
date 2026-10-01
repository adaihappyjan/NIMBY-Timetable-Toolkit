import json
import pytest
import toolkit_coordedit as ce
import toolkit_autotrack as at
from test_toolkit_autotrack import fixture_raw
from test_toolkit_coordedit import _station_bytes_noname, _make_save

SID=hex((2<<48)+1)

def save(tmp_path):
    raw=fixture_raw(); _,_,end,_=at.layout(raw)
    raw=raw[:end]+at.uvarint(1)+at.ident_bytes(int(SID,16))+at.uvarint(1)+_station_bytes_noname(int(SID,16),-81.7,47.6)
    return _make_save(tmp_path,raw)

def test_json_order_whitespace_unicode_conflicts(tmp_path):
    p=tmp_path/'export.json'
    p.write_text(json.dumps([{'name':'高山','id':SID,'class':'Station'},{'class':'Station','id':'0x2000000010001','name':'未命名站'},{'class':'Station','id':'0x2000000020001','name':'A'},{'class':'Station','id':'0x2000000020001','name':'B'}],ensure_ascii=False,indent=2),encoding='utf-8-sig')
    assert ce.station_names_from_export(p)=={SID:'高山'}
    p.write_text('[{"class":"Station"',encoding='utf-8')
    with pytest.raises(ValueError,match='未完整'):ce.station_names_from_export(p)

def test_id_and_position_must_match(tmp_path):
    p=tmp_path/'export.json'; records=ce.verified_name_stations(at.Zstd().decompress(at.split_save(save(tmp_path))[1]))
    for coords,expected in [([-81.7,47.6],{SID:'Gogama'}),([0,0],{})]:
        p.write_text(json.dumps([{'class':'Station','id':SID,'name':'Gogama','lonlat':coords}]))
        assert ce.station_names_from_export(p,records)==expected

def test_preview_write_and_single_character_readback(tmp_path):
    source=save(tmp_path); before=source.read_bytes();out=tmp_path/'named.nimbyrails5'
    preview=ce.set_station_names(source,out,{SID:'岚'},preview=True)
    assert preview['changed_count']==1 and preview['unresolved_count']==0 and not out.exists()
    result=ce.set_station_names(source,out,{SID:'岚'},expected_fingerprint=preview['fingerprint'])
    assert result['reverse_decompress_verified'] and source.read_bytes()==before
    assert ce.verified_name_stations(at.Zstd().decompress(at.split_save(out)[1]))[0].name=='岚'
    noop=ce.set_station_names(out,tmp_path/'noop.nimbyrails5',{SID:'Other'},preview=True)
    assert noop['changed_count']==0 and noop['skipped_count']==1

def test_missing_names_reported_and_no_empty_copy(tmp_path):
    source=save(tmp_path);out=tmp_path/'empty.nimbyrails5'
    report=ce.set_station_names(source,out,{},preview=True)
    assert report['unresolved'][0]['id']==SID and report['no_changes'] and not out.exists()
    ce.set_station_names(source,out,{})
    assert not out.exists()

def test_stale_preview_and_placeholder_rejected(tmp_path):
    source=save(tmp_path);out=tmp_path/'out.nimbyrails5'
    preview=ce.set_station_names(source,out,{SID:'Gogama'},preview=True)
    with pytest.raises(RuntimeError,match='已变化'):ce.set_station_names(source,out,{SID:'Changed'},expected_fingerprint=preview['fingerprint'])
    with pytest.raises(RuntimeError,match='占位编号'):ce.set_station_names(source,out,{SID:SID})
    assert not out.exists()


def test_name_backend_preview_and_write_contract(tmp_path,monkeypatch):
    import toolkit_webapp as web
    monkeypatch.setattr(web,'SAVE_DIR',tmp_path)
    source=save(tmp_path)
    payload={'save':str(source),'output':str(tmp_path/'output.nimbyrails5'),'pairs':[SID+'=Gogama'],'preview':True}
    args=web.TaskManager()._build_args('station-name-write',payload)
    assert '--preview' in args and '--pair' in args
    payload['preview']=False
    with pytest.raises(RuntimeError,match='先预览'):web.TaskManager()._build_args('station-name-write',payload)
    payload['fingerprint']='f'*64
    assert '--fingerprint' in web.TaskManager()._build_args('station-name-write',payload)


def test_unknown_manual_id_is_not_silently_ignored(tmp_path):
    with pytest.raises(RuntimeError,match='核对手动填写'):
        ce.set_station_names(save(tmp_path),tmp_path/'out.nimbyrails5',{'0x2000000990001':'Typo'},preview=True)
