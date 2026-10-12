"""Stage pinned PDF wheels at build time. The installed app never invokes pip."""

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "scripts/pdf-requirements.txt"


def stage_pdf_dependencies(runtime, *, windows=False):
    python_version = (
        "3.13" if windows else f"{sys.version_info.major}.{sys.version_info.minor}"
    )
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    revision = hashlib.sha256(requirements.encode()).hexdigest()[:12]
    wheels = (
        ROOT
        / ".bundle-cache/pdf-wheels"
        / ("windows-" + python_version if windows else "linux-" + python_version)
        / revision
    )
    wheels.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--dest",
        str(wheels),
        "-r",
        str(REQUIREMENTS),
    ]
    if windows:
        command += [
            "--platform",
            "win_amd64",
            "--python-version",
            python_version,
            "--implementation",
            "cp",
        ]
    subprocess.run(command, check=True)
    target = runtime / "python-packages"
    target.resolve().relative_to(runtime.resolve())
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    # Wheels are ordinary zip archives; no installer or pip is needed at runtime.
    for wheel in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.infolist():
                destination = (target / item.filename).resolve()
                destination.relative_to(target.resolve())
                if item.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        archive.open(item) as incoming,
                        destination.open("wb") as outgoing,
                    ):
                        shutil.copyfileobj(incoming, outgoing)
    (target / "factumdb-pdf.json").write_text(
        json.dumps(
            {
                "requirements": requirements,
                "python_version": python_version,
                "wheels": {
                    wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest()
                    for wheel in sorted(wheels.glob("*.whl"))
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
