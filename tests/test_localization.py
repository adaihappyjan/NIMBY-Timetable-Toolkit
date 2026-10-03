import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
from urllib.request import Request, urlopen

import pytest
import toolkit_locale as locale
import toolkit_webapp as web

ROOT = Path(__file__).resolve().parents[1]


def test_language_switch_state():
    if not shutil.which('node'): pytest.skip('Node required')
    result = subprocess.run(['node','--test',str(ROOT/'tests/locale_state.test.cjs')],capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_assets_are_current_and_valid_javascript():
    folder = ROOT / 'web/locales/en'
    sources = json.loads((folder / 'sources.json').read_text('utf-8'))
    for name, expected in sources.items():
        assert hashlib.sha256((ROOT/'web'/name).read_text('utf-8').encode()).hexdigest() == expected, name
        assert (folder/name).is_file()
        if name.endswith('.js') and shutil.which('node'):
            result = subprocess.run(['node', '--check', str(folder/name)], capture_output=True)
            assert result.returncode == 0, result.stderr
    assert '<html lang="en">' in (folder/'index.html').read_text('utf-8')


def test_catalog_has_reviewed_terminology():
    catalog = json.loads((ROOT/'web/locales/en.json').read_text('utf-8'))
    reviewed = json.loads((ROOT/'web/locales/en.overrides.json').read_text('utf-8'))
    assert catalog == reviewed
    assert catalog['单轨'] == 'Monorail'
    assert catalog['简体中文'] == '简体中文'
    assert all('▁' not in value and value.strip() for value in catalog.values())


def test_backend_message_catalog_is_complete():
    import ast, re
    messages = locale.messages()
    for path in ROOT.glob('toolkit_*.py'):
        if path.name == 'toolkit_locale.py': continue
        for node in ast.walk(ast.parse(path.read_text('utf-8-sig'))):
            if isinstance(node, ast.Constant) and isinstance(node.value,str) and re.search(r'[\u3400-\u9fff]',node.value):
                assert node.value in messages, (path.name,node.value)


def test_display_translation_preserves_player_data_and_template_captures():
    data = {'error':'所选站点不在当前存档，请重新自动读取',
            'name':'所选站点不在当前存档，请重新自动读取',
            'station_name':'中央车站', 'path':'D:/铁路/最新存档.nimbyrails5',
            'nested':{'notes':['新存档已安全写入'], 'code':'车库'}}
    english = locale.localize_payload(data)
    assert english['error'] == 'Selected station is not in the current save; reload automatically'
    for key in ('name','station_name','path'): assert english[key] == data[key]
    assert english['nested']['code'] == '车库'
    assert english['nested']['notes'] == ['New save written safely']
    assert locale.localize_payload(data, 'zh-CN') is data
    assert locale.translate_message('玩家自定义提示：中央车站') == '玩家自定义提示：中央车站'
    # Every generated f-string template preserves arbitrary captured player text.
    for source, target in locale.messages().items():
        if '{{0}}' not in source: continue
        import re
        value = re.sub(r'\{\{\d+\}\}', '玩家线路/Line 甲', source)
        result = locale.translate_message(value)
        assert result.count('玩家线路/Line 甲') == value.count('玩家线路/Line 甲')


def test_default_and_saved_language(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'SETTINGS_DIR', tmp_path)
    monkeypatch.setattr(web, 'SETTINGS_FILE', tmp_path/'settings.json')
    assert web.read_settings()['language'] == 'en'
    web.write_settings({'language':'zh-CN'})
    assert web.read_settings()['language'] == 'zh-CN'
    web.write_settings({'language':'unknown'})
    assert web.read_settings()['language'] == 'en'


def test_http_languages_and_api_header(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'SETTINGS_DIR', tmp_path)
    monkeypatch.setattr(web, 'SETTINGS_FILE', tmp_path/'settings.json')
    server = web.make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        html = urlopen(base+'/').read().decode('utf-8')
        assert '<html lang="en">' in html and '&lang=en' in html
        assert 'English' in html and '简体中文' in html
        chinese = urlopen(base+'/?lang=zh-CN').read().decode('utf-8')
        assert '<html lang="zh-CN">' in chinese and '&lang=zh-CN' in chinese
        assert '铁路运营总览' in chinese
        script = urlopen(base+'/app.js?lang=en').read().decode('utf-8')
        assert script.index('function metroTopology(') < script.index('const APP_BUILD')
        request = Request(base+'/api/settings', data=b'{"language":"zh-CN"}', headers={'Content-Type':'application/json','X-NIMBY-Language':'en'})
        assert json.loads(urlopen(request).read())['ok']
        assert '<html lang="zh-CN">' in urlopen(base+'/').read().decode('utf-8')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_stale_english_source_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'WEB_ROOT', tmp_path)
    (tmp_path/'app.js').write_text('// changed', encoding='utf-8')
    translated = tmp_path/'locales/en'
    translated.mkdir(parents=True)
    (translated/'app.js').write_text('// stale', encoding='utf-8')
    (translated/'sources.json').write_text('{"app.js":"wrong"}', encoding='utf-8')
    with pytest.raises(OSError, match='out of date'): web.static_bytes('app.js','en')


def test_bilingual_files_are_packaged_without_3d():
    import sys
    sys.path.insert(0, str(ROOT/'scripts'))
    from build_portable import portable_files
    files = {p.relative_to(ROOT).as_posix() for p in portable_files()}
    for name in ('README.md','README.zh-CN.md','START HERE.txt','toolkit_locale.py',
                 'web/locale.js','web/locales/en/app.js','web/locales/messages.en.json',
                 'docs/USER_GUIDE.md','docs/RELEASE_1.9.0.txt'):
        assert name in files
    assert not any(p.startswith(('experiments/','.claude/','dist/')) for p in files)
