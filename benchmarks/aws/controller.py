"""Later-run controller: sequential test stacks, bounded spend, SSM execution and finally cleanup.

Default invocation is offline preparation. Only --execute creates AWS resources.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile

from prepare import ROOT, forecast, package
from template import build


def wait_until(check, timeout, delay=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(delay)
    raise TimeoutError('AWS operation exceeded its bounded wait')


def collect_bucket(s3, bucket, destination):
    """Save all result objects, then empty this explicitly stack-owned unversioned bucket."""
    objects = [item for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket)
               for item in page.get('Contents', [])]
    for item in objects:
        key = item['Key']
        if key.startswith('results/'):
            target = (destination / key).resolve()
            target.relative_to(destination.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(target))
    for start in range(0, len(objects), 1000):
        response = s3.delete_objects(Bucket=bucket, Delete={
            'Objects': [{'Key': item['Key']} for item in objects[start:start+1000]], 'Quiet': True})
        if response.get('Errors'):
            raise RuntimeError(f'Artifact deletion failed: {response["Errors"]}')
    for page in s3.get_paginator('list_multipart_uploads').paginate(Bucket=bucket):
        for upload in page.get('Uploads', []):
            s3.abort_multipart_upload(Bucket=bucket, Key=upload['Key'], UploadId=upload['UploadId'])


def zip_resources(source, target):
    source = source.resolve()
    for directory in ('runtime/windows', 'sources'):
        if not (source / directory).is_dir():
            raise ValueError(f'Missing packaged resources: {directory}')
    # Tauri maps ../backend into the installed resource directory at bundle time;
    # src-tauri/resources itself can therefore contain only runtime and sources.
    backend = source / 'backend' if (source / 'backend').is_dir() else ROOT / 'backend'
    # If an installed/staged backend is supplied, reject stale source.
    for directory in ('core', 'adapters', 'sidecar'):
        for path in (ROOT / 'backend' / directory).rglob('*.py'):
            relative = path.relative_to(ROOT / 'backend')
            packaged = backend / relative
            if not packaged.is_file() or packaged.read_bytes() != path.read_bytes():
                raise ValueError(f'Windows package is stale: {relative}')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for directory in ('runtime/windows', 'sources'):
            for path in (source / directory).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    path.resolve().relative_to(source)
                    archive.write(path, str(path.relative_to(source)))
        for directory in ('core', 'adapters', 'sidecar'):
            for path in (backend / directory).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    path.resolve().relative_to(backend.resolve())
                    archive.write(path, 'backend/' + str(path.relative_to(backend)))


def commands(os_name, harness_url, native_url, config, results_url, expires):
    """Commands run only on the newly created guest through SSM."""
    if os_name == 'ubuntu':
        return [
            'set -eu', 'mkdir -p /opt/factumdb-benchmark', 'cd /opt/factumdb-benchmark',
            'apt-get update -qq', 'DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv unzip libaio1t64 libnuma1',
            f'curl --fail --location {json.dumps(harness_url)} --output harness.zip',
            'unzip -q -o harness.zip', f'curl --fail --location {json.dumps(native_url)} --output application.deb',
            'python3 -m venv .venv', '.venv/bin/python -m pip install -r benchmarks/aws/requirements.txt',
            # Preserve output even when the tests fail; the SSM command itself records the failure code.
            'set +e', f'.venv/bin/python benchmarks/aws/guest.py --resources application.deb --output results --deadline-utc {json.dumps(expires)}',
            'result=$?',
            f'.venv/bin/python benchmarks/aws/upload_results.py {json.dumps(results_url)} || exit 90',
            'cat results/summary.json', 'exit "$result"']
    return [
        "$ErrorActionPreference = 'Stop'", "$ProgressPreference = 'SilentlyContinue'",
        r"New-Item -ItemType Directory -Force C:\FactumDBBenchmark | Out-Null", r"Set-Location C:\FactumDBBenchmark",
        # Use a separate test interpreter; never alter the application's embedded runtime.
        "Invoke-WebRequest https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe -OutFile python-installer.exe",
        r"if ((Get-AuthenticodeSignature .\python-installer.exe).Status -ne 'Valid') { throw 'Python installer signature invalid' }",
        r"Start-Process .\python-installer.exe -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_test=0' -Wait -WindowStyle Hidden",
        f"Invoke-WebRequest '{harness_url}' -OutFile harness.zip", "Expand-Archive harness.zip -DestinationPath . -Force",
        f"Invoke-WebRequest '{native_url}' -OutFile application.zip", "Expand-Archive application.zip -DestinationPath application -Force",
        r"$python = 'C:\Program Files\Python311\python.exe'",
        "& $python -m pip install -r benchmarks/aws/requirements.txt",
        "if ($LASTEXITCODE -ne 0) { throw 'Harness dependencies failed' }",
        f"& $python benchmarks/aws/guest.py --resources application --output results --deadline-utc '{expires}'",
        "$result = $LASTEXITCODE",
        f"& $python benchmarks/aws/upload_results.py '{results_url}'",
        "if ($LASTEXITCODE -ne 0) { throw 'Result archive upload failed' }",
        "Get-Content results/summary.json -Raw", "exit $result"]


def execute(options):
    import boto3
    from botocore.config import Config
    config = json.loads((ROOT / 'benchmarks/aws/campaign.json').read_text(encoding='utf-8'))
    if config['region'] != 'ap-southeast-2' or config['budget_usd'] != 20:
        raise ValueError('Region/budget differs from the authorized campaign')
    if not options.ubuntu_deb or not options.windows_resources:
        raise ValueError('Supply freshly built --ubuntu-deb and --windows-resources before launch')
    if not options.ubuntu_deb.is_file():
        raise ValueError('Ubuntu installer does not exist')
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'campaign-state.json').exists():
        raise ValueError('Campaign state already exists; reconcile/clean up that campaign before starting another')
    package(output)
    zip_resources(options.windows_resources, output / 'windows-resources.zip')
    session = boto3.Session(profile_name=config['profile'], region_name=config['region'])
    settings = Config(retries={'mode': 'standard', 'total_max_attempts': 3}, connect_timeout=10, read_timeout=30)
    clients = {name: session.client(name, config=settings) for name in
               ('ec2', 's3', 'ssm', 'lambda', 'cloudformation', 'sts', 'service-quotas')}
    ec2, s3, ssm, lam, cfn = [clients[n] for n in ('ec2', 's3', 'ssm', 'lambda', 'cloudformation')]
    plan = session.client('freetier', region_name='us-east-1', config=settings).get_account_plan_state()
    if plan['accountPlanType'] != 'FREE' or plan['accountPlanStatus'] != 'ACTIVE':
        raise ValueError('Free-plan status changed; reverify before launching')
    if float(plan['accountPlanRemainingCredits']['amount']) < config['budget_usd']:
        raise ValueError('Insufficient credits for the authorized campaign budget')
    identity = clients['sts'].get_caller_identity()
    previous = ROOT / 'dist/aws-verification/capabilities.json'
    if not previous.is_file() or json.loads(previous.read_text())['checks']['identity']['data']['Account'] != identity['Account']:
        raise ValueError('Project identity differs from verified integration; reverify through AWS MCP')
    # Refresh prices rather than trusting yesterday's snapshot.
    pricing = session.client('pricing', region_name='us-east-1', config=settings)
    prices = []
    for row in config['matrix']:
        os_name = 'Windows' if row['os'] == 'windows' else 'Linux'
        response = pricing.get_products(ServiceCode='AmazonEC2', Filters=[
            {'Type': 'TERM_MATCH', 'Field': k, 'Value': v} for k, v in {
                'regionCode': config['region'], 'instanceType': row['instance_type'],
                'operatingSystem': os_name, 'tenancy': 'Shared', 'preInstalledSw': 'NA',
                'capacitystatus': 'Used', 'operation': 'RunInstances:0002' if os_name == 'Windows' else 'RunInstances'}.items()])
        if response.get('NextToken'):
            raise ValueError('Unexpected price pagination; reverify price selection')
        rates = [d for raw in response['PriceList'] for product in [json.loads(raw)]
                 for term in product['terms'].get('OnDemand', {}).values() for d in term['priceDimensions'].values()]
        if len(rates) != 1 or rates[0]['unit'] != 'Hrs':
            raise ValueError('Price selection ambiguous')
        prices.append({'instance': row['instance_type'], 'os': os_name,
                       'on_demand': [{'unit': 'Hrs', 'usd': rates[0]['pricePerUnit']['USD']}]})
    estimate = forecast(config, {'prices': prices})
    template = json.dumps(build())
    cfn.validate_template(TemplateBody=template)
    subnets = [s for page in ec2.get_paginator('describe_subnets').paginate()
               for s in page['Subnets'] if s.get('DefaultForAz') and s.get('AvailableIpAddressCount', 0) > 4]
    if not subnets:
        raise ValueError('No usable default subnet; prepare explicit networking before tests')
    subnet = subnets[0]
    route_tables = ec2.describe_route_tables(Filters=[{'Name':'vpc-id','Values':[subnet['VpcId']]}])['RouteTables']
    table = next((t for t in route_tables if any(a.get('SubnetId') == subnet['SubnetId'] for a in t['Associations'])), None)
    table = table or next((t for t in route_tables if any(a.get('Main') for a in t['Associations'])), None)
    if not table or not any(r.get('DestinationCidrBlock') == '0.0.0.0/0' and r.get('GatewayId', '').startswith('igw-')
                            for r in table['Routes']):
        raise ValueError('Selected subnet lacks an internet gateway route for SSM/bootstrap')
    campaign = 'factumdb-' + uuid.uuid4().hex[:12]
    record = {'campaign': campaign, 'project_id': identity['Account'], 'region': config['region'],
              'estimate': estimate, 'runs': [], 'resources_created': False}
    record_path = output / 'campaign-state.json'
    def save():
        record_path.write_text(json.dumps(record, indent=2, default=str), encoding='utf-8')
    save()
    for index, row in enumerate(config['matrix']):
        name = f'{campaign}-{index}-{row["os"]}'
        run = {'name': name, **row, 'status': 'preflight', 'cleanup': 'pending'}
        record['runs'].append(run)
        save()
        # Current quota and inventory are rechecked before each machine, not just once per campaign.
        quota = clients['service-quotas'].get_service_quota(
            ServiceCode='ec2', QuotaCode='L-1216C47A')['Quota']['Value']
        active = [i for page in ec2.get_paginator('describe_instances').paginate(Filters=[
            {'Name':'instance-state-name','Values':['pending','running','stopping','stopped']}])
            for r in page['Reservations'] for i in r['Instances']]
        if active or quota < 2:
            raise ValueError('Sydney has existing instances or insufficient quota; reverify available capacity')
        pattern = 'Windows_Server-2022-English-Full-Base-*' if row['os'] == 'windows' else 'ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*'
        images = ec2.describe_images(Owners=['amazon' if row['os'] == 'windows' else '099720109477'],
            Filters=[{'Name':'name','Values':[pattern]}, {'Name':'state','Values':['available']},
                     {'Name':'free-tier-eligible','Values':['true']}])['Images']
        if not images:
            raise ValueError('No eligible current AMI')
        image = max(images, key=lambda i: i['CreationDate'])
        eligible = ec2.describe_instance_types(InstanceTypes=[row['instance_type']])['InstanceTypes'][0]
        if not eligible.get('FreeTierEligible') or eligible['MemoryInfo']['SizeInMiB'] != row['ram_gib'] * 1024:
            raise ValueError('Instance eligibility or RAM changed')
        expires = datetime.now(timezone.utc) + timedelta(minutes=config['max_instance_minutes'])
        run.update(ami=image['ImageId'], expires_utc=expires.isoformat())
        params = {'Campaign': name, 'ExpiresAt': expires.isoformat(), 'GuestOS': row['os'],
                  'InstanceType': row['instance_type'], 'ImageId': image['ImageId'],
                  'VpcId': subnet['VpcId'], 'SubnetId': subnet['SubnetId']}
        stack_id, bucket, instance = None, None, None
        try:
            stack_id = cfn.create_stack(StackName=name, TemplateBody=template,
                Parameters=[{'ParameterKey': k, 'ParameterValue': v} for k, v in params.items()],
                Capabilities=['CAPABILITY_IAM'], TimeoutInMinutes=15,
                Tags=[{'Key':'ManagedBy','Value':'FactumDBBenchmark'}, {'Key':'FactumDBCampaign','Value':name}])['StackId']
            record['resources_created'] = True
            run['stack_id'] = stack_id
            save()
            cfn.get_waiter('stack_create_complete').wait(StackName=stack_id, WaiterConfig={'Delay':10,'MaxAttempts':90})
            outputs = {i['OutputKey']: i['OutputValue'] for i in cfn.describe_stacks(StackName=stack_id)['Stacks'][0]['Outputs']}
            bucket, instance = outputs['Bucket'], outputs['InstanceId']
            run.update(bucket=bucket, instance_id=instance, watchdog=outputs['WatchdogFunction'])
            save()
            # Invocation verifies service-role read access. Termination authorization is verified by EC2 dry-run below.
            probe = lam.invoke(FunctionName=outputs['WatchdogFunction'], Payload=b'{"probe":true}')
            with probe['Payload'] as stream:
                response = json.loads(stream.read())
            if probe.get('FunctionError') or not response.get('termination_authorized'):
                raise RuntimeError(f'Watchdog probe failed: {response}')
            ec2.describe_instances(InstanceIds=[instance])
            wait_until(lambda: ssm.describe_instance_information(Filters=[{'Key':'InstanceIds','Values':[instance]}])['InstanceInformationList'], 600)
            s3.upload_file(str(output / 'harness.zip'), bucket, 'input/harness.zip')
            native = options.ubuntu_deb if row['os'] == 'ubuntu' else output / 'windows-resources.zip'
            s3.upload_file(str(native), bucket, 'input/application')
            urls = [s3.generate_presigned_url('get_object', Params={'Bucket':bucket,'Key':key}, ExpiresIn=5400)
                    for key in ('input/harness.zip','input/application')]
            results_url = s3.generate_presigned_url('put_object',
                Params={'Bucket':bucket,'Key':'results/guest.zip'}, ExpiresIn=5400)
            run['native_sha256'] = hashlib.sha256(native.read_bytes()).hexdigest()
            send = ssm.send_command(InstanceIds=[instance],
                DocumentName='AWS-RunPowerShellScript' if row['os']=='windows' else 'AWS-RunShellScript',
                Parameters={'commands': commands(row['os'], *urls, config, results_url, expires.isoformat()), 'executionTimeout':['4500']},
                TimeoutSeconds=600, OutputS3BucketName=bucket, OutputS3KeyPrefix='results/ssm')['Command']
            run['command_id'] = send['CommandId']
            run['status'] = 'running'
            save()
            def completed():
                calls = ssm.list_command_invocations(CommandId=send['CommandId'], InstanceId=instance, Details=True)['CommandInvocations']
                if calls and calls[0]['Status'] in ('Success','Failed','Cancelled','TimedOut','Undeliverable','Terminated'):
                    return calls[0]
                return None
            invocation = wait_until(completed, max(1, (expires-datetime.now(timezone.utc)).total_seconds()-120))
            run['status'] = invocation['Status']
            run['invocation'] = invocation
        except Exception as error:
            run['status'] = 'error'
            run['error'] = str(error)
        finally:
            if stack_id:
                try:
                    # Resolve stack resources even when creation/outputs failed.
                    owned = cfn.list_stack_resources(StackName=stack_id)['StackResourceSummaries']
                    bucket = bucket or next((r['PhysicalResourceId'] for r in owned
                                             if r['LogicalResourceId']=='Artifacts' and 'PhysicalResourceId' in r), None)
                    instance = instance or next((r['PhysicalResourceId'] for r in owned
                                                  if r['LogicalResourceId']=='Guest' and 'PhysicalResourceId' in r), None)
                    if instance:
                        ec2.terminate_instances(InstanceIds=[instance])
                        ec2.get_waiter('instance_terminated').wait(InstanceIds=[instance], WaiterConfig={'Delay':5,'MaxAttempts':60})
                    if bucket:
                        try:
                            collect_bucket(s3, bucket, output / name)
                        except s3.exceptions.NoSuchBucket:
                            pass  # Rollback may already have removed the empty bucket.
                    cfn.delete_stack(StackName=stack_id)
                    cfn.get_waiter('stack_delete_complete').wait(StackName=stack_id, WaiterConfig={'Delay':10,'MaxAttempts':90})
                    run['cleanup'] = 'stack deleted'
                except Exception as error:
                    run['cleanup'] = 'failed'
                    run['cleanup_error'] = str(error)
            else:
                run['cleanup'] = 'nothing created'
            save()
        if run['cleanup'] == 'failed':
            raise RuntimeError('Cleanup failed; stop campaign and reconcile campaign-state.json through AWS MCP')
    print(json.dumps({'campaign_state':str(record_path), 'runs':len(record['runs']), 'cleanup':'completed'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--ubuntu-deb', type=Path)
    parser.add_argument('--windows-resources', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/aws-campaign')
    options = parser.parse_args()
    if not options.execute:
        subprocess.run([sys.executable, str(Path(__file__).with_name('prepare.py')), '--output', str(options.output)], check=True)
        return 0
    try:
        execute(options)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
