# Team setup after pulling changes

Pulling updates the source code only. Installers, bundled tools, dependencies,
and build outputs are ignored by Git. To use the updated application, run it
from source or install an installer freshly built from the updated `main`.

## 1. Update an existing checkout

Save or commit your current work first, then run:

```bash
git switch main
git pull --ff-only origin main
```

Run the development and build commands below from the repository root.

## 2. Development on Windows x64

Install these prerequisites once:

- Node.js 22.12 or newer, with npm.
- Python 3.11 or newer, with the Windows Python launcher (`py`).
- Rust with the `x86_64-pc-windows-msvc` toolchain.
- Visual Studio 2022 Build Tools with C++ support and a Windows SDK.
- Microsoft Edge WebView2 Runtime.

Install the locked dependencies, stage the bundled tools, and start the desktop:

```powershell
npm ci
npm --prefix frontend ci
npm run bundle:windows:prepare
npm run tauri:dev
```

The preparation step downloads and verifies the pinned Python interpreter,
MySQL extraction utilities, ibd2sql, and corresponding sources. It also needs
the Visual Studio C++ redistributable DLLs. If the redistributable directory
differs from the default, set `FACTUMDB_VC_REDIST_DIR` to its location before
preparing. The DLLs must match the pinned versions; see
[Windows bundling](windows-bundle.md) for details.

Configure Windows Hello in Windows Settings before creating a FactumDB
account. Sign-up uses the native Windows Hello prompt.

Use `npm run tauri:dev` for the working application. Running the frontend alone
does not provide the desktop backend. Tauri starts the Python backend
automatically; application operation requires no third-party Python packages.

After later pulls, stop the app, rerun both `npm ci` commands, and restart
`npm run tauri:dev`. Rerun `npm run bundle:windows:prepare` when the vendor lock
or staging script changes, or generated runtime resources are missing.

## 3. Development on Ubuntu 24.04 x86-64

Install native Linux Node.js 22.12 or newer, Rust, and Python 3.11 or newer.
Install the platform dependencies:

```bash
sudo apt update
sudo apt install build-essential curl file libwebkit2gtk-4.1-dev \
  libayatana-appindicator3-dev librsvg2-dev patchelf pkg-config libssl-dev \
  libaio1t64 libnuma1 polkitd pkexec
```

Install the locked dependencies and prepare the extraction tools:

```bash
npm ci
npm --prefix frontend ci
python3 scripts/prepare_linux_bundle.py
```

Install the sign-up policy once, then start the desktop app:

```bash
sudo install -m 0644 backend/adapters/security/org.factumdb.signup.policy \
  /usr/share/polkit-1/actions/org.factumdb.signup.policy

npm run tauri:dev
```

Account creation requires a running desktop polkit authentication agent.
Default WSL sessions may lack an active desktop session and authentication
agent, so native sign-up may be unavailable there. Use Linux versions of Node,
npm, Cargo, and Rust when working in WSL.

After later pulls, stop the app, rerun both `npm ci` commands, and restart
`npm run tauri:dev`. Rerun the Linux preparation step when the vendor lock or
staging script changes, and reinstall the policy if its contents change.

See [Linux bundling](linux-bundle.md) and
[Local examiner accounts](authentication.md) for platform details.

## 4. Using installers

Installer users do not need a repository checkout or development toolchain.
A teammate responsible for packaging should build from the updated `main`
and share the resulting installer. Existing installer files are not refreshed
by `git pull`.

### Windows

Run `FactumDB_0.1.0_x64-setup.exe` and follow the installation wizard.
Python, the extraction tools, and the Visual C++ runtime are included.
The installer may download WebView2 if it is missing.

### Ubuntu 24.04 x86-64

From the directory containing the downloaded installer:

```bash
sudo apt install ./FactumDB_0.1.0_amd64.deb
factumdb
```

APT installs the declared Python and desktop dependencies. The installer
includes the extraction tools and installs the polkit sign-up policy.
An active desktop authentication agent is still required for sign-up.

### First use on either platform

1. Open FactumDB and create your own local account. Use a password of at least
   12 characters and complete the native device verification prompt.
2. Sign in under the same OS account used for registration.
3. Check **Settings** for the bundled extraction tool paths. Use
   **Use bundled tools** to restore them after custom overrides.
4. Create a case, register evidence, and complete the analysis pipeline.
5. Export the completed results to a new JSON file or CSV folder.

Accounts and case data are local to the application data directory; pulling
the repository does not download another teammate's accounts or cases.

## 5. Building fresh installers for the team

### Windows

With the Windows development prerequisites installed:

```powershell
npm ci
npm --prefix frontend ci
npm run bundle:windows
```

The installer is written to:

```text
src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/FactumDB_0.1.0_x64-setup.exe
```

### Linux or Ubuntu WSL

With the Linux build prerequisites installed:

```bash
python3 scripts/build_linux_bundle.py
```

The script installs locked npm dependencies in a separate native Linux build
workspace, builds and checks the Debian package, and copies these files into
the original repository:

```text
dist/linux/FactumDB_0.1.0_amd64.deb
dist/linux/FactumDB_0.1.0_amd64.deb.sha256
```

Share the installer and, for Linux, its checksum file. These generated files
are ignored by Git and must be distributed separately. The version remains
`0.1.0`, so identify shared builds by their source commit as well as filename
to distinguish updated installers from older ones.

## Further instructions

- [Desktop setup and workflow](desktop-runtime.md)
- [Local examiner accounts](authentication.md)
- [Windows installer build and verification](windows-bundle.md)
- [Linux installer build and verification](linux-bundle.md)
