"""Per-user, no-console game-start watcher; no game injection or save access."""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolkit_tilecache import atomic_json, control

MARKER = 'NIMBY Toolkit ORM game-start watcher v1'


def settings(root: Path) -> dict:
    path = root / 'orm-game-start.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'enabled': False}


def status(root: Path) -> dict:
    result = {'enabled': bool(settings(root).get('enabled')), 'watcher_running': False}
    try:
        state = json.loads((root / 'orm-game-watch-state.json').read_text(encoding='utf-8'))
        result.update(state)
        result['watcher_running'] = time.time() - state['checked_at'] < 20 and result['enabled']
    except (OSError, ValueError, KeyError):
        pass
    return result


def game_running() -> bool:
    """Read process names with Toolhelp; do not open process memory or UI."""
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('pid', w.DWORD),
                    ('heap', ctypes.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
                    ('exe', w.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            if entry.exe.lower() == 'nimbyrails.exe':
                return True
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
        return False
    finally:
        kernel.CloseHandle(handle)


def pythonw() -> Path:
    candidate = Path(sys.executable).with_name('pythonw.exe')
    if os.name != 'nt' or not candidate.is_file():
        raise RuntimeError('游戏联动启动目前需要 Windows 和 pythonw.exe')
    return candidate


def shortcut_script(root: Path, enabled: bool) -> str:
    def quote(s):
        return "'" + str(s).replace("'", "''") + "'"
    executable = pythonw()
    args = subprocess.list2cmdline([str(Path(__file__).resolve()), '--root', str(root)])
    # Only the one named and marked shortcut belongs to this feature.
    return '\n'.join([
        "$ErrorActionPreference = 'Stop'",
        "$watchLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'NIMBY-ORM-Game-Watcher.lnk'",
        "$watchShell = New-Object -ComObject WScript.Shell",
        "$watchShortcut = $watchShell.CreateShortcut($watchLink)",
        f"if ((Test-Path -LiteralPath $watchLink) -and $watchShortcut.Description -ne {quote(MARKER)}) {{ throw 'Unrecognized startup shortcut; refusing to replace it' }}",
        *([f'$watchShortcut.TargetPath = {quote(executable)}',
           f'$watchShortcut.Arguments = {quote(args)}',
           f'$watchShortcut.WorkingDirectory = {quote(Path(__file__).resolve().parent)}',
           f'$watchShortcut.Description = {quote(MARKER)}',
           '$watchShortcut.WindowStyle = 7', '$watchShortcut.Save()'] if enabled else [
               'if (Test-Path -LiteralPath $watchLink) { Remove-Item -LiteralPath $watchLink }']),
        'Write-Output $watchLink'
    ])


def configure(root: Path, enabled: bool) -> dict:
    if not isinstance(enabled, bool):
        raise ValueError('enabled 必须为开关值')
    script = shortcut_script(root, enabled)
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    if completed.returncode:
        raise RuntimeError('无法配置当前用户的启动项：' + completed.stderr.decode(errors='replace')[-1200:])
    atomic_json(root / 'orm-game-start.json', {'enabled': enabled})
    if enabled:
        subprocess.Popen([str(pythonw()), str(Path(__file__).resolve()), '--root', str(root)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    return status(root)


class WatchState:
    def __init__(self):
        self.started_for_game = False
        self.retry_at = 0.0

    def tick(self, running: bool, now: float, start) -> str:
        if not running:
            self.started_for_game = False
            self.retry_at = 0.0
            return ''
        if self.started_for_game or now < self.retry_at:
            return ''
        try:
            start()
            self.started_for_game = True
            return ''
        except Exception as exc:
            self.retry_at = now + 60
            return str(exc)


def watch(root: Path):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    kernel.CreateMutexW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    key = hashlib.sha256(str(root.resolve()).lower().encode()).hexdigest()[:24]
    handle = kernel.CreateMutexW(None, False, 'Local\\NIMBYORMWatch-' + key)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return  # Idempotent startup: only one watcher per profile/session.
    state = WatchState()
    try:
        while settings(root).get('enabled'):
            running, error = False, ''
            try:
                running = game_running()
                error = state.tick(running, time.time(), lambda: control(root, 'start'))
            except Exception as exc:
                error = str(exc)
            atomic_json(root / 'orm-game-watch-state.json', {
                'checked_at': time.time(), 'pid': os.getpid(), 'game_running': running,
                'started_for_game': state.started_for_game, 'error': error,
            })
            time.sleep(5)
    finally:
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    watch(parser.parse_args().root)
