"""Resume one recorded, owned guest without extending its original expiry."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from controller import commands, wait_until
from prepare import ROOT, package


def main():
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path)
    args = parser.parse_args()
    record = json.loads(args.state.read_text())
    pending = [r for r in record['runs'] if r.get('cleanup') == 'pending']
    if len(pending) != 1 or record['region'] != 'ap-southeast-2':
        raise ValueError('Resume requires exactly one pending Sydney guest')
    run = pending[0]
    expires = datetime.fromisoformat(run['expires_utc'])
    if (expires - datetime.now(timezone.utc)).total_seconds() < 1800:
        raise ValueError('Insufficient time remaining; clean up instead of extending the timer')
    session = boto3.Session(profile_name='factumdb-benchmark', region_name=record['region'])
    settings = Config(retries={'mode':'standard','total_max_attempts':8}, connect_timeout=10,
                      read_timeout=60, request_checksum_calculation='when_required',
                      response_checksum_validation='when_required')
    cfn, ec2, ssm, s3 = [session.client(n, config=settings) for n in
                          ('cloudformation','ec2','ssm','s3')]
    if session.client('sts', config=settings).get_caller_identity()['Account'] != record['project_id']:
        raise ValueError('Project identity mismatch')
    stack = cfn.describe_stacks(StackName=run['stack_id'])['Stacks'][0]
    tags = {t['Key']:t['Value'] for t in stack['Tags']}
    if tags.get('ManagedBy') != 'FactumDBBenchmark' or tags.get('FactumDBCampaign') != run['name']:
        raise ValueError('Stack ownership mismatch')
    outputs = {o['OutputKey']:o['OutputValue'] for o in stack['Outputs']}
    if outputs['InstanceId'] != run['instance_id'] or outputs['Bucket'] != run['bucket']:
        raise ValueError('Recorded resources differ from stack outputs')
    vm = ec2.describe_instances(InstanceIds=[run['instance_id']])['Reservations'][0]['Instances'][0]
    if vm['State']['Name'] != 'running':
        raise ValueError('Owned guest is not running')
    if run.get('command_id'):
        raise ValueError('A command was already submitted; reconcile its results before resuming')
    def save():
        args.state.write_text(json.dumps(record, indent=2, default=str), encoding='utf-8')
    try:
        package(args.state.parent)
        for page in s3.get_paginator('list_multipart_uploads').paginate(Bucket=run['bucket']):
            for upload in page.get('Uploads', []):
                s3.abort_multipart_upload(Bucket=run['bucket'], Key=upload['Key'], UploadId=upload['UploadId'])
        transfer = TransferConfig(max_concurrency=2, multipart_chunksize=16*1024*1024,
                                  preferred_transfer_client='classic')
        native = args.state.parent/'windows-resources.zip' if run['os']=='windows' else ROOT/'dist/linux/FactumDB_0.1.0_amd64.deb'
        for path, key in [(args.state.parent/'harness.zip','input/harness.zip'),(native,'input/application')]:
            print('Uploading:',path.name,flush=True)
            s3.upload_file(str(path),run['bucket'],key,Config=transfer)
        run['native_sha256'] = hashlib.sha256(native.read_bytes()).hexdigest()
        config = json.loads((ROOT/'benchmarks/aws/campaign.json').read_text())
        send = ssm.send_command(InstanceIds=[run['instance_id']],
            DocumentName='AWS-RunPowerShellScript' if run['os']=='windows' else 'AWS-RunShellScript',
            Parameters={'commands':commands(run['os'],run['bucket'],config,run['expires_utc']),
                        'executionTimeout':[str(int((expires-datetime.now(timezone.utc)).total_seconds())-120)]},
            TimeoutSeconds=600,OutputS3BucketName=run['bucket'],OutputS3KeyPrefix='results/ssm')['Command']
        run.update(command_id=send['CommandId'], status='running')
        save()
        print('Remote tests started:',run['name'],flush=True)
        def completed():
            calls=ssm.list_command_invocations(CommandId=run['command_id'],InstanceId=run['instance_id'],Details=True)['CommandInvocations']
            if calls and calls[0]['Status'] in ('Success','Failed','Cancelled','TimedOut','Undeliverable','Terminated'):
                return calls[0]
        result=wait_until(completed,max(1,(expires-datetime.now(timezone.utc)).total_seconds()-120))
        run.update(status=result['Status'],invocation=result)
        print('Remote tests finished:',result['Status'],flush=True)
    except Exception as error:
        run.update(status='error',error=str(error))
        raise
    finally:
        save()
        subprocess.run([sys.executable,str(Path(__file__).with_name('cleanup.py')),str(args.state)],check=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
