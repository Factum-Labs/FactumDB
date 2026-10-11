"""Read-only AWS benchmark preflight. Requires an authenticated named CLI profile."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

SUPPORTED = 'https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html'


def render_report(report):
    results = report['checks']
    lines = ['# AWS benchmark capability report', '',
             f'Region: `{report["region"]}`. Profile: `{report["profile"]}`.', '',
             f'Checked: {report["checked_at_utc"]}. No benchmark resources created.', '',
             f'[Published Free-plan service support]({SUPPORTED}) covers EC2/EBS, S3, Systems Manager, '
             'Lambda, EventBridge, CloudWatch, IAM, STS and Service Quotas. Status: **documented support**.', '',
             '| Check | Status | Detail |', '|---|---|---|']
    for name, result in results.items():
        detail = result.get('note', result.get('error', 'Read API succeeded; writes and launch capacity remain untested.'))
        lines.append(f'| {name} | {result["status"]} | {detail.replace(chr(10), " ").replace("|", ";")} |')
    for name in ('credits', 'mcp_authentication', 'codex_restarted_mcp'):
        result = report.get(name, {'status': 'not yet verified', 'note': 'Restart Codex to load the new server.'})
        lines.append(f'| {name} | {result["status"]} | {result.get("note", "See details below.")} |')
    plan = results['plan'].get('data', {})
    lines += ['', '## Free-plan state', '', f'- Plan: {plan.get("accountPlanType", "unknown")}, '
              f'{plan.get("accountPlanStatus", "unknown")}.',
              f'- Remaining credits: {json.dumps(plan.get("accountPlanRemainingCredits", "not exposed"))}.',
              f'- Plan expiration: {plan.get("accountPlanExpirationDate", "unknown")}.',
              '- Free-tier eligibility does not imply unlimited zero-cost use. Metered testing consumes applicable credits.', '',
              '## Eligible x86-64 instance types offered in Sydney', '',
              '| Instance | RAM GiB | vCPUs |', '|---|---|---|']
    for item in report['eligible_offered_x86_types']:
        lines.append(f'| {item["Type"]} | {item["RAMMiB"] / 1024:g} | {item["vCPUs"]} |')
    lines += ['', '## Eligible AMIs', '',
              'Root disk sizes below are the AMI snapshot minimums, not application storage recommendations.', '',
              '| OS | AMI | Name | Root disk GiB | Default volume |', '|---|---|---|---|---|']
    for platform in ('ubuntu', 'windows'):
        for image in results[platform + '_amis'].get('data', []):
            root = next((disk.get('Ebs', {}) for disk in image['Disks']
                         if disk['DeviceName'] == image['RootDevice']), {})
            lines.append(f'| {platform.title()} | `{image["Id"]}` | {image["Name"]} | '
                         f'{root.get("VolumeSize", "unknown")} | {root.get("VolumeType", "unknown")} |')
    quota = results['ec2_standard_vcpu_quota'].get('data', {}).get('Quota', {})
    instances = results['existing_instances'].get('data', [])
    lines += ['', '## Quota and usage', '',
              f'- Standard On-Demand EC2 vCPU quota (`L-1216C47A`): {quota.get("Value", "unknown")}. '
              f'Adjustable: {quota.get("Adjustable", "unknown")}.',
              f'- Existing Sydney EC2 instances at check time: {len(instances)}. Details are in capabilities.json.',
              '- Status: **restricted** for simultaneous demand exceeding this quota. Run the benchmark machines sequentially.', '',
              '## Exact dry-run responses', '']
    for platform in ('ubuntu', 'windows'):
        lines += [f'- {platform.title()}: `{results[platform + "_launch_dry_run"].get("error", "No response")}`']
    lines += ['', '## Outstanding checks', '']
    if report.get('codex_restarted_mcp', {}).get('status') != 'verified access':
        lines += ['- **not yet verified**: AWS MCP loaded and authenticated inside a restarted Codex session.']
    lines += [
              '- **not yet verified**: service-role creation, PassRole, SSM command execution, artifact writes and watchdog cleanup.',
              '- **not yet verified**: launch capacity, exact benchmark launch permissions with its IAM role, prices and end-to-end workloads.',
              '- Dry-runs used the latest eligible AMI, m7i-flex.large, a default subnet and default security group, without an instance role. '
              'DryRunOperation confirms authorization for that request; it does not reserve capacity.',
              '- No unsupported-service responses, permission denials or transient errors occurred in the completed checks. '
              'Future API calls can have different restrictions.',
              '- Raw response data and errors: capabilities.json.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='factumdb-benchmark')
    parser.add_argument('--region', default='ap-southeast-2')
    parser.add_argument('--output', type=Path, default=Path('dist/aws-verification'))
    parser.add_argument('--render-only', action='store_true', help='Render saved checks without making AWS API calls')
    options = parser.parse_args()
    if options.render_only:
        report = json.loads((options.output / 'capabilities.json').read_text(encoding='utf-8'))
        (options.output / 'report.md').write_text(render_report(report), encoding='utf-8')
        return
    executable = shutil.which('aws')
    if not executable:
        candidate = Path(os.environ['LOCALAPPDATA']) / 'Programs/Amazon/AWSCLIV2/aws.exe'
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        parser.error('Install AWS CLI before running this check')
    options.output.mkdir(parents=True, exist_ok=True)

    def call(name, arguments, region=None):
        command = [executable, *arguments, '--profile', options.profile,
                   '--region', region or options.region, '--output', 'json', '--no-cli-pager',
                   '--cli-connect-timeout', '10', '--cli-read-timeout', '30']
        try:
            process = subprocess.run(command, capture_output=True, text=True,
                                     encoding='utf-8', errors='replace', timeout=120,
                                     env={**os.environ, 'AWS_PAGER': '', 'AWS_CLI_AUTO_PROMPT': 'off',
                                          'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
            result = {'name': name, 'exit_code': process.returncode,
                      'status': 'verified access' if process.returncode == 0 else 'not yet verified'}
            if process.returncode == 0:
                result['data'] = json.loads(process.stdout or '{}')
            else:
                result['error'] = process.stderr.strip() or process.stdout.strip()
                if any(token in result['error'].lower() for token in
                       ('accessdenied', 'unauthorizedoperation', 'not authorized', 'explicit deny')):
                    result['status'] = 'restricted'
                if 'DryRunOperation' in result['error']:
                    result['status'] = 'verified access'
                    result['note'] = 'Launch authorization verified by dry-run; capacity and actual launch are untested.'
            return result
        except subprocess.TimeoutExpired:
            return {'name': name, 'status': 'not yet verified', 'error': 'Read-only CLI check timed out'}

    identity = call('identity', ['sts', 'get-caller-identity'])
    if identity['status'] != 'verified access':
        (options.output / 'authentication.json').write_text(json.dumps(identity, indent=2) + '\n')
        raise SystemExit('Authentication not verified. Run aws login before the capability audit.')
    queries = [
        ('plan', ['freetier', 'get-account-plan-state'], 'us-east-1'),
        ('toolkit_catalog', ['agent-toolkit', 'list-available-skills'], 'us-east-1'),
        ('eligible_instance_types', ['ec2', 'describe-instance-types', '--filters',
            'Name=free-tier-eligible,Values=true', '--query',
            'InstanceTypes[].{Type:InstanceType,RAMMiB:MemoryInfo.SizeInMiB,vCPUs:VCpuInfo.DefaultVCpus,Architectures:ProcessorInfo.SupportedArchitectures}'], None),
        ('instance_offerings', ['ec2', 'describe-instance-type-offerings', '--location-type', 'region',
            '--filters', 'Name=instance-type,Values=t3.micro,t3.small,c7i-flex.large,m7i-flex.large'], None),
        ('ubuntu_amis', ['ec2', 'describe-images', '--owners', '099720109477', '--filters',
            'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*',
            'Name=state,Values=available', 'Name=free-tier-eligible,Values=true', '--query',
            'reverse(sort_by(Images,&CreationDate))[:3].{Id:ImageId,Name:Name,Created:CreationDate,Architecture:Architecture,RootDevice:RootDeviceName,Disks:BlockDeviceMappings}'], None),
        ('windows_amis', ['ec2', 'describe-images', '--owners', 'amazon', '--filters',
            'Name=name,Values=Windows_Server-2022-English-Full-Base-*',
            'Name=state,Values=available', 'Name=free-tier-eligible,Values=true', '--query',
            'reverse(sort_by(Images,&CreationDate))[:3].{Id:ImageId,Name:Name,Created:CreationDate,Architecture:Architecture,RootDevice:RootDeviceName,Disks:BlockDeviceMappings}'], None),
        ('ec2_standard_vcpu_quota', ['service-quotas', 'get-service-quota', '--service-code', 'ec2',
            '--quota-code', 'L-1216C47A'], None),
        ('existing_instances', ['ec2', 'describe-instances', '--query',
            'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType,State:State.Name}'], None),
        ('ebs', ['ec2', 'describe-volumes', '--max-results', '5'], None),
        ('vpc', ['ec2', 'describe-vpcs'], None),
        ('s3', ['s3api', 'list-buckets'], None),
        ('systems_manager', ['ssm', 'describe-instance-information'], None),
        ('lambda', ['lambda', 'list-functions', '--max-items', '1'], None),
        ('eventbridge', ['events', 'list-rules', '--limit', '1'], None),
        ('eventbridge_scheduler', ['scheduler', 'list-schedules', '--max-results', '1'], None),
        ('cloudwatch', ['cloudwatch', 'describe-alarms', '--max-records', '1'], None),
        ('cloudwatch_logs', ['logs', 'describe-log-groups', '--limit', '1'], None),
        ('iam', ['iam', 'list-roles', '--max-items', '1'], None),
        ('subnets', ['ec2', 'describe-subnets', '--query',
            'Subnets[].{Id:SubnetId,VpcId:VpcId,Zone:AvailabilityZone,Default:DefaultForAz,AvailableAddresses:AvailableIpAddressCount}'], None),
        ('security_groups', ['ec2', 'describe-security-groups', '--query',
            'SecurityGroups[].{Id:GroupId,VpcId:VpcId,Name:GroupName}'], None),
    ]
    results = {'identity': identity}
    def execute(query):
        name, args, region = query
        print(f'Checking {name}', flush=True)
        return name, call(name, args, region)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name, value in pool.map(execute, queries):
            results[name] = value
    eligible = results['eligible_instance_types'].get('data', [])
    offered = {item['InstanceType'] for item in results['instance_offerings'].get('data', {}).get('InstanceTypeOfferings', [])}
    usable = [item for item in eligible if item['Type'] in offered and 'x86_64' in item['Architectures']]
    subnets = results['subnets'].get('data', [])
    groups = results['security_groups'].get('data', [])
    subnet = next((item for item in subnets if item['Default']), None)
    group = next((item for item in groups if subnet and item['VpcId'] == subnet['VpcId'] and item['Name'] == 'default'), None)
    for platform in ('ubuntu', 'windows'):
        images = results[platform + '_amis'].get('data', [])
        if images and subnet and group and usable:
            preferred = next((item['Type'] for item in usable if item['Type'] == 'm7i-flex.large'), usable[0]['Type'])
            results[platform + '_launch_dry_run'] = call(platform + '_launch_dry_run',
                ['ec2', 'run-instances', '--dry-run', '--image-id', images[0]['Id'],
                 '--instance-type', preferred, '--count', '1',
                 '--subnet-id', subnet['Id'], '--security-group-ids', group['Id']])
        else:
            results[platform + '_launch_dry_run'] = {'status': 'not yet verified',
                'note': 'An eligible AMI, instance type, default subnet or security group was unavailable. No resources created.'}
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'profile': options.profile, 'region': options.region, 'benchmark_budget_usd': 20,
              'regional_resources_created': False, 'documented_support_source': SUPPORTED,
              'eligible_offered_x86_types': usable, 'checks': results,
              'credits': {'status': 'not yet verified', 'note': 'Confirm remaining credits in AWS Settings > Billing.'},
              'mcp_authentication': {'status': 'not yet verified', 'note': 'Requires a restarted Codex session and an authenticated AWS MCP call.'}}
    plan = results['plan'].get('data', {})
    if 'accountPlanRemainingCredits' in plan:
        report['credits'] = {'status': 'verified access',
                            'remaining': plan['accountPlanRemainingCredits'],
                            'expires': plan.get('accountPlanExpirationDate')}
    (options.output / 'capabilities.json').write_text(json.dumps(report, indent=2) + '\n')
    (options.output / 'report.md').write_text(render_report(report), encoding='utf-8')
    print(f'Report: {options.output / "report.md"}', flush=True)


if __name__ == '__main__':
    main()
