from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZSTD_DLL_SHA256 = "8f07e1112ed283e5cd2798833e9a3c32d8961381bc36da04af57a1b0ca9bd40b"
PE_MACHINE_AMD64 = 0x8664
FIXED_FILES = (
    "启动工具箱.cmd",
    "launcher.bat",
    "README.md",
    "LICENSE",
    "NOTICE",
    "requirements.txt",
    "libzstd.dll",
)
DIRECTORIES = ("web", "docs", "third_party")
FORBIDDEN_SUFFIXES = {".vbs", ".ps1", ".lnk", ".exe", ".msi"}


def validate_zstd_runtime(path: Path) -> None:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != ZSTD_DLL_SHA256:
        raise RuntimeError(
            f"libzstd.dll SHA-256 不匹配：期望 {ZSTD_DLL_SHA256}，实际 {digest}"
        )
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise RuntimeError("libzstd.dll 不是有效的 Windows PE 文件")
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    if pe_offset + 6 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise RuntimeError("libzstd.dll 的 PE 头无效")
    machine = int.from_bytes(data[pe_offset + 4:pe_offset + 6], "little")
    if machine != PE_MACHINE_AMD64:
        raise RuntimeError(
            f"libzstd.dll 不是 AMD64 运行库：PE machine=0x{machine:04x}"
        )


def portable_files(root: Path = ROOT) -> list[Path]:
    files = [root / name for name in FIXED_FILES]
    files.extend(sorted(root.glob("toolkit_*.py")))
    for directory in DIRECTORIES:
        files.extend(path for path in sorted((root / directory).rglob("*")) if path.is_file())
    missing = [str(path.relative_to(root)) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"便携包缺少必要文件：{', '.join(missing)}")
    validate_zstd_runtime(root / "libzstd.dll")
    forbidden = [str(path.relative_to(root)) for path in files if path.suffix.lower() in FORBIDDEN_SUFFIXES]
    if forbidden:
        raise RuntimeError(f"便携包包含高风险或不便携入口：{', '.join(forbidden)}")
    return files


def build_portable(version: str, output_dir: Path, root: Path = ROOT) -> tuple[Path, Path]:
    clean_version = version.strip() or "dev"
    folder_name = f"NIMBY-Timetable-Toolkit-{clean_version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"NIMBY-Timetable-Toolkit-portable-{clean_version}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in portable_files(root):
            relative = path.relative_to(root)
            archive.write(path, Path(folder_name) / relative)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = output_dir / "SHA256SUMS.txt"
    checksum_path.write_text(f"{digest} *{archive_path.name}\n", encoding="utf-8", newline="\n")
    return archive_path, checksum_path


def main() -> None:
    parser = argparse.ArgumentParser(description="构建不含 VBS/PowerShell/快捷方式的 Windows 便携发布包")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    archive, checksum = build_portable(args.version, args.output.resolve())
    print(archive)
    print(checksum)


if __name__ == "__main__":
    main()
