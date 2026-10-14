"""Reject stale packaged backend source before claiming requirements for a finished revision."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def check(resources, manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
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


def check_deb(path, manifest_path):
    """Stream the Debian ar/tar archive on Windows too; no extraction or execution."""
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {name: digest for name, digest in manifest['files'].items()
                if name.startswith(('backend/core/', 'backend/adapters/', 'backend/sidecar/'))}
    found = set()
    dependencies = None
    with path.open('rb') as source:
        if source.read(8) != b'!<arch>\n':
            raise ValueError('Not a Debian ar archive')
        while header := source.read(60):
            if len(header) != 60 or header[-2:] != b'`\n':
                raise ValueError('Invalid ar member')
            name = header[:16].decode().strip().rstrip('/')
            size = int(header[48:58])
            position = source.tell()
            if name.startswith(('data.tar', 'control.tar')):
                with tarfile.open(fileobj=source, mode='r|*') as archive:
                    for member in archive:
                        if not member.isfile():
                            continue
                        relative = 'backend/' + member.name.split('/backend/', 1)[1] if '/backend/' in member.name else None
                        if relative in expected:
                            stream = archive.extractfile(member)
                            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                            if digest != expected[relative]:
                                raise ValueError(f'Packaged backend differs: {relative}')
                            found.add(relative)
                        elif name.startswith('control.tar') and member.name.lstrip('./') == 'control':
                            dependencies = archive.extractfile(member).read().decode()
            source.seek(position + size + size % 2)
    missing = set(expected) - found
    if missing or not found:
        raise ValueError(f'Installer source missing: {sorted(missing)[:5]}')
    print(f'Ubuntu installer matches {len(found)} current backend source/asset hashes')
    if dependencies:
        print('\n'.join(line for line in dependencies.splitlines() if line.startswith(('Package:', 'Version:', 'Depends:'))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resources', type=Path)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'benchmark-manifest.json')
    options = parser.parse_args()
    if options.resources.suffix == '.deb':
        check_deb(options.resources, options.manifest)
    else:
        check(options.resources.resolve(), options.manifest)


if __name__ == '__main__':
    main()
