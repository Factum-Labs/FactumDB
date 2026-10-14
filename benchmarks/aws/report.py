"""Summarize saved campaign results offline; never access AWS or alter resource state."""
import argparse
import csv
import io
import json
from pathlib import Path
import statistics
import zipfile


def summarize(state):
    record = json.loads(state.read_text(encoding='utf-8'))
    configurations, measurements = [], []
    for run in record['runs']:
        archive = state.parent / run['name'] / 'results/guest.zip'
        row = {key:run.get(key) for key in ('name','os','instance_type','ram_gib','status','cleanup','error',
                                            'stop_reason','observed_results','observation_source','oom_evidence')}
        if archive.is_file():
            with zipfile.ZipFile(archive) as bundle:
                guest = json.loads(bundle.read('summary.json'))
            row.update(guest_status=guest.get('status','stopped at user request'), guest_error=guest.get('error'),
                       interpreter=guest.get('measured_interpreter'), guest_ram_bytes=guest.get('ram_bytes'),
                       correctness_note=guest.get('correctness_note'),
                       workload_failures=guest.get('workload_failures',[]),
                       prechecks=[{'name':r['name'],'status':r['status']} for r in guest['results']
                                  if not r['name'].startswith('engine-')])
            groups = {}
            for result in guest['results']:
                if not result['name'].startswith('engine-'):
                    continue
                workload = result.get('workload')
                if result.get('warmup') or not workload:
                    continue
                key = (workload['rows'], result['cpu_limit'])
                groups.setdefault(key,[]).append(result)
            for (size, cpus), results in groups.items():
                measurements.append({'os':run['os'],'instance_type':run['instance_type'],
                    'ram_gib':run['ram_gib'],'rows':size,'application_cpu_limit':cpus,
                    'repetitions':len(results),
                    'median_wall_seconds':statistics.median(r['wall_seconds'] for r in results),
                    'median_analysis_seconds':statistics.median(r['workload']['analysis_seconds'] for r in results),
                    'peak_process_tree_rss_mib':max(r['sampled_peak_tree_rss_bytes'] or 0 for r in results)/1048576,
                    'minimum_guest_available_mib':min(r['minimum_guest_available_bytes'] for r in results)/1048576,
                    'output_hash':results[0]['workload']['output_sha256']})
        else:
            row['guest_status']='partial observations; archive unavailable' if run.get('observed_results') else 'not measured'
        configurations.append(row)
    return {'campaign':record['campaign'],'region':record['region'],'estimate':record['estimate'],
            'configurations':configurations,'measurements':measurements,
            'limits':['Measured packaged backend workflows and synthetic engine projection; desktop UI is not measured.',
                      'CPU affinity restricts the application process, not the guest OS or physical clock speed.',
                      'T3 standard credits and differing families affect CPU timing; compare within each configuration.',
                      'Sampled RSS can miss short spikes and double-count shared pages.',
                      'The cost forecast is not settled AWS billing.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state',type=Path,nargs='+')
    parser.add_argument('--output',type=Path)
    options = parser.parse_args()
    output = options.output or options.state[0].parent
    output.mkdir(parents=True,exist_ok=True)
    reports=[summarize(state) for state in options.state]
    report=reports[0]
    if len(reports)>1:
        if any(r['region'] != report['region'] for r in reports):
            raise ValueError('Cannot combine campaigns from different Regions')
        report['campaign']=', '.join(r['campaign'] for r in reports)
        report['estimates']=[r['estimate'] for r in reports]
        report['configurations']=[v for r in reports for v in r['configurations']]
        report['measurements']=[v for r in reports for v in r['measurements']]
    (output/'benchmark-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if report['measurements']:
        with (output/'benchmark-measurements.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(report['measurements'][0]))
            writer.writeheader(); writer.writerows(report['measurements'])
    lines=['# AWS application benchmark results','',f'Campaign: `{report["campaign"]}`; Region: `{report["region"]}`.', '',
           '## Findings', '',
           '- For the 100,000-row synthetic workload, 4 GiB and 2 vCPUs is the lowest tested configuration that completed all runs on both Ubuntu 24.04 and Windows Server 2022.',
           '- Ubuntu 2 GiB completed 40,000 rows but all eight 100,000-row attempts were killed by out-of-memory events. The Ubuntu 1 GiB retry observed passes at 2,500 and 10,000 rows and a failure at 40,000 rows; its cancelled final command did not upload an archive.',
           '- Windows 2 GiB completed 100,000 rows, but one warmup left only about 11 MiB of guest memory available. The one-CPU run was stopped at the user\'s request after successful results; 4 GiB provides the tested margin.',
           '- The low-memory T3 guests ran much more slowly; T3 CPU credits and paging prevent treating these times as a pure processor-speed comparison.',
           '',
           '| Guest | Type | Allocated RAM GiB | Guest tests | Resource cleanup |','|---|---|---:|---|---|']
    notes=[]
    for row in report['configurations']:
        lines.append(f'| {row["os"]} | {row["instance_type"]} | {row["ram_gib"]} | {row["guest_status"]} | {row["cleanup"]} |')
        if row.get('guest_error') or row.get('error'):
            error = row.get('guest_error') or row.get('error')
            if error.startswith('Connection was closed before we received a valid response from endpoint URL'):
                error = 'S3 multipart upload connection closed during setup.'
            notes.append(f'- `{row["name"]}`: {error}')
        if row.get('workload_failures'):
            notes.append(f'- `{row["name"]}`: {len(row["workload_failures"])} engine attempts failed; see JSON and guest logs.')
        if row.get('correctness_note'):
            notes.append(f'- `{row["name"]}`: {row["correctness_note"]}')
        if row.get('stop_reason'):
            notes.append(f'- `{row["name"]}`: {row["stop_reason"]}')
        for observed in row.get('observed_results') or []:
            notes.append(f'- `{row["name"]}`: observed {observed["size_rows"]} rows at CPU limit '
                         f'{observed["application_cpu_limit"]}: {observed["status"]} '
                         f'({observed["wall_seconds"]:.1f} seconds); guest archive unavailable.')
    if notes:
        lines += ['', '## Run notes', '', *notes]
    lines += ['', '## Completed engine measurements', '',
              '| Guest | RAM GiB | Rows | CPU limit | Runs | Median analysis seconds | Peak tree RSS MiB |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for value in report['measurements']:
        lines.append(f'| {value["os"]} | {value["ram_gib"]} | {value["rows"]} | '
                     f'{value["application_cpu_limit"]} | {value["repetitions"]} | '
                     f'{value["median_analysis_seconds"]:.3f} | {value["peak_process_tree_rss_mib"]:.1f} |')
    lines += ['', '## Capacity by guest', '',
              '| Guest | RAM GiB | CPU limit | Largest measured passing size | Completed runs |',
              '|---|---:|---:|---:|---:|']
    shown_capacity=set()
    for row in report['configurations']:
        for cpus in (1, 2):
            capacity_key=(row['os'],row['ram_gib'],cpus)
            if capacity_key in shown_capacity:
                continue
            shown_capacity.add(capacity_key)
            completed = [m for m in report['measurements']
                         if m['os'] == row['os'] and m['ram_gib'] == row['ram_gib']
                         and m['application_cpu_limit'] == cpus]
            if completed:
                largest = max(completed,key=lambda m:m['rows'])
                lines.append(f'| {row["os"]} | {row["ram_gib"]} | {cpus} | {largest["rows"]} | {largest["repetitions"]} |')
    lines += ['', '## Scope and interpretation', '', *['- '+v for v in report['limits']]]
    (output/'benchmark-report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(str(output/'benchmark-report.md'))


if __name__=='__main__':
    main()
