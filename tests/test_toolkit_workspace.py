import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import toolkit_workspace as ws
import toolkit_webapp as web
from toolkit_diagnostics import SOURCE, install_diagnostic
from toolkit_scriptgen import validate_script_source
from test_toolkit_scheduleconfig import _raw, DAILY, AIRPORT, DEPOT
import toolkit_scheduleconfig as sc


def objects(runs):
    return [{'class': 'Line', 'id': 'L', 'stops': [{'station_id': 'A'}, {'station_id': 'A'}]},
            {'class': 'Line', 'id': 'D', 'stops': [{'station_id': 'A'}]},
            {'class': 'Schedule', 'id': 'S', 'name': 'Daily', 'trains': {'T': ['shift']},
             'shifts': [{'id': 'shift', 'runs': runs}]}]


def run(start, end, line='L'):
    return {'line_id': line, 'arrival_departure': [start, end], 'enter_stop_idx': 0, 'exit_stop_idx': 0}


def test_project_persists_without_path_traversal(tmp_path):
    ws.project_state(tmp_path, '../../outside', {'draft': {'id': 42}})
    assert ws.project_state(tmp_path, '../../outside')['draft']['id'] == 42
    assert len(list((tmp_path/'projects').glob('*.json'))) == 1
    ws.project_state(tmp_path, '../../outside', {'undo': [1]})
    assert ws.project_state(tmp_path, '../../outside')['draft']['id'] == 42


def test_fingerprint_content_not_filename(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'
    a.write_text('same'); b.write_text('same')
    assert ws.fingerprint(a) == ws.fingerprint(b)
    b.write_text('changed')
    assert ws.fingerprint(a) != ws.fingerprint(b)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,0.25,172801])
def test_reject_invalid_times(value):
    with pytest.raises(ValueError): ws.finite(value)


def test_preset_existing_ids_preserved():
    raw=_raw(); group=sc.group_to_dict(sc.get_operating_group(raw,DAILY))
    changes=ws.preset_updates(group,{'days_mask':31,'depot_ids':[DEPOT],'depot_time':1800,'service_start':21600},[{'id':DEPOT,'stop_count':1},{'id':AIRPORT,'stop_count':2}])
    after,before,parsed,_=sc.set_operating_group(raw,DAILY,**changes)
    assert [e.order_id for e in parsed.entries] == [e.order_id for e in before.entries]
    assert all(e.days_mask==31 for e in parsed.entries)
    assert parsed.entries[0].repeat_count==1
    assert after != raw


def test_shared_offset_is_not_silently_changed():
    group=sc.group_to_dict(sc.get_operating_group(_raw(),DAILY))
    with pytest.raises(ValueError,match='共用偏移组'):
        ws.preset_updates(group,{'depot_ids':[DEPOT],'interval':420},[{'id':DEPOT,'stop_count':1},{'id':AIRPORT,'stop_count':2}])


def test_period_preset_keeps_depot_and_original_ids():
    group=sc.group_to_dict(sc.get_operating_group(_raw(),DAILY))
    updates=ws.period_preset(group,{'depot_ids':[DEPOT],'periods':[{'start':19800,'interval':900},{'start':25200,'interval':420}]},[{'id':DEPOT,'stop_count':1},{'id':AIRPORT,'stop_count':2}])
    plan=updates['entry_plan']
    assert {e['order_id'] for e in plan if e['order_id']}=={e['order_id'] for e in group['entries']}
    assert len(plan)==3
    assert len(updates['distribution_updates'])==2
    assert 0 not in updates['distribution_updates']  # depot keeps its group


def test_period_preset_rejects_duplicate_boundaries():
    group=sc.group_to_dict(sc.get_operating_group(_raw(),DAILY))
    with pytest.raises(ValueError,match='递增'):
        ws.period_preset(group,{'depot_ids':[DEPOT],'periods':[{'start':25200,'interval':420},{'start':25200,'interval':900}]},[{'id':DEPOT,'stop_count':1},{'id':AIRPORT,'stop_count':2}])


def test_batch_requires_matching_fingerprint(tmp_path):
    with patch.object(ws,'catalog',return_value={'fingerprint':'current'}):
        with pytest.raises(ValueError,match='指纹'):
            ws.batch(tmp_path/'save',{'fingerprint':'old'})


def test_sunday_monday_overlap_detected():
    report=ws.continuity(objects([run(100,200),run(604700,605000)]))
    assert any(i['problem']=='班次重叠' and i['seconds']==100 for i in report['issues'])


