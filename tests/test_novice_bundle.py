import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import build_novice as novice
import toolkit_start as start
import toolkit_updater as updater
from build_portable import build_portable


@pytest.mark.parametrize('name', ['/absolute', '../escape', 'a/../b', 'a\\b', 'C:/drive', 'a//b', './a'])
def test_runtime_rejects_unsafe_archive_names(name):
    with pytest.raises(ValueError):
        novice.safe_name(name)


def test_runtime_manifest_is_complete_and_reproducible():
    entries = {'python/pythonw.exe': b'python', 'node.exe': b'node', 'licenses/test.txt': b'license'}
    data = novice.make_runtime(entries)
    assert data == novice.make_runtime(dict(reversed(list(entries.items()))))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read('runtime-manifest.json'))
        assert manifest == {name: hashlib.sha256(value).hexdigest() for name, value in entries.items()}
        for name, value in entries.items():
            assert archive.read(name) == value


def test_download_rejects_corrupt_cached_file_without_network(tmp_path):
    cached = tmp_path / 'runtime.zip'
    cached.write_bytes(b'wrong')
    with patch.object(novice, 'urlopen') as fetch:
        with pytest.raises(RuntimeError, match='缓存校验失败'):
            novice.download({'url': 'https://example.invalid/runtime.zip', 'sha256': '0' * 64}, tmp_path)
        fetch.assert_not_called()
    assert cached.read_bytes() == b'wrong'


def test_only_explicit_novice_extras_are_allowed(tmp_path):
    with pytest.raises(ValueError, match='只允许'):
        build_portable('v1.6.0', tmp_path, extras={'arbitrary.exe': b'no'})


def test_source_to_novice_update_preserves_user_file_and_restarts_via_exe(tmp_path):
    archive, _ = build_portable('v1.6.1', tmp_path / 'out', extras={
        'NIMBYToolkit.exe': b'launcher fixture', '故障诊断.exe': b'diagnostic fixture',
        'runtime/runtime.zip': b'runtime fixture'})
    data = archive.read_bytes()
    package, manifest = updater.extract_verified_archive(data, hashlib.sha256(data).hexdigest(), '1.6.1', tmp_path / 'stage')
    assert 'toolkit_start.py' in manifest['files']
    assert '先看这里.txt' in manifest['files']
    target = tmp_path / 'installed'
    old_archive, _ = build_portable('v1.6.0', tmp_path / 'old')
    old_data = old_archive.read_bytes()
    old_package, _ = updater.extract_verified_archive(old_data, hashlib.sha256(old_data).hexdigest(), '1.6.0', tmp_path / 'old-stage')
    shutil.copytree(old_package, target)
    (target / 'my-save.nimbyrails5').write_bytes(b'untouched')
    with patch.object(updater, '_restart_app') as restart:
        assert updater.apply_prepared_update(target, package, tmp_path / 'result.json', '1.6.0', '1.6.1', python_executable=sys.executable)
        restart.assert_called_once()
    assert (target / 'my-save.nimbyrails5').read_bytes() == b'untouched'
    with patch.object(updater.subprocess, 'Popen') as launch:
        updater._restart_app(sys.executable, target)
        assert launch.call_args.args[0] == [str(target / 'NIMBYToolkit.exe')]


def test_diagnostic_txt_is_readable_and_does_not_claim_gui_validation():
    result = {'ok': False, 'app': '应用', 'python_executable': '内置运行库', 'python': '3.13',
              'checks': [{'ok': False, 'name': '桌面组件', 'detail': '未找到'}]}
    report = start.readable_report(result)
    assert '失败：桌面组件' in report
    assert '不会修改游戏存档' in report
    assert '不代表所有游戏功能已经验收' in report
