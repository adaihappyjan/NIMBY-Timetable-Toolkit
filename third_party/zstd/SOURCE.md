# Zstandard Windows runtime provenance

The Windows portable package includes the official 64-bit Zstandard runtime.

- Project: Zstandard (`facebook/zstd`)
- Version: `v1.5.7`
- Release: <https://github.com/facebook/zstd/releases/tag/v1.5.7>
- Asset: `zstd-v1.5.7-win64.zip`
- Asset URL: <https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-v1.5.7-win64.zip>
- Asset SHA-256: `acb4e8111511749dc7a3ebedca9b04190e37a17afeb73f55d4425dbf0b90fad9`
- Included file: `dll/libzstd.dll`
- DLL SHA-256: `8f07e1112ed283e5cd2798833e9a3c32d8961381bc36da04af57a1b0ca9bd40b`
- DLL architecture: AMD64 (`PE machine 0x8664`)

The release builder refuses to create a package if the DLL checksum or PE
architecture differs. Zstandard is redistributed under its BSD license; see
`LICENSE` in this directory.