def test_unknown_position_not_reported_as_pass():
    data=objects([run(100,200),run(300,400)])
    data[0]['stops'][0]['station_id']=None
    assert all(i['status']=='unknown' for i in ws.continuity(data)['issues'])


def test_depot_week_wrap_and_capacity():
    data=objects([run(100,200),run(600000,600010,'D')])
    data[2]['trains']['T2']=['shift']
    depot=ws.continuity(data,{'D':1})['depots'][0]
    assert depot['planned_peak']==2 and depot['over_capacity']
    assert any(i[0]==0 for i in depot['intervals'])


def test_depot_departure_before_same_time_arrival():
    data=objects([run(100,200,'D'),run(200,300)])
    assert ws.continuity(data,{'D':1})['depots'][0]['planned_peak']==1


def branches():
    return [{'id':'A','stations':['S1','S2'],'entry_travel':120}, {'id':'B','stations':['S1','S2'],'entry_travel':240}]


def test_rem_corridor_phase_and_origin_offset():
    report=ws.corridor(branches(),[{'start':25200,'end':27000,'intervals':{'A':420,'B':840},'phases':{'B':210}}])
    assert [e['gap'] for e in report['events'][1:7]]==[210,210,420,210,210,420]
    assert report['events'][1]['origin_departure']==25200+210-240


def test_reverse_direction_and_same_name_different_id_rejected():
    data=branches();data[1]['stations']=['S2','S1']
    with pytest.raises(ValueError,match='同方向'):ws.corridor(data,[{}])
    data[1]['stations']=['X1','X2']
    with pytest.raises(ValueError):ws.corridor(data,[{}])


def test_repeated_corridor_occurrence_is_ambiguous():
    data=branches();data[0]['stations']=['S1','S2','X','S1','S2']
    with pytest.raises(ValueError,match='重复出现'):ws.corridor(data,[{}])


def test_corridor_transition_boundary_and_midnight():
    windows=[{'start':85800,'end':0,'intervals':{'A':300,'B':300},'phases':{'B':150}},
             {'start':86400,'end':87000,'intervals':{'A':300,'B':300},'phases':{'B':150}}]
    report=ws.corridor(branches(),windows)
    assert len(report['events'])==8
    assert [e['entry_time'] for e in report['events']].count(86400)==1


def test_accounting_grain_period_null_and_ratio(tmp_path):
    p=tmp_path/'account.tsv'
    p.write_text('id\tkind\tname\tperiod\ttimestamp\ttrains_signal_stop_time\ttrain_departed_full\ttrains_departures\n'
                 'A\tline\tA\tdaily\t2027-12-01\t10\t4\t10\n'
                 'B\tline\tB\tdaily\t2027-12-01\t\t\t0\n'
                 'A\tline\tA\tlifetime\t2027-12-01\t100\t9\t10\n',encoding='utf-8')
    result=ws.accounting(p)
    assert [x['value'] for x in result['rankings']]==[10,None]
    assert ws.accounting(p,metric='full_departure_ratio')['rankings'][0]['value']==.4


def test_duplicate_accounting_rejected(tmp_path):
    p=tmp_path/'a.tsv';p.write_text('id\tkind\tperiod\ttimestamp\nA\tline\tdaily\t1\nA\tline\tdaily\t1\n')
    with pytest.raises(ValueError,match='重复'):ws.accounting(p)


def test_log_is_bounded_and_html_is_data():
    report=ws.parse_log('\n'.join('NIMBY_DIAG|SIGNAL_WAIT|<script>' for _ in range(2005)))
    assert report['total']==2005 and len(report['records'])==2000
    assert report['counts']['SIGNAL_WAIT']==2005


def test_diagnostic_no_dispatch_commands_and_idempotent_install(tmp_path):
    assert validate_script_source(SOURCE)['valid']
    assert 'queue_train_' not in SOURCE and 'match_pos' not in SOURCE
    installed=install_diagnostic(tmp_path)
    assert Path(installed['path']).is_dir()
    assert install_diagnostic(tmp_path)['already_installed']
    (Path(installed['path'])/'mod.txt').write_text('user changes')
    with pytest.raises(ValueError,match='不自动覆盖'):install_diagnostic(tmp_path)


