import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import toolkit_backend as backend
import toolkit_binary as binary

HEADER = bytes.fromhex('4e4d42590200010013000a00') + bytes(20)


def test_save_version_without_json():
    info = binary.save_version_info(HEADER)
    assert info['save_release'] == '1.19.10'
    assert info['safe_to_write']


@pytest.mark.parametrize('header', [b'', b'invalid header', HEADER[:10],
    HEADER[:10] + b'\x0b\x00' + HEADER[12:], b'NMBY\x03' + HEADER[5:]])
def test_unknown_save_never_inherits_supported_export(header, tmp_path):
    info = backend.detect_game_version([{'class':'ExportMeta','model_version':230}], header)
    assert not info['safe_to_write']
    target = tmp_path/'new.nimbyrails5'
    with pytest.raises(RuntimeError, match='阻止写入'):
        backend.write_output(tmp_path/'input', target, header, b'before', b'after', {}, len(header), 3)
    assert not target.exists()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('model', ['230', {}, [], True, None])
def test_malformed_export_model_is_unknown_not_crash(model):
    assert backend.detect_game_version([{'class':'ExportMeta','model_version':model}], HEADER)['status']=='unknown'


def test_known_header_newer_model_not_fully_verified():
    info = backend.detect_game_version([{'class':'ExportMeta','model_version':999}], HEADER)
    assert info['save_release']=='1.19.10'
    assert not info['safe_to_write']


def test_11910_roundtrip_retains_header_and_input(tmp_path):
    original = tmp_path/'input.nimbyrails5'
    original_bytes = HEADER + binary.Zstd().compress(b'before')
    original.write_bytes(original_bytes)
    target = tmp_path/'output.nimbyrails5'
    result = backend.write_output(original, target, HEADER, b'before', b'after', {}, len(HEADER), 3)
    header, frame, _ = binary.split_save(target)
    assert header == HEADER
    assert binary.Zstd().decompress(frame) == b'after'
    assert original.read_bytes() == original_bytes
    assert result['save_compatibility']['save_release'] == '1.19.10'
