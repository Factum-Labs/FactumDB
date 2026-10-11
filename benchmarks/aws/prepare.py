"""Offline preparation and packaging; no AWS calls and no resource creation."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from template import build

ROOT = Path(__file__).resolve().parents[2]


def forecast(config, prices):
    rates = {(p['instance'], p['os']): Decimal(p['on_demand'][0]['usd'])
             for p in prices['prices'] if len(p['on_demand']) == 1 and p['on_demand'][0]['unit'] == 'Hrs'}
    hours = Decimal(config['max_instance_minutes']) / 60
    compute = sum(rates[(r['instance_type'], 'Windows' if r['os'] == 'windows' else 'Linux')] * hours
                  for r in config['matrix'])
    # Deliberately conservative allowance, not a price claim; reserve is separate.
    ancillary = Decimal('3.00')
    total = compute + ancillary
    if total > Decimal(config['scheduling_limit_usd']):
        raise ValueError('Campaign forecast exceeds USD 16 scheduling limit')
    return {'compute_max_usd': str(compute), 'ancillary_allowance_usd': str(ancillary),
            'forecast_usd': str(total), 'scheduling_limit_usd': config['scheduling_limit_usd'],
            'cleanup_reserve_usd': config['cleanup_reserve_usd'],
            'note': 'Reprice at launch; allowance is not a billing cap. T3 uses standard credits, avoiding surplus-credit fees.'}


def package(output):
    tracked = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z', '--', 'backend'], cwd=ROOT).decode().split('\0')
    paths = [ROOT / p for p in tracked if p and (Path(p).suffix in ('.py', '.toml')
             or (p.startswith('backend/tests/golden/') and Path(p).suffix == '.json'))
             and p != 'backend/context.md']
    paths += list((ROOT / 'benchmarks/aws').glob('*.py'))
    paths += [ROOT / 'benchmarks/aws/campaign.json', ROOT / 'benchmarks/aws/requirements.txt',
              ROOT / 'scripts/check_windows_bundle.py', ROOT / 'scripts/check_linux_bundle.py']
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = {'revision': revision, 'prepared_utc': datetime.now(timezone.utc).isoformat(),
                'note': 'Manifest hashes identify working-tree content, including uncommitted edits. Rebuild after final application changes.',
                'files': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in paths if p.is_file()}}
    target = output / 'harness.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_file():
                archive.write(path, str(path.relative_to(ROOT)))
        archive.writestr('benchmark-manifest.json', json.dumps(manifest, indent=2))
    (output / 'harness-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (output / 'harness.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/aws-preparation')
    options = parser.parse_args()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / 'benchmarks/aws/campaign.json').read_text(encoding='utf-8'))
    if config['region'] != 'ap-southeast-2' or config['budget_usd'] != 20:
        raise ValueError('Unexpected Region or budget')
    template = json.dumps(build(), indent=2)
    if len(template.encode()) >= 51200:
        raise ValueError('Template exceeds inline CloudFormation limit')
    (output / 'benchmark.template.json').write_text(template, encoding='utf-8')
    prices = json.loads((ROOT / 'benchmarks/aws/prices.json').read_text(encoding='utf-8'))
    estimate = forecast(config, prices)
    (output / 'budget.json').write_text(json.dumps(estimate, indent=2), encoding='utf-8')
    manifest = package(output)
    print(json.dumps({'prepared': str(output), 'revision': manifest['revision'], 'budget': estimate,
                      'resources_created': False}, indent=2))


if __name__ == '__main__':
    main()