def test_workspace_paths_cannot_escape_save_folder(tmp_path,monkeypatch):
    monkeypatch.setattr(web,'SAVE_DIR',tmp_path)
    with pytest.raises(RuntimeError):web.TaskManager()._build_args('workspace',{'operation':'catalog','save':'C:/outside.nimbyrails5'})
    with pytest.raises(RuntimeError):web.TaskManager()._build_args('workspace',{'operation':'accounting','accounting':'C:/outside.tsv'})


def test_cache_key_uses_content(tmp_path):
    save=tmp_path/'save';save.write_bytes(b'save')
    data={'save':str(save),'fingerprint':ws.fingerprint(save),'groups':[]}
    with patch.object(ws,'catalog',return_value=data) as read:
        req={'operation':'catalog','save':str(save),'_cache_dir':str(tmp_path/'cache')}
        assert not ws.dispatch(req)['cache_hit']
        assert ws.dispatch(req)['cache_hit']
        assert read.call_count==1


def test_no_depot_records_are_unknown_not_zero():
    report=ws.continuity(objects([run(100,200)]),{'D':8})
    assert report['depots'][0]['planned_peak'] is None
    assert report['without_depot']==['T']


def test_frontend_has_no_malformed_closing_tags():
    import re
    text=(Path(__file__).resolve().parents[1]/'web'/'workspace.js').read_text('utf-8')
    assert not re.search(r'</\w+\s+\w+=',text)


def test_generated_mod_install_requires_receipt_and_no_overwrite(tmp_path):
    from toolkit_diagnostics import record_generated_archive,install_generated_archive
    from toolkit_scriptgen import build_mod_zip
    package=tmp_path/'rules.zip';package.write_bytes(build_mod_zip({'id':'test_ops','garage_join':True})[0])
    savedir=tmp_path/'saves';savedir.mkdir()
    with pytest.raises(ValueError,match='原始模组包'):install_generated_archive(package,savedir)
    record_generated_archive(package)
    result=install_generated_archive(package,savedir)
    assert (Path(result['path'])/'mod.txt').is_file()
    with pytest.raises(ValueError,match='已经存在'):install_generated_archive(package,savedir)


def test_zip_traversal_rejected_even_with_receipt(tmp_path):
    import zipfile
    from toolkit_diagnostics import record_generated_archive,install_generated_archive
    package=tmp_path/'evil.zip'
    with zipfile.ZipFile(package,'w') as z:
        z.writestr('root/mod.txt','test');z.writestr('root/../../outside','bad')
    record_generated_archive(package)
    with pytest.raises(ValueError,match='不安全路径'):install_generated_archive(package,tmp_path)
    assert not (tmp_path/'outside').exists()


def test_real_save_multi_table_roundtrip(tmp_path):
    import os
    name=os.environ.get('NIMBY_TEST_SAVE')
    if not name:
        pytest.skip('Set NIMBY_TEST_SAVE for opt-in read-only source integration')
    from toolkit_binary import split_save, Zstd
    source=Path(name)
    mark=ws.fingerprint(source)
    copied=tmp_path/'input.nimbyrails5';copied.write_bytes(source.read_bytes())
    current=ws.catalog(copied)
    selected=[g['schedule_id'] for g in current['groups'] if g['kind']=='timetable' and g['schedule_name'] in ('OT Line 1 Daily','OT Line 4 Daily')]
    assert len(selected)==2
    request={'fingerprint':mark,'selected':selected,'preset':{'days_mask':31}}
    preview=ws.dispatch({'operation':'batch','save':str(copied),**request})
    assert not list(tmp_path.glob('*.manifest.json'))
    output=tmp_path/'output.nimbyrails5'
    result=ws.batch(copied,{**request,'apply':True,'preview_hash':preview['preview_hash'],'output':str(output)})
    assert result['compressed_readback_verified']
    assert ws.fingerprint(source)==mark==ws.fingerprint(copied)
    old={g.schedule_id:sc.group_to_dict(g) for g in sc.read_operating_groups(Zstd().decompress(split_save(copied)[1]))}
    new={g.schedule_id:sc.group_to_dict(g) for g in sc.read_operating_groups(Zstd().decompress(split_save(output)[1]))}
    assert old.keys()==new.keys()
    assert all(old[k]==new[k] for k in old if k not in selected)
    assert all(e['days_mask']==31 for k in selected for e in new[k]['entries'])
    with pytest.raises(ValueError,match='预览'):
        ws.batch(copied,{**request,'apply':True,'preview_hash':'wrong','output':str(tmp_path/'wrong.nimbyrails5')})
