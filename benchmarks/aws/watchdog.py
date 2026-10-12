"""Independent compute failsafe. The campaign controller deletes the full stack afterwards."""
from datetime import datetime, timezone
import os


def expired_instances(ec2, campaign, now):
    selected = []
    pages = ec2.get_paginator('describe_instances').paginate(Filters=[
        {'Name': 'tag:FactumDBCampaign', 'Values': [campaign]},
        {'Name': 'tag:ManagedBy', 'Values': ['FactumDBBenchmark']},
        {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']}])
    for page in pages:
        for reservation in page.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                tags = {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
                if tags.get('FactumDBCampaign') != campaign or tags.get('ManagedBy') != 'FactumDBBenchmark':
                    continue
                # Missing/invalid expiration on a campaign-owned machine means terminate, not retain indefinitely.
                try:
                    expires = datetime.fromisoformat(tags.get('ExpiresAt', '').replace('Z', '+00:00'))
                    is_expired = expires.tzinfo is None or expires <= now
                except ValueError:
                    is_expired = True
                if is_expired:
                    selected.append(instance['InstanceId'])
    return selected


def handler(event, context):
    import boto3
    from botocore.exceptions import ClientError
    region = os.environ['AWS_REGION']
    if region != 'ap-southeast-2':
        raise ValueError('Benchmark watchdog must run in Sydney')
    ec2 = boto3.client('ec2', region_name=region)
    now = datetime.now(timezone.utc)
    probe = event.get('probe') is True
    ids = expired_instances(ec2, os.environ['CAMPAIGN'],
                            datetime.max.replace(tzinfo=timezone.utc) if probe else now)
    if probe:
        if not ids:
            raise RuntimeError('No campaign-owned VM available for termination authorization probe')
        try:
            ec2.terminate_instances(InstanceIds=ids, DryRun=True)
        except ClientError as error:
            if error.response['Error']['Code'] == 'DryRunOperation':
                return {'termination_authorized': True, 'instances': ids}
            raise
        raise RuntimeError('Termination dry-run did not return expected DryRunOperation')
    if ids:
        ec2.terminate_instances(InstanceIds=ids)
    return {'terminated': ids, 'checked_utc': now.isoformat()}
