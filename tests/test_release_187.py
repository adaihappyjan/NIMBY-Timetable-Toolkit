import importlib.util
from pathlib import Path

import pytest

import toolkit_updater as updater
import toolkit_webapp as web

ROOT = Path(__file__).resolve().parents[1]


def test_stable_package_includes_theme_but_not_experiments():
    spec = importlib.util.spec_from_file_location('release187_builder', ROOT / 'scripts/build_portable.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    names = {p.relative_to(ROOT).as_posix() for p in builder.portable_files()}
    assert 'web/theme.css' in names
    assert 'docs/RELEASE_1.8.7.txt' in names
    assert not any(name.startswith(('experiments/', '.claude/', '_research/', '_backups/')) for name in names)
    assert not any('nimby3d' in name.lower() or 'terrain_observer' in name.lower() for name in names)


def test_theme_is_last_and_content_versioned():
    html = (ROOT / 'web/index.html').read_text('utf-8')
    assert html.index('/usability.css') < html.index('/theme.css') < html.index('</head>')
    assert '/theme.css?v=' in web.version_static_html(html)
    assert '2.0.0 beta 3D 版本即将释出' in html
    assert '当前稳定版' in html and '不会下载安装任何 3D 内容' in html
    assert '/experiments/' not in html and '/nimby3d' not in html


def test_announcement_is_not_a_stable_update():
    # Even a higher advertised version must not enter the stable update channel.
    with pytest.raises(RuntimeError):
        updater.parse_release_metadata({'tag_name': 'v2.0.0-beta.1', 'prerelease': True})


def test_release_notes_explain_scope_and_upgrade():
    notes = (ROOT / 'docs/RELEASE_1.8.7.txt').read_text('utf-8')
    for text in ('1.8.7', '2.0.0 beta', '不包含或启用 3D', 'Python', 'Node.js', 'SHA-256', '新副本'):
        assert text in notes
