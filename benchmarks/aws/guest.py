"""Run bounded subprocess benchmarks on a disposable guest or in a local smoke check."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import tempfile

import psutil

ROOT = Path(__file__).resolve().parents[2]


def stop_tree(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for item in children:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs([parent, *children], timeout=5)
    except psutil.NoSuchProcess:
        pass
    process.wait(timeout=10)


def measure(command, directory, timeout, cpus, output, name):
    started = time.monotonic()
    samples = []
    timed_out = False
    with (output / f'{name}.stdout').open('w', encoding='utf-8') as stdout, \
            (output / f'{name}.stderr').open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(command, cwd=directory, stdout=stdout, stderr=stderr,
                                   env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        try:
            parent = psutil.Process(process.pid)
            # Apply to the child only; the harness continues to use the guest's normal CPU allocation.
            if cpus:
                allowed = parent.cpu_affinity()
                if len(allowed) < cpus:
                    raise ValueError(f'Requested {cpus} CPUs but only {len(allowed)} are available')
                parent.cpu_affinity(allowed[:cpus])
            while process.poll() is None:
                rss, cpu = 0, 0.0
                try:
                    members = [parent, *parent.children(recursive=True)]
                except psutil.NoSuchProcess:
                    members = []
                for member in members:
                    try:
                        rss += member.memory_info().rss
                        times = member.cpu_times()
                        cpu += times.user + times.system
                    except psutil.NoSuchProcess:
                        pass
                memory = psutil.virtual_memory()
                swap = psutil.swap_memory()
                samples.append({'elapsed_seconds': time.monotonic()-started,
                                'tree_rss_bytes': rss, 'live_tree_cpu_seconds': cpu,
                                'guest_available_bytes': memory.available,
                                'guest_swap_used_bytes': swap.used,
                                'guest_swap_in_bytes': swap.sin, 'guest_swap_out_bytes': swap.sout})
                if time.monotonic()-started >= timeout:
                    timed_out = True
                    stop_tree(process)
                    break
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                stop_tree(process)
    (output / f'{name}.samples.json').write_text(json.dumps(samples), encoding='utf-8')
    return {'name': name, 'command': command, 'cpu_limit': cpus,
            'wall_seconds': time.monotonic()-started, 'exit_code': process.returncode,
            'status': 'timeout' if timed_out else ('passed' if process.returncode == 0 else 'failed'),
            'sampled_peak_tree_rss_bytes': max((s['tree_rss_bytes'] for s in samples), default=None),
            'minimum_guest_available_bytes': min((s['guest_available_bytes'] for s in samples), default=None),
            'samples': len(samples)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'benchmarks/aws/campaign.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/benchmark-results')
    parser.add_argument('--smoke', action='store_true', help='Tiny harness check; not a requirements benchmark')
    parser.add_argument('--skip-correctness', action='store_true',
                        help='Skip full source suite when separately verified on larger guests; retain package checks')
    parser.add_argument('--resources', type=Path, help='Fresh packaged application resources or Ubuntu .deb')
    parser.add_argument('--deadline-utc', help='Absolute VM expiration; leave two minutes for uploading results')
    options = parser.parse_args()
    config = json.loads(options.config.read_text(encoding='utf-8'))
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    fingerprints = {}
    workload_failures = []
    extracted = None
    workload_python = sys.executable
    packaged_backend = None
    report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
              'python': sys.version, 'cpu_description': platform.processor(),
              'logical_cpus': psutil.cpu_count(), 'ram_bytes': psutil.virtual_memory().total,
              'smoke_only': options.smoke, 'revision': None, 'results': results,
              'limits': ['RSS is sampled at 100 ms and sums processes; shared pages can be counted twice.',
                         'CPU samples cover live processes; short-lived children can be missed.',
                         'Desktop UI, native credential dialogs and physical CPU speeds are not measured.']}
    manifest = ROOT / 'benchmark-manifest.json'
    if manifest.is_file():
        report['artifact_manifest'] = json.loads(manifest.read_text(encoding='utf-8'))
        report['revision'] = report['artifact_manifest'].get('revision')
    deadline = time.monotonic() + (30 if options.smoke else 60 * config['max_instance_minutes'] - 900)
    if options.deadline_utc:
        expiration = datetime.fromisoformat(options.deadline_utc.replace('Z', '+00:00'))
        if expiration.tzinfo is None:
            parser.error('Deadline must include a timezone')
        deadline = min(deadline, time.monotonic() + (expiration-datetime.now(timezone.utc)).total_seconds()-120)

    def execute(name, command, directory=ROOT, cpus=None):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Guest campaign deadline reached')
        result = measure(command, directory, min(config['timeout_seconds'], remaining), cpus, output, name)
        results.append(result)
        (output / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if result['status'] != 'passed':
            raise RuntimeError(f'{name}: {result["status"]}; inspect guest logs')

    try:
        if not options.smoke:
            if options.skip_correctness:
                report['correctness_note'] = 'Full source suite skipped for this guest; package checks still run.'
            else:
                execute('correctness', [sys.executable, '-m', 'pytest', '-q', '--strict-markers'], ROOT / 'backend')
            if options.resources is None:
                raise ValueError('Full run requires fresh --resources; source-only runs cannot establish packaged requirements')
            execute('release-source-match', [sys.executable, str(ROOT / 'benchmarks/aws/verify_release.py'), str(options.resources)])
            script = 'check_windows_bundle.py' if os.name == 'nt' else 'check_linux_bundle.py'
            execute('packaged-backend', [sys.executable, str(ROOT / 'scripts' / script), str(options.resources)])
            if os.name == 'nt':
                workload_python = str(options.resources.resolve() / 'runtime/windows/python/python.exe')
                packaged_backend = options.resources.resolve() / 'backend'
            else:
                extracted = tempfile.TemporaryDirectory(prefix='factumdb-measured-release-')
                subprocess.run(['dpkg-deb', '-x', str(options.resources), extracted.name], check=True)
                matches = list(Path(extracted.name).glob('usr/lib/*/runtime/linux/manifest.json'))
                if len(matches) != 1:
                    raise ValueError('Unexpected Linux runtime layout')
                packaged_backend = matches[0].parents[2] / 'backend'
                workload_python = '/usr/bin/python3'
            report['measured_interpreter'] = workload_python
            report['measured_backend'] = str(packaged_backend)
        sizes = [10] if options.smoke else config['sizes']
        limits = [1] if options.smoke else config['cpu_limits']
        for cpus in limits:
            for size in sizes:
                iterations = 1 if options.smoke else config['warmups'] + config['repetitions']
                for iteration in range(iterations):
                    name = f'engine-{size}-cpu{cpus}-run{iteration}'
                    command = [workload_python, str(ROOT / 'benchmarks/aws/workload.py'), '--rows', str(size)]
                    if packaged_backend:
                        command += ['--backend', str(packaged_backend)]
                    try:
                        execute(name, command, cpus=cpus)
                    except RuntimeError as error:
                        workload_failures.append({'name': name, 'error': str(error)})
                        continue
                    result = results[-1]
                    result['warmup'] = not options.smoke and iteration < config['warmups']
                    result['workload'] = json.loads((output / f'{name}.stdout').read_text(encoding='utf-8'))
                    digest = result['workload']['output_sha256']
                    if size in fingerprints and fingerprints[size] != digest:
                        raise RuntimeError(f'Non-repeatable output for {size} rows')
                    fingerprints[size] = digest
        report['status'] = 'partial' if workload_failures else 'passed'
        if workload_failures:
            report['workload_failures'] = workload_failures
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
    finally:
        if extracted:
            extracted.cleanup()
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'summary': str(output / 'summary.json')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
