# Linux desktop installer

The Linux bundle targets **Ubuntu 24.04 x86-64** and compatible desktops. It
includes MySQL Community 8.4.11's `innochecksum`, `ibd2sdi`, and `mysqlbinlog`,
and the same pinned ibd2sql revision as the Windows bundle. It installs a desktop
launcher, icons, backend resources, and the FactumDB polkit sign-up policy.
Python 3.11+ and GTK/WebKit libraries are installed through apt dependencies.
No MySQL server or service is installed.

## Install and open

```bash
sudo apt install ./FactumDB_0.1.0_amd64.deb
factumdb
```

You can also open FactumDB from the desktop application menu. A running desktop
polkit authentication agent is needed for initial account sign-up; GNOME and
KDE normally provide one. Case data is stored under
`~/.local/share/lk.ac.uom.factumdb/`. Settings automatically selects bundled
extraction tools, and **Use bundled tools** restores them after overrides.

The package is built on Ubuntu 24.04 and uses its `libaio1t64` library. Earlier
Ubuntu versions, ARM machines, and other distributions are not verified targets.
Tauri recommends building on the oldest distribution you intend to support;
see its [Linux distribution guidance](https://v2.tauri.app/distribute/debian/).

## Build on Ubuntu or Ubuntu WSL

Install Linux Node.js 22.12+ (or 24 LTS), a current Rust toolchain, and:

```bash
sudo apt update
sudo apt install build-essential curl file libwebkit2gtk-4.1-dev \
  libayatana-appindicator3-dev librsvg2-dev patchelf pkg-config libssl-dev \
  libaio1t64 libnuma1 polkitd pkexec
python3 scripts/build_linux_bundle.py
```

Run from the repository root. On Windows with this repository location:

```powershell
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/Users/yasir/Desktop/Projects/FactumDB && python3 scripts/build_linux_bundle.py'
```

Ensure Linux `node`, `npm`, `cargo` and `rustc` are on PATH; Windows executables
exposed through WSL interoperability cannot build a Linux bundle. The build
also recognizes the isolated Node.js and Rust tools provisioned in this session
under `~/.local/share/factumdb-build/`. The build script stages vendor resources,
copies application sources to a dedicated native
Linux build tree under `~/.cache/factumdb/`, installs locked npm dependencies,
and runs Tauri. Windows build artifacts and npm modules are excluded. The
resulting `.deb` installer is checked with the headless bundle check before it
and its SHA-256 file are copied to **`dist/linux/`**
in the original repository. `npm run bundle:linux` invokes the same workflow.

`scripts/linux-bundle.lock.json` pins download hashes. `.bundle-cache/` caches
archives, while generated runtime files live in `src-tauri/resources/runtime/linux/`.
Normal builds reject checksum mismatches. Maintainers can deliberately update
the lock with `python3 scripts/prepare_linux_bundle.py --record-lock`; review
the downloaded sources and hash changes before distributing an update.
MySQL's complete matching source archive, license and build information and
ibd2sql's source/license accompany the utilities. The source archive accounts
for most of the installer size. The native MySQL utilities are patched to use
Ubuntu 24.04's compatible x86-64 `libaio.so.1t64` SONAME and resolve their private
libraries relative to the executable. Tool provenance hashes the actual binaries.

## Headless verification

Install test tools with `sudo apt install python3-pytest xvfb xauth`. The bundle
check extracts the installer and verifies desktop integration, polkit policy,
runtime/source hashes, real tool startup, automatic settings, guarded commands,
password login, case creation and persistence across backend restart:

```bash
python3 scripts/check_linux_bundle.py dist/linux/FactumDB_0.1.0_amd64.deb
# Optional: run all extraction/analysis stages and export using real fixture data.
python3 scripts/check_linux_bundle.py dist/linux/FactumDB_0.1.0_amd64.deb \
  --evidence datasets/attack_lab/subjects/06_clean_marketplace
cd backend
python3 -m pytest
python3 tests/linux_auth_smoke.py --expect-unavailable
```

The bundle check seeds an account directly in its temporary test database to
exercise login without a desktop authentication prompt. This does not modify
the application's sign-up requirements. The native security smoke check verifies
that sign-up fails safely when WSL lacks a desktop authentication agent.

After installing, a virtual-display startup check is possible:

```bash
python3 scripts/check_linux_desktop.py
```

This verifies that the installed application stays running and its rendered
frontend starts the packaged backend through Tauri IPC. It uses isolated
temporary data/config/cache directories. An interactive Linux desktop is required to
verify native credential dialogs, file dialogs and the visual appearance.

Uninstall using `sudo apt remove factum-db`; existing examiner data is retained.

## Verified build

The 2026-10-08 build was installed and checked in Ubuntu 24.04.4 x86-64 WSL:
1,114 backend tests passed (11 platform/optional tests skipped), all 5 native
Rust transport tests passed, and the extracted installer completed every
analysis stage and JSON export on the clean marketplace fixture. Runtime/source
hashes, automatic tool settings, login/logout, case persistence across restart,
the installed polkit policy, and desktop startup with renderer-to-backend IPC
under Xvfb passed. Interactive credential/file dialogs still require a desktop
session. The installer is approximately 579 MB, including corresponding sources.
