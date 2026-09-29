from __future__ import annotations

import base64
import concurrent.futures
import json
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import toolkit_tilecache as tc

IMAGE = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
HEADERS = {'Content-Type': 'image/png', 'Cache-Control': 'max-age=3600', 'ETag': 'tile-v1'}
KEY = 'standard/2/1/1.png'


@pytest.fixture
def cache(tmp_path):
    instance = tc.Cache(tmp_path, tc.defaults(tmp_path), lambda *_: (200, HEADERS, IMAGE))
    yield instance
    instance.close()


def test_miss_hit_offline_restart(cache):
    assert cache.get(KEY) == (200, IMAGE, 'download')
    assert cache.get(KEY) == (200, IMAGE, 'hit')
    cache.config['offline'] = True
    assert cache.get('standard/2/2/1.png')[0] == 503
    reopened = tc.Cache(cache.root, cache.config, lambda *_: pytest.fail('no network'))
    try:
        assert reopened.get(KEY) == (200, IMAGE, 'hit')
        assert reopened.status()['count'] == 1
    finally:
        reopened.close()


@pytest.mark.parametrize('path', ['/tiles/standard/20/1/1.png', '/tiles/standard/2/4/1.png',
    '/tiles/standard/2/-1/1.png', '/tiles/../2/1/1.png', '/tiles/standard/2/1/1.png/extra',
    '/tiles/unknown/2/1/1.png', '/tiles/standard/2/1/%2e%2e.png'])
def test_invalid_coordinates(path):
    with pytest.raises(ValueError):
        tc.tile_key(path)


def test_styles_and_boundaries():
    for style in tc.STYLES:
        assert tc.tile_key(f'/tiles/{style}/19/524287/0.png') == f'{style}/19/524287/0.png'


def test_rate_limit_stops_all_styles_and_survives_restart(cache):
    calls = []
    cache.fetch = lambda *args: (calls.append(args) or (429, {'Retry-After': '120'}, b''))
    assert cache.get(KEY)[0] == 503
    assert cache.get('signals/2/1/1.png')[0] == 503
    assert len(calls) == 1
    assert cache.status()['paused_seconds'] >= 118
    reopened = tc.Cache(cache.root, cache.config, lambda *_: pytest.fail('must remain paused'))
    try:
        assert reopened.get(KEY)[0] == 503
    finally:
        reopened.close()


@pytest.mark.parametrize('response', [(200, HEADERS, b'<html>error</html>'),
    (200, {'Content-Type': 'text/html'}, IMAGE), (200, HEADERS, tc.PNG + b'x' * tc.MAX_TILE),
    (500, {}, b''), (404, {}, b'')])
def test_errors_never_saved_as_tiles(cache, response):
    cache.fetch = lambda *_: response
    assert cache.get(KEY)[0] == 503
    assert cache.status()['count'] == 0
    assert cache.status()['errors'] == 1


def test_revalidation_and_stale_on_failure(cache):
    cache.get(KEY)
    cache.db.execute('UPDATE tiles SET expires=0')
    cache.db.commit()
    seen = []
    cache.fetch = lambda *args: (seen.append(args) or (304, HEADERS, b''))
    assert cache.get(KEY) == (200, IMAGE, 'revalidated')
    assert seen[0][1] == 'tile-v1'
    cache.db.execute('UPDATE tiles SET expires=0')
    cache.db.commit()
    cache.fetch = lambda *_: (503, {}, b'')
    assert cache.get(KEY) == (200, IMAGE, 'stale')


def test_no_store(cache):
    cache.fetch = lambda *_: (200, {**HEADERS, 'Cache-Control': 'no-store'}, IMAGE)
    assert cache.get(KEY)[0] == 200
    assert cache.status()['count'] == 0


def test_same_tile_single_download(cache):
    calls = []
    def fetch(*args):
        calls.append(args)
        time.sleep(.03)
        return 200, HEADERS, IMAGE
    cache.fetch = fetch
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.get(KEY), range(8)))
    assert all(r[0] == 200 for r in results)
    assert len(calls) == 1


