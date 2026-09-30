import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import toolkit_cleanup as cleanup


def write_json(path, data, age=30):
    path.write_text(json.dumps(data), encoding='utf-8')
    stamp = (datetime.now(timezone.utc)-timedelta(days=age)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def timetable(root, project, index, age=30):
    return write_json(root/f'{project} Timetable Export 2026010{index}T120000Z.json',
                      [{'class': 'Line', 'id': 'line'}, {'class': 'Schedule', 'id': 'schedule'}], age)


def map_json(root, index, line='a', age=30):
    return write_json(root/f'map-{line}-{index}.json',
                      {'schema': 'nimby-toolkit-line-map.v1', 'lines': [{'id': line, 'name': line}], 'stations': {}}, age)


def generated(root, name, age=30):
    path = root/name; path.write_bytes(b'generated')
    write_json(path.with_suffix('.manifest.json'), {'output_save': str(path),
               'output_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    stamp = (datetime.now(timezone.utc)-timedelta(days=age)).timestamp(); os.utime(path, (stamp, stamp))
    return path


def test_exports_are_opt_in_and_keep_latest_per_project_and_map_selection(tmp_path):
    for project in ('A', 'B'):
        timetable(tmp_path, project, 1); timetable(tmp_path, project, 2, age=1)
    for line in ('a', 'b'):
        map_json(tmp_path, 1, line); map_json(tmp_path, 2, line, age=1)
    write_json(tmp_path/'unknown.json', {'anything': 'keep'})
    write_json(tmp_path/'Lookalike Timetable Export 20260101T120000Z.json', {'not': 'game'})
    assert cleanup.cleanup_preview(tmp_path, keep=1, compact=True)['candidate_count'] == 0
    p = cleanup.cleanup_preview(tmp_path, keep=1, include_maps=True, include_timetables=True)
    assert p['candidate_count'] == 4
    assert {t['kind'] for t in p['targets']} == {'timetable-json', 'map-json'}
    assert all('unknown' not in t['name'] and 'Lookalike' not in t['name'] for t in p['targets'])


def test_export_age_pin_current_selection_and_nonrecursive_scope(tmp_path):
    old = timetable(tmp_path, 'A', 1); timetable(tmp_path, 'A', 2, age=0)
    older = map_json(tmp_path, 1, age=30); map_json(tmp_path, 2, age=0)
    older.with_suffix('.keep').touch()
    child = tmp_path/'child'; child.mkdir(); timetable(child, 'B', 1); timetable(child, 'B', 2)
    p = cleanup.cleanup_preview(tmp_path, keep=1, include_maps=True, include_timetables=True, protected_paths=[str(old)])
    assert p['candidate_count'] == 0
    os.utime(old, None)
    assert cleanup.cleanup_preview(tmp_path, keep=1, include_timetables=True)['candidate_count'] == 0


def test_compact_exports_still_preserve_one_per_group(tmp_path):
    timetable(tmp_path, 'A', 1, age=0); timetable(tmp_path, 'A', 2, age=0)
    assert cleanup.cleanup_preview(tmp_path, keep=1, include_timetables=True)['candidate_count'] == 0
    assert cleanup.cleanup_preview(tmp_path, keep=1, include_timetables=True, compact=True)['candidate_count'] == 1


def test_nested_generated_names_share_project_and_other_projects_are_protected(tmp_path):
    a = generated(tmp_path, 'A_Toolkit_20260101_120000.nimbyrails5')
    generated(tmp_path, 'A_Toolkit_20260101_120000_StopTime30s_20260102_120000.nimbyrails5', age=1)
    b = generated(tmp_path, 'B_Workspace_20260101_120000.nimbyrails5', age=50)
    p = cleanup.cleanup_preview(tmp_path, keep=1, compact=True)
    assert [t['path'] for t in p['targets']] == [str(a)]
    assert b.exists()


def test_expanded_partial_names_remain_age_protected(tmp_path):
    stale = tmp_path/'A_StopTime30s_20260101_120000.nimbyrails5.partial'; stale.write_bytes(b'temp')
    fresh = tmp_path/'A_Names_20260101_120000.nimbyrails5.partial'; fresh.write_bytes(b'temp')
    stamp = (datetime.now(timezone.utc)-timedelta(hours=2)).timestamp(); os.utime(stale, (stamp, stamp))
    p = cleanup.cleanup_preview(tmp_path)
    assert [t['path'] for t in p['targets']] == [str(stale)]


def test_cleanup_moves_only_checked_groups_in_trusted_folders(tmp_path, monkeypatch):
    saves = tmp_path/'saves'; saves.mkdir(); maps = tmp_path/'maps'; maps.mkdir()
    old_map = map_json(maps, 1); map_json(maps, 2, age=1)
    old_tt = timetable(saves, 'A', 1); timetable(saves, 'A', 2, age=1)
    p = cleanup.cleanup_preview(saves, keep=1, include_maps=True, include_timetables=True, export_directory=maps)
    removed = []
    def recycle(paths):
        assert all(path.parent in (saves, maps) for path in paths)
        removed.extend(paths)
        for path in paths: path.unlink()  # Disposable test files only.
    monkeypatch.setattr(cleanup, '_recycle_windows', recycle)
    result = cleanup.execute_cleanup(saves, p, export_directory=maps, selected=[str(old_map)])
    assert removed == [old_map] and old_tt.is_file()
    assert result['recoverable'] and result['moved_group_count'] == 1


def test_forged_targets_and_unselected_unknown_files_are_rejected(tmp_path, monkeypatch):
    timetable(tmp_path, 'A', 1); timetable(tmp_path, 'A', 2, age=1)
    unknown = write_json(tmp_path/'personal.json', {'keep': True})
    p = cleanup.cleanup_preview(tmp_path, keep=1, include_timetables=True)
    monkeypatch.setattr(cleanup, '_recycle_windows', lambda paths: pytest.fail('must not recycle'))
    with pytest.raises(RuntimeError, match='候选'):
        cleanup.execute_cleanup(tmp_path, p, selected=[str(unknown)])
    forged = copy.deepcopy(p); forged['targets'][0]['paths'] = [str(unknown)]
    with pytest.raises(RuntimeError, match='不符'):
        cleanup.execute_cleanup(tmp_path, forged)


def test_content_change_with_same_size_and_mtime_invalidates_export_preview(tmp_path, monkeypatch):
    old = timetable(tmp_path, 'A', 1); timetable(tmp_path, 'A', 2, age=1)
    p = cleanup.cleanup_preview(tmp_path, keep=1, include_timetables=True)
    stat = old.stat(); old.write_text(old.read_text().replace('schedule', 'Schedule'))
    os.utime(old, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    monkeypatch.setattr(cleanup, '_recycle_windows', lambda paths: pytest.fail('must not recycle'))
    with pytest.raises(RuntimeError, match='重新预览'): cleanup.execute_cleanup(tmp_path, p)


def test_current_selection_and_untrusted_export_directory_invalidate_preview(tmp_path, monkeypatch):
    maps = tmp_path/'maps'; maps.mkdir(); map_json(maps, 1); map_json(maps, 2, age=1)
    p = cleanup.cleanup_preview(tmp_path, keep=1, include_maps=True, export_directory=maps)
    monkeypatch.setattr(cleanup, '_recycle_windows', lambda paths: pytest.fail('must not recycle'))
    with pytest.raises(RuntimeError, match='重新预览'): cleanup.execute_cleanup(tmp_path, p)


def test_manual_api_checks_active_worker_and_current_selection(tmp_path, monkeypatch):
    import toolkit_webapp as web
    from types import SimpleNamespace
    monkeypatch.setattr(web, 'SAVE_DIR', tmp_path)
    monkeypatch.setattr(web, 'map_export_directory', lambda: tmp_path)
    monkeypatch.setattr(web, 'TASKS', web.TaskManager())
    old = timetable(tmp_path, 'A', 1); timetable(tmp_path, 'A', 2, age=1)
    options = {'keep': 1, 'include_timetables': True}
    p = web.manual_cleanup_preview(options)
    assert p['candidate_count'] == 1
    assert web.manual_cleanup_preview({**options, 'protected_paths': [str(old)]})['candidate_count'] == 0
    web.TASKS.task = {'process': SimpleNamespace(poll=lambda: None)}
    with pytest.raises(RuntimeError, match='后台任务'):
        web.manual_cleanup_execute({**options, 'token': p['token'], 'selected': [str(old)]})


def test_symlink_exports_are_not_candidates(tmp_path):
    actual = map_json(tmp_path, 1)
    try: (tmp_path/'alias.json').symlink_to(actual)
    except OSError: pytest.skip('symlinks not available')
    assert cleanup.cleanup_preview(tmp_path, keep=1, include_maps=True, compact=True)['candidate_count'] == 0
