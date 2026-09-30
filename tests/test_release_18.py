import json
from pathlib import Path

import pytest
import toolkit_autotrack as at
import toolkit_webapp as app
from test_toolkit_autotrack import fixture_raw


def station_table(free_slots=(), count=3, objects=None):
    values=[]; live=[]
    for slot in range(count):
        if slot in free_slots:
            signed=((0xffff << 48) | (slot << 16) | 1)-(1 << 64)
            values.append(at.uvarint((-signed)*2-1))
        else:
            ident=(2 << 48) | (slot << 16) | 1
            values.append(at.ident_bytes(ident)); live.append(ident)
    return at.uvarint(count)+b''.join(values)+at.uvarint(len(live) if objects is None else objects)+b''.join(at.ident_bytes(i)+bytes(100) for i in live)


@pytest.mark.parametrize('free', [(1,), (0,), (0,1), (2,)])
def test_station_free_slots_have_unique_boundary_and_preserved_suffix(free):
    raw=fixture_raw(); _,_,end,_=at.layout(raw)
    raw=raw[:end]+station_table(free)+raw[end+110:]
    ids,start,actual,nodes=at.layout(raw)
    assert actual==end
    live,records=at.registry(raw,end,2)
    assert len(live)==3-len(free)
    prepared=at.prepare(raw,{'preset':'vandry-dessane'})
    after=at.patch(raw,prepared)
    _,_,new_end,_=at.layout(after)
    assert after[new_end:]==raw[end:]


def test_station_free_slot_count_and_unknown_markers_fail_closed():
    with pytest.raises(ValueError,match='数量'):
        at.registry(station_table((1,),objects=3),0,2)
    with pytest.raises(ValueError):
        at.registry(at.uvarint(1)+at.uvarint(3)+at.uvarint(0),0,2)
    with pytest.raises(ValueError):
        at.registry(station_table((0,1,2)),0,2)
    # Sparse Track allocation is intentionally NOT enabled.
    with pytest.raises(ValueError):
        at.registry(station_table((0,)),0,1)


def test_invalid_and_ambiguous_boundaries_remain_blocked():
    raw=fixture_raw(); _,_,end,_=at.layout(raw)
    with pytest.raises(ValueError,match='未找到'):
        at.layout(raw[:end]+bytes(200))
    with pytest.raises(ValueError,match='多个'):
        at.layout(raw[:end]+station_table()+station_table())


@pytest.fixture
def export_config(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'SETTINGS_DIR',tmp_path/'config')
    monkeypatch.setattr(app,'SETTINGS_FILE',tmp_path/'config/settings.json')
    monkeypatch.setattr(app,'EXPORT_DIR',tmp_path/'default')
    return tmp_path


def test_map_exports_use_persistent_folder_and_never_overwrite(export_config):
    folder=export_config/'中文 导出'
    app.write_settings({'map_export_dir':str(folder),'auto_check_updates':False})
    app.write_settings({'keep':7})
    assert app.map_export_directory()==folder
    data={'schema':'nimby-toolkit-line-map.v1','lines':[{'name':'测试线'}],'stations':{}}
    request={'format':'json','filename':'测试.json','data':data}
    first=app.save_map_export(request); second=app.save_map_export(request)
    assert first!=second and first.parent==folder
    assert json.loads(first.read_text('utf-8'))==data
    assert app.save_map_export({'format':'svg','svg':'<svg/>','filename':'测试.svg'}).parent==folder
    app.write_settings({'map_export_dir':''})
    assert app.map_export_directory()==export_config/'default'
    assert first.is_file()  # Changing/resetting the folder never moves/deletes exports.


def test_map_export_rejects_bad_data_and_paths(export_config):
    for value in ['relative',str(Path(export_config.anchor))]:
        with pytest.raises(RuntimeError):app.write_settings({'map_export_dir':value})
    file=export_config/'file';file.write_text('keep')
    with pytest.raises(RuntimeError):app.write_settings({'map_export_dir':str(file)})
    with pytest.raises(RuntimeError):app.save_map_export({'format':'exe','svg':'x'})
    with pytest.raises(RuntimeError):app.save_map_export({'format':'json','data':[]})
    data={'schema':'nimby-toolkit-line-map.v1','lines':[],'stations':{},'nan':float('nan')}
    with pytest.raises(ValueError):app.save_map_export({'format':'json','data':data})
    path=app.save_map_export({'format':'svg','filename':'../../CON.svg','svg':'<svg/>'})
    assert path.parent==app.map_export_directory() and path.suffix=='.svg'