def test_quota_age_clear_only_owned_rows(cache):
    sentinel = Path(cache.config['directory']) / 'keep-user-file.txt'
    sentinel.write_text('preserve')
    cache.config['max_mb'] = len(IMAGE) / 1048576 / 0.95  # Include the 5% eviction buffer.
    cache.get(KEY)
    cache.get('standard/2/2/1.png')
    assert cache.status()['count'] == 1
    assert cache.db.execute('SELECT key FROM tiles').fetchone()[0] == 'standard/2/2/1.png'
    cache.flush_touches()
    cache.db.execute('UPDATE tiles SET used=0')
    cache.db.commit()
    assert cache.prune() == 1
    cache.get(KEY)
    assert cache.prune(clear=True) == 1
    assert sentinel.read_text() == 'preserve'


@pytest.mark.parametrize('patch', [{'port': 80}, {'max_mb': 0}, {'max_age_days': -1},
    {'offline': 'false'}, {'port': 58743.5}, {'directory': '.'}, {'directory': Path.cwd().anchor}])
def test_settings_validation(tmp_path, patch):
    with pytest.raises(ValueError):
        tc.validate(patch, tmp_path)


def test_hits_batch_writes_and_status_does_not_scan_database(cache):
    cache.get(KEY)
    statements = []
    cache.db.set_trace_callback(statements.append)
    for _ in range(200):
        assert cache.get(KEY)[2] == 'hit'
        cache.status()
    assert not any('UPDATE' in s or 'SUM(' in s or 'COUNT(' in s or 'COMMIT' in s for s in statements)
    assert cache.status()['pending_touches'] == 1
    cache.flush_touches()
    assert sum('UPDATE' in s for s in statements) == 1
    assert cache.status()['pending_touches'] == 0


def test_downloads_under_quota_do_not_prune_per_tile(cache):
    cache.request_interval = 0
    before = cache.prune_runs
    for x in range(8):
        assert cache.get(f'standard/4/{x}/1.png')[0] == 200
    assert cache.prune_runs == before
    assert cache.status()['count'] == 8
    assert cache.status()['bytes'] == 8 * len(IMAGE)


def test_two_downloads_can_overlap_and_duplicates_coalesce(cache):
    entered = threading.Barrier(2)
    calls = []
    cache.request_interval = 0
    def fetch(key, *_):
        calls.append(key)
        entered.wait(timeout=3)
        time.sleep(.05)
        return 200, HEADERS, IMAGE
    cache.fetch = fetch
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(cache.get, key) for key in [KEY, 'signals/2/1/1.png', KEY, KEY]]
        assert all(f.result(timeout=5)[0] == 200 for f in futures)
    assert len(calls) == 2
    assert cache.status()['coalesced'] >= 1
    assert cache.status()['active_downloads'] == 0


def test_upstream_rate_is_global_across_workers(cache):
    starts = []
    cache.request_interval = .06
    def fetch(*_):
        starts.append(time.monotonic())
        time.sleep(.1)
        return 200, HEADERS, IMAGE
    cache.fetch = fetch
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(cache.get, [f'standard/3/{x}/1.png' for x in range(4)]))
    assert all(r[0] == 200 for r in results)
    assert all(b - a >= .05 for a, b in zip(starts, starts[1:]))


def test_clear_during_download_does_not_repopulate_cache(cache):
    entered, release = threading.Event(), threading.Event()
    def fetch(*_):
        entered.set()
        assert release.wait(timeout=3)
        return 200, HEADERS, IMAGE
    cache.fetch = fetch
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cache.get, KEY)
        assert entered.wait(timeout=3)
        cache.prune(clear=True)
        release.set()
        assert future.result(timeout=3)[0] == 200
    assert cache.status()['count'] == 0


