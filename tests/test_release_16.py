import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import toolkit_updater as updater
from build_portable import build_portable
from toolkit_workspace import parse_log


def test_actual_game_log_separate_timestamp_and_source_line():
    result = parse_log('#126,062 | 2027年十二月29日 星期三 15:03:28.430000\nL42 NIMBY_DIAG|ASSIGNED|5077\nNIMBY_DIAG|TIMED_STOP|5077')
    assert result['total'] == 2
    assert '15:03:28' in result['records'][0]['timestamp']
    assert result['records'][0]['detail'] == '5077'
    assert result['records'][1]['timestamp'] == ''


def test_release_includes_workspace_tutorial_and_style(tmp_path):
    archive, sums = build_portable('v1.6.0', tmp_path / 'dist')
    data = archive.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest in sums.read_text()
    package, manifest = updater.extract_verified_archive(data, digest, '1.6.0', tmp_path / 'stage')
    for name in ['toolkit_workspace.py', 'toolkit_diagnostics.py', 'web/workspace.js',
                 'web/tutorial.js', 'web/studio.css', 'docs/WORKSPACE_GUIDE.md']:
        assert name in manifest['files']
        assert (package / name).is_file()
    html = (package / 'web/index.html').read_text('utf-8')
    assert 'src="/tutorial.js"' in html
    assert 'href="/studio.css"' in html
    assert 'data-view="learn"' in html


def test_incomplete_rollback_is_reported_and_never_restarted(tmp_path):
    old, _ = build_portable('v1.5.0', tmp_path / 'old')
    new, _ = build_portable('v1.6.0', tmp_path / 'new')
    old_data, new_data = old.read_bytes(), new.read_bytes()
    old_package, _ = updater.extract_verified_archive(old_data, hashlib.sha256(old_data).hexdigest(), '1.5.0', tmp_path / 'old-stage')
    new_package, _ = updater.extract_verified_archive(new_data, hashlib.sha256(new_data).hexdigest(), '1.6.0', tmp_path / 'new-stage')
    target = tmp_path / 'installed'
    shutil.copytree(old_package, target)
    original = updater._replace_from
    calls = 0

    def fail_and_fail_rollback(source, destination):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise PermissionError('locked test file')
        original(source, destination)

    result_file = tmp_path / 'result.json'
    with patch.object(updater, '_replace_from', side_effect=fail_and_fail_rollback), patch.object(updater, '_restart_app') as restart:
        assert not updater.apply_prepared_update(target, new_package, result_file, '1.5.0', '1.6.0', python_executable=sys.executable)
        restart.assert_not_called()
    result = json.loads(result_file.read_text('utf-8'))
    assert not result['rollback_complete']
    assert result['rollback_errors']
    assert '回滚失败' in result['error']
    assert Path(result['backup_dir']).is_dir()
