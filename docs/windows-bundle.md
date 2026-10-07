# Build the Windows x64 installer

Run from the repository root on Windows x64 with Node.js, Python 3.11+, Rust's
`x86_64-pc-windows-msvc` toolchain, and Visual Studio 2022 Build Tools installed:

```powershell
npm install
npm --prefix frontend install
npm run bundle:windows
```

The NSIS installer is written to
`src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`.
End users do not install Python, MySQL or Visual C++ separately. WebView2 may
require a download on first installation if Windows does not already supply it.

## Reproducible vendor staging

`scripts/windows-bundle.lock.json` pins versions and SHA-256 hashes for Python
3.13.16, MySQL Community 8.4.11, its matching source archive, ibd2sql revision
`e6e8c380e6060f74e32fc7032bcf479347f1de12`, and the Visual C++ runtime DLLs.
Downloads are cached in `.bundle-cache/`. Staging fails on checksum mismatch.
Generated files in `src-tauri/resources/` and the cache are ignored by Git.

The Visual C++ DLLs come from the licensed Visual Studio redistributable
directory, **not** from Windows System32. The pinned build uses
`14.44.35112/x64/Microsoft.VC143.CRT`. If Build Tools lives elsewhere, set
`FACTUMDB_VC_REDIST_DIR` to that directory. The DLL hashes must match the lock.
Install the matching Build Tools component on new build machines; a different
runtime version is an intentional lock update, not an automatic substitution.

`npm run bundle:windows:prepare` verifies artifacts, replaces the generated
runtime, stages sources, writes `manifest.json` with all runtime file hashes,
and runs `--version` for every tool. For intentional dependency updates only,
edit versions/URLs, review upstream changes and use
`py -3 scripts/prepare_windows_bundle.py --record-lock`; review the resulting
hash changes before distribution. Ordinary builds never rewrite the lock.

MySQL and ibd2sql license texts and complete matching source archives ship in
the installer. MySQL's source archive is roughly 457 MiB and accounts for most
of the installer size. `runtime/windows/THIRD-PARTY-NOTICES.txt` identifies
licenses and source locations. No MySQL server executable or service is bundled.

## Verification

After building, exercise the packaged backend with Python and utility locations
removed from PATH:

```powershell
py -3 scripts/check_windows_bundle.py src-tauri/target/x86_64-pc-windows-msvc/release
```

This checks resource hashes, isolated Python startup, automatic utility paths,
case creation, and persistence across restart. Builder staging also launches
each real utility. Before publishing a release, test the installer on a clean
Windows x64 machine, including WebView2 installation, extraction with known
MySQL evidence and uninstall. The current installer is unsigned.