def test_timed_out_unstarted_work_is_cancelled(cache):
    release = threading.Event()
    calls = []
    cache.wait_timeout = .05
    cache.request_interval = 0
    def fetch(key, *_):
        calls.append(key)
        release.wait(timeout=3)
        return 200, HEADERS, IMAGE
    cache.fetch = fetch
    try:
        assert cache.get(KEY)[2] == 'wait-timeout'
        assert cache.get('signals/2/1/1.png')[2] == 'wait-timeout'
        assert cache.get('maxspeed/2/1/1.png')[2] == 'wait-timeout'
        assert len(calls) == 2
        assert 'maxspeed/2/1/1.png' not in cache.flights
        assert cache.status()['wait_timeouts'] == 3
    finally:
        release.set()


def test_queue_full_is_measured_separately_from_network_errors(cache):
    cache.pending_limit = 0
    assert cache.get(KEY)[2] == 'busy'
    assert cache.status()['queue_full'] == 1
    assert cache.status()['errors'] == 0


def test_pause_is_rechecked_after_waiting_for_rate_slot(cache):
    calls = []
    cache.fetch = lambda *args: (calls.append(args) or (429, {}, b''))
    cache.request_interval = .1
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(cache.get, [KEY, 'signals/2/1/1.png']))
    assert all(r[0] == 503 for r in results)
    assert len(calls) == 1


def test_waiting_more_than_old_five_second_limit_succeeds(cache):
    cache.fetch = lambda *_: (time.sleep(5.1) or (200, HEADERS, IMAGE))
    assert cache.get(KEY)[0] == 200
    assert cache.status()['wait_timeouts'] == 0


def test_http_serves_png_and_authenticates_controls(cache):
    server = tc.Server(('127.0.0.1', 0), cache, 'test-token')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/tiles/' + KEY) as response:
            assert response.read() == IMAGE
            assert response.headers['X-Tile-Cache'] == 'download'
        with pytest.raises(HTTPError) as err:
            urlopen(Request(base + '/clear', data=b'{}'))
        assert err.value.code == 403
        with pytest.raises(HTTPError):
            urlopen(Request(base + '/status', headers={'Host': 'evil.example'}))
        with urlopen(Request(base + '/status', headers={'Authorization': 'Bearer test-token'})) as response:
            assert json.load(response)['count'] == 1
        with urlopen(Request(base + '/clear', data=b'{}', headers={'Authorization': 'Bearer test-token'})) as response:
            assert json.load(response)['count'] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_controller_daemon_start_stop_and_settings_persistence(tmp_path):
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    cfg = tc.control(tmp_path, 'config', {'port': port, 'offline': True})
    assert not cfg['running']
    try:
        started = tc.control(tmp_path, 'start')
        assert started['running'] and started['config']['offline']
        assert tc.control(tmp_path, 'start')['running']
        updated = tc.control(tmp_path, 'config', {'max_mb': 128})
        assert updated['config']['max_mb'] == 128
        assert tc.read_config(tmp_path)['max_mb'] == 128
        assert tc.control(tmp_path, 'prune')['count'] == 0
    finally:
        stopped = tc.control(tmp_path, 'stop')
        assert not stopped['running']


def test_web_routes_and_release_include_module(tmp_path, monkeypatch):
    import toolkit_webapp as web
    monkeypatch.setattr(web, 'SETTINGS_DIR', tmp_path)
    server = web.make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/api/tilecache/status') as response:
            data = json.load(response)
            assert data['ok'] and not data['cache']['running']
        payload = json.dumps({'action': 'config', 'config': {'offline': True}}).encode()
        with urlopen(Request(base + '/api/tilecache/action', data=payload)) as response:
            assert json.load(response)['cache']['config']['offline']
        with pytest.raises(HTTPError) as err:
            urlopen(Request(base + '/api/tilecache/action', data=payload, headers={'Origin': 'https://evil.example'}))
        assert err.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
