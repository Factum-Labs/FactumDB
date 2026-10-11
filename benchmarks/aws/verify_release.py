"""Reject stale packaged backend source before claiming requirements for a finished revision."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def check(resources):
    manifest = json.loads((ROOT / 'benchmark-manifest.json').read_text(encoding='utf-8'))
    checked = 0
    for name, expected in manifest['files'].items():
        if not name.startswith(('backend/core/', 'backend/adapters/', 'backend/sidecar/')):
            continue
        path = resources / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Packaged backend differs from benchmark revision: {name}')
        checked += 1
    if not checked:
        raise ValueError('No backend source hashes found')
    print(f'Packaged backend matches {checked} source hashes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resources', type=Path)
    options = parser.parse_args()
    if options.resources.suffix == '.deb':
        with tempfile.TemporaryDirectory(prefix='factumdb-release-check-') as directory:
            subprocess.run(['dpkg-deb','-x',str(options.resources),directory],check=True)
            candidates = list(Path(directory).glob('usr/lib/*/runtime/linux/manifest.json'))
            if len(candidates) != 1:
                raise ValueError('Unexpected installer resource layout')
            check(candidates[0].parents[2])
    else:
        check(options.resources.resolve())


if __name__ == '__main__':
    main()
