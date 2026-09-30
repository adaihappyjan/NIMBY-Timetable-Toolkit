"""Demand-only ORM cache. No prefetch, arbitrary upstreams, or save-file access.

The independent loopback daemon survives closing the desktop window. SQLite owns
all tile data, so eviction never walks or deletes user directories. stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor, TimeoutError as FutureTimeout
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

STYLES = ('standard', 'maxspeed', 'signals', 'electrification', 'gauge')
UPSTREAM = 'https://tiles.openrailwaymap.org'
USER_AGENT = 'NIMBY-Timetable-Toolkit/1.6 ORMCache (+https://github.com/adaihappyjan/NIMBY-Timetable-Toolkit)'
MAX_TILE = 4 * 1024 * 1024
PNG = b'\x89PNG\r\n\x1a\n'
SERVICE = 'nimby-orm-cache-v1'
ENGINE_VERSION = 2
_CONTROL_LOCK = threading.Lock()


def defaults(root: Path) -> dict:
    return dict(port=58743, directory=str(root / 'map-cache'), max_mb=2048,
                max_age_days=90, offline=False, autostart=False)


def validate(config: dict, root: Path) -> dict:
    result = defaults(root)
    result.update({k: v for k, v in config.items() if k in result})
    for key, low, high in [('port', 1024, 65535), ('max_mb', 64, 51200), ('max_age_days', 1, 3650)]:
        value = result[key]
        if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)) or not low <= int(value) <= high:
            raise ValueError(f'{key} 必须为 {low}–{high} 的整数')
        result[key] = int(value)
    for key in ('offline', 'autostart'):
        if not isinstance(result[key], bool):
            raise ValueError(f'{key} 必须为开关值')
    directory = Path(str(result['directory']).strip()).expanduser()
    if not directory.is_absolute() or directory == Path(directory.anchor):
        raise ValueError('请选择绝对路径下的专用缓存目录，不能使用磁盘根目录')
    result['directory'] = str(directory.resolve())
    return result


def read_config(root: Path) -> dict:
    path = root / 'orm-cache.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return validate(config, root)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + '.partial')
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    partial.replace(path)


def token(root: Path) -> str:
    path = root / 'orm-cache.token'
    root.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='ascii') as f:
            f.write(secrets.token_hex(32))
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    except FileExistsError:
        pass
    return path.read_text(encoding='ascii').strip()


def tile_key(route: str) -> str:
    match = re.fullmatch(r'/tiles/(standard|maxspeed|signals|electrification|gauge)/(\d{1,2})/(\d{1,6})/(\d{1,6})\.png', route)
    if not match:
        raise ValueError('无效的 ORM 瓦片地址')
    style, z, x, y = match.groups()
    z, x, y = int(z), int(x), int(y)
    if not 0 <= z <= 19 or x >= 2 ** z or y >= 2 ** z:
        raise ValueError('瓦片坐标超出范围')
    return f'{style}/{z}/{x}/{y}.png'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, 'Unexpected tile redirect', headers, fp)


def download(key: str, etag: str, modified: str) -> tuple[int, dict, bytes]:
    headers = {'User-Agent': USER_AGENT, 'Accept': 'image/png'}
    if etag:
        headers['If-None-Match'] = etag
    if modified:
        headers['If-Modified-Since'] = modified
    req = Request(f'{UPSTREAM}/{key}', headers=headers)
    # No redirect following: only this fixed provider can receive requests.
    try:
        with build_opener(NoRedirect()).open(req, timeout=5) as response:
            return response.status, dict(response.headers.items()), response.read(MAX_TILE + 1)
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), b''


def header(headers: dict, name: str) -> str:
    return next((str(v) for k, v in headers.items() if k.lower() == name.lower()), '')


def lifetime(headers: dict) -> int:
    cc = header(headers, 'Cache-Control').lower()
    if 'no-cache' in cc:
        return 0
    match = re.search(r'(?:^|,)\s*max-age=(\d+)', cc)
    age = header(headers, 'Age')
    return max(0, min(30 * 86400, int(match[1])) - (int(age) if age.isdigit() else 0)) if match else 7 * 86400


class Cache:
    def __init__(self, root: Path, config: dict, fetch=download):
        self.root, self.config, self.fetch = root, config, fetch
        self.lock = threading.RLock()
        self.network = threading.Lock()  # Global request spacing, independent of DB lock.
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='orm-download')
        self.flights = {}
        self.pending_limit = 32
        self.wait_timeout = 30.0
        self.request_interval = 0.5  # No increase in upstream request rate.
        self.closed = False
        self.generation = 0
        self.touches = {}
        self.last_flush = time.monotonic()
        self.last_prune = time.monotonic()
        self.coalesced = self.queue_full = self.wait_timeouts = self.active_downloads = 0
        self.fetch_count = self.touch_batches = self.prune_runs = 0
        self.fetch_seconds = self.wait_seconds = 0.0
        self.hits = self.misses = self.downloads = self.errors = 0
        self.last_error = ''
        self.next_request = 0.0
        self.blocked_until = 0.0
        cooldown = root / 'orm-cooldown.json'
        if cooldown.exists():
            self.blocked_until = float(json.loads(cooldown.read_text())['until'])
        owned = Path(config['directory']) / SERVICE
        owned.mkdir(parents=True, exist_ok=True)
        self.db_path = owned / 'tiles.sqlite3'
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.execute('PRAGMA auto_vacuum=INCREMENTAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS tiles (key TEXT PRIMARY KEY, data BLOB NOT NULL, size INTEGER NOT NULL, used REAL NOT NULL, expires REAL NOT NULL, etag TEXT, modified TEXT)')
        self.db.execute('CREATE INDEX IF NOT EXISTS tiles_used ON tiles(used)')
        self.db.commit()
        self.count, self.size = self.db.execute('SELECT COUNT(*), COALESCE(SUM(size),0) FROM tiles').fetchone()
        self.prune()

    def flush_touches(self):
        with self.lock:
            if self.touches:
                self.db.executemany('UPDATE tiles SET used=? WHERE key=?',
                                    [(used, key) for key, used in self.touches.items()])
                self.db.commit()
                self.touches.clear()
                self.touch_batches += 1
            self.last_flush = time.monotonic()

    def maintenance(self):
        with self.lock:
            self.flush_touches()
            if time.monotonic() - self.last_prune >= 600:
                self.prune()
            else:
                self._reclaim_pages()

    def _reclaim_pages(self):
        # Bound each maintenance slice; large eviction must not monopolize SQLite.
        free = self.db.execute('PRAGMA freelist_count').fetchone()[0]
        for _ in range(min(free, 128)):
            self.db.execute('PRAGMA incremental_vacuum(1)')
        self.db.commit()

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            self.flush_touches()
            self.db.close()

    def prune(self, clear=False) -> int:
        with self.lock:
            self.prune_runs += 1
            self.flush_touches()
            before = self.count
            if clear:
                self.generation += 1  # In-flight responses cannot refill a cleared cache.
                self.db.execute('DELETE FROM tiles')
            else:
                self.db.execute('DELETE FROM tiles WHERE used < ?', (time.time() - self.config['max_age_days'] * 86400,))
                total = self.db.execute('SELECT COALESCE(SUM(size),0) FROM tiles').fetchone()[0]
                limit = self.config['max_mb'] * 1048576
                if total > limit:
                    target = limit * 0.95  # Leave room to avoid pruning every new tile.
                    while total > target:
                        rows = self.db.execute('SELECT key,size FROM tiles ORDER BY used LIMIT 256').fetchall()
                        if not rows:
                            break
                        victims = []
                        for key, size in rows:
                            victims.append((key,))
                            total -= size
                            if total <= target:
                                break
                        self.db.executemany('DELETE FROM tiles WHERE key=?', victims)
            self.db.commit()
            self._reclaim_pages()
            self.count, self.size = self.db.execute('SELECT COUNT(*), COALESCE(SUM(size),0) FROM tiles').fetchone()
            self.last_prune = time.monotonic()
            return before - self.count

    def status(self) -> dict:
        with self.lock:
            return dict(running=True, service=SERVICE, engine_version=ENGINE_VERSION,
                        config=self.config.copy(), count=self.count, bytes=self.size,
                        disk_bytes=self.db_path.stat().st_size, hits=self.hits, misses=self.misses,
                        downloads=self.downloads, errors=self.errors, last_error=self.last_error,
                        paused_seconds=max(0, int(self.blocked_until - time.time())), urls=urls(self.config),
                        pending=len(self.flights), active_downloads=self.active_downloads,
                        coalesced=self.coalesced, queue_full=self.queue_full, wait_timeouts=self.wait_timeouts,
                        average_fetch_ms=round(self.fetch_seconds * 1000 / max(1, self.fetch_count)),
                        average_wait_ms=round(self.wait_seconds * 1000 / max(1, self.misses)),
                        pending_touches=len(self.touches), touch_batches=self.touch_batches,
                        prune_runs=self.prune_runs)

    def fail(self, reason: str, seconds: float) -> None:
        with self.lock:
            self.errors += 1
            self.last_error = reason
            self.blocked_until = max(self.blocked_until, time.time() + seconds)
            atomic_json(self.root / 'orm-cooldown.json', {'until': self.blocked_until})

    def get(self, key: str) -> tuple[int, bytes, str]:
        with self.lock:
            if self.closed:
                return 503, b'', 'stopping'
            row = self.db.execute('SELECT data,expires,etag,modified FROM tiles WHERE key=?', (key,)).fetchone()
            if row:
                self.touches[key] = time.time()
                if len(self.touches) >= 1024 or time.monotonic() - self.last_flush >= 10:
                    self.flush_touches()
                if row[1] > time.time() or self.config['offline'] or self.blocked_until > time.time():
                    self.hits += 1
                    return 200, row[0], 'hit'
            self.misses += 1
            if self.config['offline'] or self.blocked_until > time.time():
                return 503, b'', 'offline-or-paused'
            flight = self.flights.get(key)
            if flight:
                self.coalesced += 1
            else:
                if len(self.flights) >= self.pending_limit:
                    self.queue_full += 1
                    return (200, row[0], 'stale') if row else (503, b'', 'busy')
                flight = {'waiters': 0}
                self.flights[key] = flight
                flight['future'] = self.pool.submit(self._download, key, row, self.generation)
                flight['future'].add_done_callback(lambda f: self._finish_flight(key, flight))
            flight['waiters'] += 1
        started = time.monotonic()
        try:
            return flight['future'].result(timeout=self.wait_timeout)
        except CancelledError:
            return 503, b'', 'stopping'
        except FutureTimeout:
            with self.lock:
                self.wait_timeouts += 1
            return (200, row[0], 'stale') if row else (503, b'', 'wait-timeout')
        finally:
            with self.lock:
                self.wait_seconds += time.monotonic() - started
                flight['waiters'] -= 1
                if not flight['waiters']:
                    flight['future'].cancel()  # Don't download queued work nobody is waiting on.

    def _finish_flight(self, key, flight):
        with self.lock:
            if self.flights.get(key) is flight:
                self.flights.pop(key)

    def _download(self, key, row, generation):
        with self.network:
            # Older Windows/Python monotonic clocks can tick more coarsely than
            # sleep(). Recheck the deadline after waking instead of assuming a
            # single sleep advanced the clock far enough to admit the request.
            while (remaining := self.next_request - time.monotonic()) > 0:
                time.sleep(remaining)
            with self.lock:
                if self.closed or generation != self.generation or self.config['offline'] or self.blocked_until > time.time():
                    return (200, row[0], 'stale') if row else (503, b'', 'offline-or-paused')
                self.active_downloads += 1
            self.next_request = time.monotonic() + self.request_interval
        started = time.monotonic()
        try:
            try:
                code, headers, data = self.fetch(key, row[2] or '' if row else '', row[3] or '' if row else '')
                if code == 429:
                    retry = header(headers, 'Retry-After')
                    try:
                        delay = float(retry) if retry.isdigit() else parsedate_to_datetime(retry).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        delay = 900
                    self.fail('ORM 限流（429），已暂停联网；缓存仍可使用', max(60, delay))
                elif code == 304 and row:
                    with self.lock:
                        if generation == self.generation:
                            self.db.execute('UPDATE tiles SET expires=? WHERE key=?', (time.time() + lifetime(headers), key))
                            self.db.commit()
                    return 200, row[0], 'revalidated'
                elif code == 200 and len(data) <= MAX_TILE and data.startswith(PNG) and data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82') and 'image/png' in header(headers, 'Content-Type').lower():
                    with self.lock:
                        self.downloads += 1
                        self.last_error = ''
                        if generation == self.generation and 'no-store' not in header(headers, 'Cache-Control').lower():
                            previous = self.db.execute('SELECT size FROM tiles WHERE key=?', (key,)).fetchone()
                            self.db.execute('INSERT OR REPLACE INTO tiles VALUES (?,?,?,?,?,?,?)',
                                            (key, data, len(data), time.time(), time.time() + lifetime(headers), header(headers, 'ETag'), header(headers, 'Last-Modified')))
                            self.db.commit()
                            self.count += 0 if previous else 1
                            self.size += len(data) - (previous[0] if previous else 0)
                            if self.size > self.config['max_mb'] * 1048576:
                                self.prune()
                    return 200, data, 'download'
                else:
                    self.fail(f'ORM 响应不可用（HTTP {code}），未缓存错误内容', 60 if code != 403 else 900)
            except Exception as exc:
                self.fail(f'下载或缓存失败：{type(exc).__name__}；稍后再试', 60)
            return (200, row[0], 'stale') if row else (503, b'', 'upstream-error')
        finally:
            with self.lock:
                self.active_downloads -= 1
                self.fetch_count += 1
                self.fetch_seconds += time.monotonic() - started


def urls(config: dict) -> dict:
    return {style: f'http://127.0.0.1:{config["port"]}/tiles/{style}/{{z}}/{{x}}/{{y}}.png' for style in STYLES}


class Server(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 96

    def __init__(self, address, cache: Cache, secret: str):
        self.cache, self.secret = cache, secret
        self.slots = threading.BoundedSemaphore(96)
        self.tile_slots = threading.BoundedSemaphore(64)  # Leave threads for status/stop.
        super().__init__(address, TileHandler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class TileHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def reply(self, code: int, data: bytes, mime='application/json; charset=utf-8', cache=''):
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cache:
            self.send_header('X-Tile-Cache', cache)
            self.send_header('Access-Control-Allow-Origin', '*')
        if code == 503:
            self.send_header('Retry-After', '2' if cache in ('busy', 'wait-timeout') else '60')
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(data)

    def json(self, value, code=200):
        self.reply(code, json.dumps(value, ensure_ascii=False).encode('utf-8'))

    def allowed(self) -> bool:
        host = self.headers.get('Host', '')
        if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
            self.json({'ok': False, 'error': 'Invalid Host'}, 403)
            return False
        return True

    def authorized(self) -> bool:
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.secret):
            self.json({'ok': False, 'error': 'Unauthorized'}, 403)
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        route = urlparse(self.path).path
        if route == '/status':
            if self.authorized():
                self.json({'ok': True, **self.server.cache.status()})
            return
        try:
            key = tile_key(route)
        except ValueError:
            self.json({'ok': False, 'error': 'Invalid tile'}, 404)
            return
        try:
            if not self.server.tile_slots.acquire(blocking=False):
                with self.server.cache.lock:
                    self.server.cache.queue_full += 1
                self.reply(503, b'', 'text/plain', 'busy')
                return
            try:
                code, data, source = self.server.cache.get(key)
            finally:
                self.server.tile_slots.release()
            self.reply(code, data, 'image/png' if code == 200 else 'text/plain', source)
        except Exception:
            self.json({'ok': False, 'error': '缓存读取失败，请检查磁盘空间与目录权限'}, 500)

    def do_POST(self):
        if not self.allowed() or not self.authorized():
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 8192:
                raise ValueError('请求过大')
            value = json.loads(self.rfile.read(length)) if length else {}
            cache = self.server.cache
            if self.path == '/stop':
                with cache.lock:
                    cache.closed = True
                self.json({'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path == '/config':
                with cache.lock:
                    updated = validate({**cache.config, **value}, cache.root)
                    if any(updated[k] != cache.config[k] for k in ('port', 'directory')):
                        raise ValueError('更改端口或目录前请先停止缓存服务')
                    atomic_json(cache.root / 'orm-cache.json', updated)
                    cache.config = updated
                    cache.prune()
            elif self.path == '/clear':
                cache.prune(clear=True)
            elif self.path == '/prune':
                cache.prune()
            else:
                raise ValueError('未知操作')
            self.json({'ok': True, **cache.status()})
        except Exception as exc:
            self.json({'ok': False, 'error': str(exc)}, 400)


def rpc(root: Path, path='/status', value=None) -> dict:
    config = read_config(root)
    request = Request(f'http://127.0.0.1:{config["port"]}{path}',
                      data=None if value is None else json.dumps(value).encode(),
                      headers={'Authorization': 'Bearer ' + token(root), 'Content-Type': 'application/json'})
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=8) as response:
        result = json.loads(response.read(65536))
    if not result.get('ok'):
        raise RuntimeError(result.get('error', '缓存服务请求失败'))
    if path == '/status' and result.get('service') != SERVICE:
        raise RuntimeError('端口被其他程序使用')
    return result


def control(root: Path, action='status', value=None) -> dict:
    with _CONTROL_LOCK:
        config = read_config(root)
        try:
            status = rpc(root)
        except (OSError, ValueError, RuntimeError):
            status = dict(running=False, config=config, urls=urls(config))
        if action == 'status':
            return status
        if action == 'config':
            updated = validate({**config, **(value or {})}, root)
            if status['running']:
                return rpc(root, '/config', updated)
            atomic_json(root / 'orm-cache.json', updated)
            return dict(running=False, config=updated, urls=urls(updated))
        if action == 'start':
            if status['running']:
                return status
            token(root)
            exe = Path(sys.executable)
            if os.name == 'nt' and exe.with_name('pythonw.exe').exists():
                exe = exe.with_name('pythonw.exe')
            process = subprocess.Popen([str(exe), str(Path(__file__).resolve()), '--serve', '--root', str(root)],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(30):
                time.sleep(0.1)
                try:
                    return rpc(root)
                except (OSError, ValueError, RuntimeError):
                    if process.poll() is not None:
                        break
            raise RuntimeError('缓存启动失败：请检查端口占用、缓存目录权限或 orm-start-error.txt')
        if action in ('stop', 'clear', 'prune'):
            if not status['running']:
                if action == 'stop':
                    return status
                raise ValueError('请先启动缓存服务')
            result = rpc(root, '/' + action, {})
            if action == 'stop':
                for _ in range(20):
                    time.sleep(0.1)
                    try:
                        rpc(root)
                    except (OSError, ValueError, RuntimeError):
                        return dict(running=False, config=config, urls=urls(config))
                raise RuntimeError('服务仍在停止中，请稍后刷新')
            return result
        raise ValueError('未知缓存操作')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    server = None
    try:
        config = read_config(args.root)
        # Bind before opening the DB, preventing two daemon writers.
        server = Server(('127.0.0.1', config['port']), None, token(args.root))
        cache = Cache(args.root, config)
        server.cache = cache
        def maintenance():
            while not stopped.wait(10):
                try:
                    cache.maintenance()
                except Exception as exc:
                    with cache.lock:
                        cache.last_error = f'缓存清理失败：{type(exc).__name__}'
        stopped = threading.Event()
        threading.Thread(target=maintenance, daemon=True).start()
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            stopped.set()
            server.server_close()
            cache.close()
    except Exception as exc:
        args.root.mkdir(parents=True, exist_ok=True)
        atomic_json(args.root / 'orm-start-error.txt', {'error': str(exc)})
        if server:
            server.server_close()
        raise


if __name__ == '__main__':
    main()
