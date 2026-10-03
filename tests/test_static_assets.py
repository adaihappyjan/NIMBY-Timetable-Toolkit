import json
import re
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

import toolkit_webapp as web


@pytest.fixture
def assets_server():
    # Real production handler, without desktop startup, cleanup, or API calls.
    server = web.make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_actual_http_entrypoint_contains_dependencies_in_order(assets_server):
    html = urlopen(assets_server + "/").read().decode("utf-8")
    assert 'src="/metro.js' not in html
    assert 'src="/metro-poster.js' not in html
    paths = re.findall(r'(?:src|href)="(/[^"?]+\.(?:js|css)\?v=[a-f0-9]+(?:&lang=[\w-]+)?)"', html)
    assert len(paths) >= 7
    entry = next(p for p in paths if p.startswith('/app.js?'))
    with urlopen(assets_server + entry) as response:
        script = response.read().decode('utf-8')
        assert 'javascript' in response.headers['Content-Type']
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert 'no-store' in response.headers['Cache-Control']
    assert script.index('function metroTopology(') < script.index('function drawMetroDiagram(') < script.index('const APP_BUILD')


def test_missing_script_is_404_not_html(assets_server):
    with pytest.raises(HTTPError) as result:
        urlopen(assets_server + '/missing-map-module.js')
    assert result.value.code == 404


def test_incomplete_bundle_fails_explicitly(assets_server, tmp_path, monkeypatch):
    (tmp_path/'app.js').write_text('// UI', encoding='utf-8')
    monkeypatch.setattr(web, 'WEB_ROOT', tmp_path)
    with pytest.raises(HTTPError) as result:
        urlopen(assets_server + '/app.js')
    assert result.value.code == 503
    error = json.loads(result.value.read())
    assert 'metro.js' in error['error'] and '安装不完整' in error['error']


def test_dependency_change_versions_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'WEB_ROOT', tmp_path)
    for name in web.APP_SCRIPT_PARTS:
        (tmp_path/name).write_text('// initial', encoding='utf-8')
    html = '<script src="/app.js"></script>'
    first = web.version_static_html(html)
    (tmp_path/'metro.js').write_text('// changed', encoding='utf-8')
    assert first != web.version_static_html(html)
