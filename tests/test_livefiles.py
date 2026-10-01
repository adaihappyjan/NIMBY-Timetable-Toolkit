import os
from toolkit_livefiles import StableFiles
import toolkit_webapp as web


def test_settle_and_same_path_rewrite():
    tracker=StableFiles(3)
    f={'saves':[{'path':'save','size':123,'modified_ns':'1'}],'exports':[]}
    assert not tracker.observe(f,now=0)['saves'][0]['stable']
    assert not tracker.observe(f,now=2)['saves'][0]['stable']
    assert tracker.observe(f,now=3)['saves'][0]['stable']
    f['saves'][0]['modified_ns']='2'
    assert not tracker.observe(f,now=4)['saves'][0]['stable']
    assert tracker.observe(f,now=7)['saves'][0]['stable']
    tracker.observe({'saves':[],'exports':[]},now=8)
    assert not tracker.observe(f,now=9)['saves'][0]['stable']


def test_zero_length_is_never_ready():
    tracker=StableFiles()
    f={'saves':[{'path':'save','size':0,'modified_ns':'1'}]}
    tracker.observe(f,now=0)
    assert not tracker.observe(f,now=99)['saves'][0]['stable']


def test_scan_copies_and_subsecond_changes(tmp_path,monkeypatch):
    monkeypatch.setattr(web,'SAVE_DIR',tmp_path)
    for name in ['City.nimbyrails5','City_Names_20260930_175900.nimbyrails5','City Timetable Export 20280101T000000Z.json','map.json']:
        (tmp_path/name).write_bytes(b'test')
    result=web.recent_files()
    assert len(result['saves'])==2 and len(result['exports'])==1
    assert next(r for r in result['saves'] if '_Names_' in r['name'])['tool_generated']
    assert not next(r for r in result['saves'] if r['name']=='City.nimbyrails5')['tool_generated']
    before=web.file_info(tmp_path/'City.nimbyrails5')['modified_ns']
    os.utime(tmp_path/'City.nimbyrails5',ns=(int(before)+1000,int(before)+1000))
    assert web.file_info(tmp_path/'City.nimbyrails5')['modified_ns']!=before
