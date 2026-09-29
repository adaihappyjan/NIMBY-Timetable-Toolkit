import os
from unittest.mock import Mock

import pytest
import toolkit_tilewatch as tw


def test_starts_once_per_game_and_respects_manual_stop():
    state, start = tw.WatchState(), Mock()
    state.tick(False, 0, start)
    start.assert_not_called()
    state.tick(True, 5, start)
    state.tick(True, 10, start)
    start.assert_called_once()
    state.tick(False, 15, start)
    state.tick(True, 20, start)
    assert start.call_count == 2


def test_failed_start_retries_at_most_once_per_minute():
    state = tw.WatchState()
    start = Mock(side_effect=[RuntimeError('occupied'), None])
    assert state.tick(True, 1, start) == 'occupied'
    state.tick(True, 5, start)
    assert start.call_count == 1
    state.tick(True, 61, start)
    assert state.started_for_game


def test_disabled_by_default_and_heartbeat(tmp_path):
    assert tw.status(tmp_path) == {'enabled': False, 'watcher_running': False}


@pytest.mark.skipif(os.name != 'nt', reason='Windows startup shortcut')
def test_startup_script_no_console_and_scoped_removal(tmp_path):
    script = tw.shortcut_script(tmp_path / "test's dir", True)
    assert 'pythonw.exe' in script
    assert "test''s dir" in script
    assert 'GetFolderPath(\'Startup\')' in script
    assert tw.MARKER in script
    assert 'Remove-Item' not in script
    disabled = tw.shortcut_script(tmp_path, False)
    assert 'Remove-Item -LiteralPath $watchLink' in disabled
    assert '-Recurse' not in disabled


def test_invalid_switch_rejected_before_windows_changes(tmp_path):
    with pytest.raises(ValueError):
        tw.configure(tmp_path, 'yes')
