import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import toolkit_cleanup as cleanup
from toolkit_backend import plan_train_count


def make_copy(folder, number=0):
    path = folder / f'Network_Workspace_20260101_00000{number}.nimbyrails5'
    path.write_bytes(b'generated')
    path.with_suffix('.manifest.json').write_text(json.dumps({
        'output_save': str(path), 'output_file_sha256': hashlib.sha256(b'generated').hexdigest()
    }))
    return path


def test_unknown_changed_and_pinned_copies_are_not_cleanup_candidates(tmp_path):
    p = make_copy(tmp_path)
    assert cleanup._recognized_copy(p)
    cleanup.set_copy_protection(tmp_path, p.name, True)
    assert not cleanup._recognized_copy(p)
    cleanup.set_copy_protection(tmp_path, p.name, False)
    assert cleanup._recognized_copy(p)
    p.write_bytes(b'player continued playing')
    assert not cleanup._recognized_copy(p)
    p.with_suffix('.manifest.json').unlink()
    assert not cleanup._recognized_copy(p)


def test_manifest_must_reference_the_same_path(tmp_path):
    p = make_copy(tmp_path)
    manifest = p.with_suffix('.manifest.json')
    data = json.loads(manifest.read_text())
    data['output_save'] = str(tmp_path / 'other.nimbyrails5')
    manifest.write_text(json.dumps(data))
    assert not cleanup._recognized_copy(p)


def test_cleanup_refuses_changed_or_pinned_preview_without_recycling(tmp_path):
    for n in range(3): make_copy(tmp_path, n)
    preview = cleanup.cleanup_preview(tmp_path, keep=1, compact=True)
    target = Path(preview['targets'][0]['path'])
    cleanup.set_copy_protection(tmp_path, target.name, True)
    with patch.object(cleanup, '_recycle_windows') as recycle:
        with pytest.raises(RuntimeError, match='重新预览'):
            cleanup.execute_cleanup(tmp_path, preview)
        recycle.assert_not_called()


def test_protection_rejects_path_escape(tmp_path):
    with pytest.raises(RuntimeError):
        cleanup.set_copy_protection(tmp_path, '../outside.nimbyrails5', True)


def test_cleanup_executes_only_verified_unpinned_excess_copies(tmp_path):
    paths = [make_copy(tmp_path, n) for n in range(4)]
    cleanup.set_copy_protection(tmp_path, paths[0].name, True)
    preview = cleanup.cleanup_preview(tmp_path, keep=1, compact=True)
    assert preview['candidate_count'] == 2
    removed = []
    def fake_recycle(files):
        removed.extend(files)
        for p in files:
            p.unlink()  # Temporary test directory only; never invokes Windows recycle.
    with patch.object(cleanup, '_recycle_windows', side_effect=fake_recycle):
        result = cleanup.execute_cleanup(tmp_path, preview)
    assert result['moved_group_count'] == 2
    assert paths[0].is_file()
    assert all(p.parent == tmp_path for p in removed)


def test_fresh_install_cleanup_is_off_but_existing_choice_is_preserved(tmp_path, monkeypatch):
    import toolkit_webapp as web
    settings = tmp_path/'settings.json'
    monkeypatch.setattr(web, 'SETTINGS_FILE', settings)
    assert web.read_settings()['enabled'] is False
    settings.write_text('{"enabled": true}')
    assert web.read_settings()['enabled'] is True


def test_headway_count_is_a_lower_bound_not_nearest_integer():
    assert plan_train_count(3720, 300) == 13
    for duration in (300, 601, 3720, 10477):
        for target in (30, 90, 300, 600):
            n = plan_train_count(duration, target)
            assert duration / n <= target
    assert plan_train_count(-1, 300) is None


def test_copy_and_metro_assets_are_wired():
    root = Path(__file__).resolve().parents[1]
    html = (root/'web/index.html').read_text('utf-8')
    assert 'value="metro"' in html and 'src="/app.js"' in html
    import toolkit_webapp as web
    assert web.APP_SCRIPT_PARTS == ('metro.js', 'metro-poster.js', 'app.js')
    assert 'href="/usability.css"' in html and 'id="cleanup-protection"' in html
    for misleading in ('零风险', '32/37', '真值护栏', '几秒完成', '仅用存档体检（估算）', '已回滚旧版本'):
        assert misleading not in html
    import re
    ids = set(re.findall(r'id="([^"]+)"', html))
    for target in re.findall(r'href="#([^"]+)"', html):
        assert target in ids
