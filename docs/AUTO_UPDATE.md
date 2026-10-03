# Automatic updates

[简体中文](AUTO_UPDATE.zh-CN.md)

Official portable releases have supported in-app updates since v1.5.0.
The updater manages only the extracted application's manifest-listed files.
Game saves, exports, generated mods and preferences in the user configuration
folder are outside its update scope.

## User workflow

1. Startup uses cached release information, checking GitHub when the last online
   check is more than six hours old. The version button can force a check.
2. A newer stable release displays its version, size and release notes.
   Downloading and installation require confirmation.
3. After verification, a separate helper waits for the toolkit to exit, backs up
   managed files, installs the update and reads the version back.
4. Successful installation or complete rollback restarts the toolkit. Incomplete
   rollback does not restart it: retain logs and backups, and extract a complete
   release to recover. The interface distinguishes these outcomes.

Disable startup checks in the update panel if desired; manual checks remain
available. A checkout containing `.git` reports versions but cannot be overwritten
by this updater. Update source checkouts through Git.

## Verification

Every accepted update must satisfy all of the following:

- Metadata comes from this project's latest stable GitHub release. Drafts and
  prereleases are rejected; a 2.0.0 beta announcement is not an update.
- Download URLs belong to this repository's release paths. The portable ZIP and
  `SHA256SUMS.txt` asset names must match the selected tag.
- The tag follows `vMAJOR.MINOR.PATCH` and is newer than the installed version.
- ZIP SHA-256 matches the checksum file; size matches release metadata.
- The archive has one versioned top-level directory. Absolute paths, traversal,
  duplicate paths, symlinks and excessive file counts or unpacked size are rejected.
- `.toolkit-manifest.json` matches the version and covers every other packaged
  file. Each file's size and SHA-256 are checked.
- Required launchers, version data, frontend, backend, updater and compression
  runtime must all be present.

## Installation and recovery

The package is staged in a separate user-configuration subfolder. After the old
process exits, the helper handles only paths listed in the old or new manifest:

- Existing managed files are copied to the update's backup directory.
- New files are copied to same-directory temporary files, then atomically
  replaced. The manifest is replaced last.
- Only previously managed files removed from the new manifest are deleted.
  Unmanaged user files are not scanned or removed.
- A copy, lock, verification or version-readback failure triggers rollback of
  files actually changed. Previously absent files are removed; existing files
  are restored from backup.
- An update result is saved for the next startup to display.

These checks protect against damaged downloads, unsafe paths, mixed packages
and interrupted installation. They do not replace publisher code signing.
Obtain the first installation from the official release page.
