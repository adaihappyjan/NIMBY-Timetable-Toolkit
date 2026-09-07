"""Secure, self-contained updater for the portable toolkit release.

The running app checks the project's GitHub Releases feed, verifies the exact
portable asset against SHA256SUMS.txt and its per-file package manifest, then
launches this module from the staged package as a helper.  The helper waits for
the current process to exit before replacing files, rolls back on any failure,
and restarts the app.  It never touches saves or per-user settings.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen


REPOSITORY = "adaihappyjan/NIMBY-Timetable-Toolkit"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
ARCHIVE_NAME_TEMPLATE = "NIMBY-Timetable-Toolkit-portable-{tag}.zip"
MANIFEST_NAME = ".toolkit-manifest.json"
VERSION_NAME = "VERSION"
CHECK_CACHE_SECONDS = 6 * 60 * 60
MAX_METADATA_BYTES = 2_000_000
MAX_CHECKSUM_BYTES = 1_000_000
MAX_ARCHIVE_BYTES = 100_000_000
MAX_ARCHIVE_FILES = 1_000
MAX_UNCOMPRESSED_BYTES = 250_000_000
UPDATE_LOCK_MAX_AGE_SECONDS = 30 * 60
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ESSENTIAL_FILES = {
    VERSION_NAME,
    "启动工具箱.cmd",
    "launcher.bat",
    "libzstd.dll",
    "toolkit_backend.py",
    "toolkit_updater.py",
    "toolkit_webapp.py",
    "web/app.js",
    "web/index.html",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_version(value: str) -> str:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise RuntimeError(f"不支持的版本号：{value!r}")
    return ".".join(match.groups())


def version_key(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in normalize_version(value).split("."))  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)


def read_current_version(root: Path | None = None) -> str:
    base = Path(root) if root is not None else Path(__file__).resolve().parent
    try:
        return normalize_version((base / VERSION_NAME).read_text(encoding="utf-8-sig").strip())
    except Exception:
        return "0.0.0"


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if not value or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise RuntimeError(f"更新包包含不安全路径：{value!r}")
    if ":" in path.parts[0]:
        raise RuntimeError(f"更新包包含不安全路径：{value!r}")
    return path


def _path_in(root: Path, relative: str) -> Path:
    rel = _safe_relative_path(relative)
    root_resolved = root.resolve()
    path = root_resolved.joinpath(*rel.parts)
    resolved = path.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise RuntimeError(f"更新路径越界：{relative}")
    return path


def _request_bytes(url: str, limit: int, timeout: float = 20.0) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/octet-stream",
            "User-Agent": "NIMBY-Timetable-Toolkit-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed GitHub URLs
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise RuntimeError("更新服务器返回的数据超过安全上限")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("更新服务器返回的数据超过安全上限")
    return data


def parse_release_metadata(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise RuntimeError("最新 Release 元数据无效")
    tag = str(payload.get("tag_name") or "").strip()
    version = normalize_version(tag)
    archive_name = ARCHIVE_NAME_TEMPLATE.format(tag=tag)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("Release 没有可用的下载资产")
    by_name = {
        str(asset.get("name")): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("name")
    }
    archive = by_name.get(archive_name)
    checksum = by_name.get(CHECKSUM_ASSET_NAME)
    if not archive or not checksum:
        raise RuntimeError("Release 缺少便携 ZIP 或 SHA256SUMS.txt")
    archive_url = str(archive.get("browser_download_url") or "")
    checksum_url = str(checksum.get("browser_download_url") or "")
    expected_prefix = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    if not archive_url.startswith(expected_prefix) or not checksum_url.startswith(expected_prefix):
        raise RuntimeError("Release 下载地址不是项目的官方 GitHub 资产")
    size = int(archive.get("size") or 0)
    if size <= 0 or size > MAX_ARCHIVE_BYTES:
        raise RuntimeError("Release 便携包大小无效")
    return {
        "tag_name": tag,
        "version": version,
        "name": str(payload.get("name") or tag)[:200],
        "published_at": str(payload.get("published_at") or ""),
        "notes": str(payload.get("body") or "")[:8_000],
        "release_url": str(payload.get("html_url") or ""),
        "archive_name": archive_name,
        "archive_url": archive_url,
        "archive_size": size,
        "checksum_url": checksum_url,
    }


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(partial, path)


def _load_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _fetch_release(fetcher=_request_bytes) -> dict:
    try:
        payload = json.loads(fetcher(LATEST_RELEASE_API, MAX_METADATA_BYTES).decode("utf-8"))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"无法读取 GitHub 最新版本信息：{exc}") from exc
    return parse_release_metadata(payload)


def check_for_updates(
    current_version: str,
    settings_dir: Path,
    *,
    force: bool = False,
    fetcher=_request_bytes,
) -> dict:
    """Return safe UI metadata, using a six-hour per-user cache by default."""
    current = normalize_version(current_version)
    cache_file = Path(settings_dir) / "update-cache.json"
    cached = _load_json(cache_file)
    release = None
    used_cache = False
    if not force and cached:
        checked_epoch = float(cached.get("checked_epoch") or 0)
        candidate = cached.get("release")
        if time.time() - checked_epoch < CHECK_CACHE_SECONDS and isinstance(candidate, dict):
            try:
                release = parse_release_metadata(candidate)
                used_cache = True
            except Exception:
                release = None
    if release is None:
        release = _fetch_release(fetcher)
        # Cache a GitHub-shaped subset so it is revalidated by the same parser.
        cache_payload = {
            "tag_name": release["tag_name"],
            "name": release["name"],
            "published_at": release["published_at"],
            "body": release["notes"],
            "html_url": release["release_url"],
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": release["archive_name"],
                    "browser_download_url": release["archive_url"],
                    "size": release["archive_size"],
                },
                {
                    "name": CHECKSUM_ASSET_NAME,
                    "browser_download_url": release["checksum_url"],
                    "size": 1,
                },
            ],
        }
        _atomic_json(
            cache_file,
            {"checked_at": utc_now(), "checked_epoch": time.time(), "release": cache_payload},
        )
    return {
        "current_version": current,
        "latest_version": release["version"],
        "tag_name": release["tag_name"],
        "name": release["name"],
        "published_at": release["published_at"],
        "notes": release["notes"],
        "release_url": release["release_url"],
        "asset_size": release["archive_size"],
        "available": is_newer_version(release["version"], current),
        "cached": used_cache,
    }


def _checksum_for_asset(text: str, filename: str) -> str:
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or not _SHA256_RE.fullmatch(parts[0]):
            continue
        listed = parts[1].lstrip("*").strip()
        if listed == filename:
            return parts[0].lower()
    raise RuntimeError("SHA256SUMS.txt 没有当前便携包的校验值")


def _manifest_from_bytes(data: bytes, expected_version: str) -> dict:
    try:
        manifest = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("更新包文件清单无法读取") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise RuntimeError("更新包文件清单版本不受支持")
    if normalize_version(str(manifest.get("version") or "")) != normalize_version(expected_version):
        raise RuntimeError("更新包内部版本与 Release 标签不一致")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("更新包文件清单为空")
    normalized: dict[str, dict] = {}
    for name, info in files.items():
        rel = _safe_relative_path(str(name)).as_posix()
        if rel == MANIFEST_NAME or not isinstance(info, dict):
            raise RuntimeError("更新包文件清单包含无效项目")
        digest = str(info.get("sha256") or "").lower()
        size = int(info.get("size") or -1)
        if not _SHA256_RE.fullmatch(digest) or size < 0:
            raise RuntimeError(f"更新包文件清单项目无效：{rel}")
        if rel in normalized:
            raise RuntimeError(f"更新包文件清单存在重复路径：{rel}")
        normalized[rel] = {"sha256": digest, "size": size}
    if not ESSENTIAL_FILES.issubset(normalized):
        missing = sorted(ESSENTIAL_FILES - set(normalized))
        raise RuntimeError(f"更新包缺少必要文件：{', '.join(missing)}")
    return {"schema": 1, "version": normalize_version(expected_version), "files": normalized}


def extract_verified_archive(
    archive_data: bytes,
    expected_sha256: str,
    expected_version: str,
    destination: Path,
) -> tuple[Path, dict]:
    """Verify the release digest and manifest before extracting any file."""
    actual = hashlib.sha256(archive_data).hexdigest()
    if actual != expected_sha256.lower():
        raise RuntimeError(f"更新包 SHA-256 校验失败（期望 {expected_sha256}，实际 {actual}）")
    if len(archive_data) > MAX_ARCHIVE_BYTES:
        raise RuntimeError("更新包超过安全大小上限")
    try:
        bundle = zipfile.ZipFile(io.BytesIO(archive_data))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("更新包不是有效的 ZIP 文件") from exc
    with bundle:
        infos = [info for info in bundle.infolist() if not info.is_dir()]
        if not infos or len(infos) > MAX_ARCHIVE_FILES:
            raise RuntimeError("更新包文件数量异常")
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise RuntimeError("更新包解压后超过安全大小上限")
        relative_entries: dict[str, zipfile.ZipInfo] = {}
        roots: set[str] = set()
        for info in infos:
            path = _safe_relative_path(info.filename)
            if len(path.parts) < 2:
                raise RuntimeError("更新包缺少顶层版本目录")
            roots.add(path.parts[0])
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            _safe_relative_path(relative)
            # Reject Unix symlinks even when a crafted ZIP reaches Windows.
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError("更新包不允许符号链接")
            if relative in relative_entries:
                raise RuntimeError(f"更新包存在重复路径：{relative}")
            relative_entries[relative] = info
        if len(roots) != 1 or MANIFEST_NAME not in relative_entries:
            raise RuntimeError("更新包顶层目录或文件清单无效")
        manifest = _manifest_from_bytes(
            bundle.read(relative_entries[MANIFEST_NAME]), expected_version
        )
        expected_paths = set(manifest["files"])
        actual_paths = set(relative_entries) - {MANIFEST_NAME}
        if actual_paths != expected_paths:
            missing = sorted(expected_paths - actual_paths)
            extra = sorted(actual_paths - expected_paths)
            raise RuntimeError(f"更新包与文件清单不一致（缺少 {missing[:3]}，多出 {extra[:3]}）")
        for relative, expected in manifest["files"].items():
            info = relative_entries[relative]
            if info.file_size != expected["size"]:
                raise RuntimeError(f"更新包文件大小不符：{relative}")
            data = bundle.read(info)
            if hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise RuntimeError(f"更新包文件校验失败：{relative}")

        package_root = Path(destination) / "package"
        package_root.mkdir(parents=True, exist_ok=False)
        for relative in sorted(expected_paths):
            target = _path_in(package_root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(relative_entries[relative]))
        (package_root / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return package_root, manifest


def _ensure_install_root(root: Path) -> None:
    root = root.resolve()
    if (root / ".git").exists():
        raise RuntimeError("开发源码目录由 Git 管理，自动更新仅用于解压后的官方便携版")
    if not (root / "toolkit_webapp.py").is_file() or not (root / "launcher.bat").is_file():
        raise RuntimeError("当前目录不是完整的 NIMBY 工具箱便携版")
    probe = root / f".update-write-test-{uuid.uuid4().hex}"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except Exception as exc:
        raise RuntimeError(f"软件目录不可写，无法自动更新：{root}") from exc


def acquire_update_lock(settings_dir: Path) -> Path:
    """Create a cross-process lock so two open copies cannot update together."""
    settings = Path(settings_dir).resolve()
    settings.mkdir(parents=True, exist_ok=True)
    lock = settings / "update.lock"
    for attempt in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "created_at": utc_now()}, handle)
            return lock
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0
            if attempt == 0 and age > UPDATE_LOCK_MAX_AGE_SECONDS:
                try:
                    lock.unlink()
                    continue
                except OSError:
                    pass
            raise RuntimeError("另一个工具箱窗口正在准备或安装更新，请先等待它完成")
    raise RuntimeError("无法取得自动更新锁")


def release_update_lock(lock_file: Path | str | None) -> None:
    if not lock_file:
        return
    try:
        Path(lock_file).unlink(missing_ok=True)
    except OSError:
        pass


def prepare_update(
    root: Path,
    settings_dir: Path,
    current_version: str,
    *,
    expected_version: str | None = None,
    fetcher=_request_bytes,
) -> dict:
    """Download, verify and stage the latest official portable package."""
    root = Path(root).resolve()
    settings_dir = Path(settings_dir).resolve()
    _ensure_install_root(root)
    lock_file = acquire_update_lock(settings_dir)
    update_dir: Path | None = None
    try:
        release = _fetch_release(fetcher)
        current = normalize_version(current_version)
        if expected_version and normalize_version(expected_version) != release["version"]:
            raise RuntimeError("最新版本已经变化，请重新检查更新后再安装")
        if not is_newer_version(release["version"], current):
            raise RuntimeError("当前已经是最新版本")
        checksum_data = fetcher(release["checksum_url"], MAX_CHECKSUM_BYTES)
        expected_sha256 = _checksum_for_asset(
            checksum_data.decode("utf-8-sig"), release["archive_name"]
        )
        archive_data = fetcher(release["archive_url"], MAX_ARCHIVE_BYTES)
        if len(archive_data) != release["archive_size"]:
            raise RuntimeError("更新包实际大小与 GitHub Release 元数据不一致")
        update_dir = settings_dir / "updates" / f"{release['version']}-{uuid.uuid4().hex[:8]}"
        update_dir.mkdir(parents=True, exist_ok=False)
        (update_dir / release["archive_name"]).write_bytes(archive_data)
        package_root, manifest = extract_verified_archive(
            archive_data, expected_sha256, release["version"], update_dir
        )
    except Exception:
        if update_dir is not None:
            shutil.rmtree(update_dir, ignore_errors=True)
        release_update_lock(lock_file)
        raise
    return {
        "from_version": current,
        "to_version": release["version"],
        "tag_name": release["tag_name"],
        "package_root": str(package_root),
        "update_dir": str(update_dir),
        "file_count": len(manifest["files"]),
        "archive_size": len(archive_data),
        "sha256": expected_sha256,
        "lock_file": str(lock_file),
    }


def launch_update_helper(
    prepared: dict,
    target_root: Path,
    settings_dir: Path,
    *,
    parent_pid: int | None = None,
    python_executable: str | None = None,
) -> dict:
    package_root = Path(str(prepared["package_root"])).resolve()
    helper = package_root / "toolkit_updater.py"
    if not helper.is_file():
        raise RuntimeError("已验证更新包缺少更新助手")
    result_file = Path(settings_dir).resolve() / "update-result.json"
    executable = str(python_executable or sys.executable)
    command = [
        executable,
        str(helper),
        "--apply",
        "--target-root",
        str(Path(target_root).resolve()),
        "--package-root",
        str(package_root),
        "--parent-pid",
        str(parent_pid if parent_pid is not None else os.getpid()),
        "--python-executable",
        executable,
        "--result-file",
        str(result_file),
        "--from-version",
        str(prepared["from_version"]),
        "--to-version",
        str(prepared["to_version"]),
        "--lock-file",
        str(prepared.get("lock_file") or ""),
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            command,
            cwd=str(package_root.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except Exception:
        release_update_lock(prepared.get("lock_file"))
        raise
    return {
        "started": True,
        "from_version": prepared["from_version"],
        "to_version": prepared["to_version"],
        "file_count": prepared["file_count"],
        "archive_size": prepared["archive_size"],
        "sha256": prepared["sha256"],
    }


def _wait_for_process(pid: int, timeout_seconds: float = 120.0) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    if os.name == "nt":
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return
        try:
            result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000))
            if result == 0x00000102:
                raise RuntimeError("等待旧版本退出超时")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        time.sleep(0.2)
    raise RuntimeError("等待旧版本退出超时")


def validate_staged_package(package_root: Path, expected_version: str) -> dict:
    package_root = Path(package_root).resolve()
    manifest_path = package_root / MANIFEST_NAME
    manifest = _manifest_from_bytes(manifest_path.read_bytes(), expected_version)
    for relative, expected in manifest["files"].items():
        path = _path_in(package_root, relative)
        if not path.is_file() or path.stat().st_size != expected["size"]:
            raise RuntimeError(f"暂存更新文件缺失或大小不符：{relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
            raise RuntimeError(f"暂存更新文件校验失败：{relative}")
    return manifest


def _replace_from(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + f".update-{uuid.uuid4().hex}.partial")
    try:
        shutil.copy2(source, partial)
        os.replace(partial, destination)
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass


def _write_update_result(path: Path, payload: dict) -> None:
    try:
        _atomic_json(path, {**payload, "finished_at": utc_now()})
    except Exception:
        pass


def _restart_app(python_executable: str, target_root: Path) -> None:
    executable = Path(python_executable)
    app = target_root / "toolkit_webapp.py"
    if not executable.is_file() or not app.is_file():
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(executable), str(app)],
        cwd=str(target_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )


def apply_prepared_update(
    target_root: Path,
    package_root: Path,
    result_file: Path,
    from_version: str,
    to_version: str,
    *,
    parent_pid: int = 0,
    python_executable: str = "",
    lock_file: Path | str | None = None,
    restart: bool = True,
) -> bool:
    """Apply one verified package with per-file backup and full rollback."""
    target_root = Path(target_root).resolve()
    package_root = Path(package_root).resolve()
    result_file = Path(result_file).resolve()
    success = False
    rollback_errors: list[str] = []
    backup_root = package_root.parent / "backup"
    changed_paths: set[str] = set()
    new_paths: set[str] = set()
    old_paths: set[str] = set()
    try:
        manifest = validate_staged_package(package_root, to_version)
        _wait_for_process(parent_pid)
        _ensure_install_root(target_root)
        new_paths = set(manifest["files"])
        old_manifest_path = target_root / MANIFEST_NAME
        if old_manifest_path.is_file():
            old_manifest = _manifest_from_bytes(
                old_manifest_path.read_bytes(), read_current_version(target_root)
            )
            old_paths = set(old_manifest["files"])
        managed_paths = sorted(new_paths | old_paths | {MANIFEST_NAME})
        backup_root.mkdir(parents=True, exist_ok=False)
        for relative in managed_paths:
            current = _path_in(target_root, relative)
            if current.is_dir():
                raise RuntimeError(f"更新目标被同名目录占用：{relative}")
            if current.is_file():
                backup = _path_in(backup_root, relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, backup)

        for relative in sorted(new_paths):
            _replace_from(_path_in(package_root, relative), _path_in(target_root, relative))
            changed_paths.add(relative)
        _replace_from(package_root / MANIFEST_NAME, target_root / MANIFEST_NAME)
        changed_paths.add(MANIFEST_NAME)
        for relative in sorted(old_paths - new_paths):
            stale = _path_in(target_root, relative)
            if stale.is_file():
                stale.unlink()
                changed_paths.add(relative)
        if read_current_version(target_root) != normalize_version(to_version):
            raise RuntimeError("更新完成后的版本回读不一致")
        _write_update_result(
            result_file,
            {
                "ok": True,
                "from_version": normalize_version(from_version),
                "to_version": normalize_version(to_version),
                "file_count": len(new_paths),
                "backup_dir": str(backup_root),
            },
        )
        success = True
    except Exception as exc:
        # Restore every managed file from backup; remove files that did not
        # exist before.  Unmanaged user files are never touched.
        for relative in sorted(changed_paths, reverse=True):
            try:
                target = _path_in(target_root, relative)
                backup = _path_in(backup_root, relative)
                if backup.is_file():
                    _replace_from(backup, target)
                elif target.is_file() and relative in new_paths:
                    target.unlink()
            except Exception as rollback_exc:
                rollback_errors.append(f"{relative}: {rollback_exc}")
        _write_update_result(
            result_file,
            {
                "ok": False,
                "from_version": normalize_version(from_version),
                "to_version": normalize_version(to_version),
                "error": str(exc) + ("；部分文件回滚失败，请从备份恢复，不要继续启动：" + "; ".join(rollback_errors) if rollback_errors else ""),
                "rollback_complete": not rollback_errors,
                "rollback_errors": rollback_errors,
                "backup_dir": str(backup_root) if backup_root.exists() else "",
            },
        )
    finally:
        release_update_lock(lock_file)
        if restart and python_executable and not rollback_errors:
            try:
                _restart_app(python_executable, target_root)
            except Exception:
                pass
    return success


def read_update_result(settings_dir: Path, *, consume: bool = False) -> dict | None:
    path = Path(settings_dir) / "update-result.json"
    result = _load_json(path)
    if consume and result is not None:
        try:
            path.unlink()
        except OSError:
            pass
    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(description="NIMBY Toolkit verified update helper")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--target-root", type=Path)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--from-version", default="0.0.0")
    parser.add_argument("--to-version", default="0.0.0")
    parser.add_argument("--lock-file", default="")
    args = parser.parse_args()
    if not args.apply or not args.target_root or not args.package_root or not args.result_file:
        parser.error("更新助手只能由工具箱内部调用")
    return 0 if apply_prepared_update(
        args.target_root,
        args.package_root,
        args.result_file,
        args.from_version,
        args.to_version,
        parent_pid=args.parent_pid,
        python_executable=args.python_executable,
        lock_file=args.lock_file,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
