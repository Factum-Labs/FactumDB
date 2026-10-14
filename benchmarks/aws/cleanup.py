"""Recover cleanup from a recorded campaign; verify project and stack ownership first."""
import argparse
import json
from pathlib import Path
import sys
import time

from controller import collect_bucket


def main():
    import boto3
    from botocore.exceptions import ClientError
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path)
    options = parser.parse_args()
    record = json.loads(options.state.read_text(encoding='utf-8'))
    if record['region'] != 'ap-southeast-2':
        raise ValueError('Unexpected Region')
    session = boto3.Session(profile_name='factumdb-benchmark', region_name=record['region'])
    if session.client('sts').get_caller_identity()['Account'] != record['project_id']:
        raise ValueError('Project identity mismatch')
    cfn, ec2, s3 = [session.client(name) for name in ('cloudformation','ec2','s3')]
    for run in record['runs']:
        if not run.get('stack_id') or run.get('cleanup') == 'stack deleted':
            continue
        try:
            stack = cfn.describe_stacks(StackName=run['stack_id'])['Stacks'][0]
        except ClientError as error:
            if error.response['Error']['Code'] == 'ValidationError' and 'does not exist' in str(error):
                run['cleanup'] = 'stack deleted'
                continue
            raise
        tags = {v['Key']:v['Value'] for v in stack.get('Tags',[])}
        if tags.get('ManagedBy') != 'FactumDBBenchmark' or tags.get('FactumDBCampaign') != run['name']:
            raise ValueError('Stack ownership mismatch')
        if stack['StackStatus'] == 'CREATE_IN_PROGRESS':
            print('Waiting for owned stack creation to settle:',run['name'],flush=True)
            for attempt in range(90):
                time.sleep(10)
                stack = cfn.describe_stacks(StackName=run['stack_id'])['Stacks'][0]
                if stack['StackStatus'] != 'CREATE_IN_PROGRESS':
                    break
            else:
                raise TimeoutError('Owned stack creation did not settle before cleanup deadline')
        resources = cfn.list_stack_resources(StackName=run['stack_id'])['StackResourceSummaries']
        ids = {r['LogicalResourceId']:r['PhysicalResourceId'] for r in resources if 'PhysicalResourceId' in r}
        if ids.get('Guest'):
            print('Terminating owned VM:', ids['Guest'], flush=True)
            ec2.terminate_instances(InstanceIds=[ids['Guest']])
            ec2.get_waiter('instance_terminated').wait(InstanceIds=[ids['Guest']],WaiterConfig={'Delay':5,'MaxAttempts':60})
        if ids.get('Artifacts'):
            try:
                collect_bucket(s3, ids['Artifacts'], options.state.parent/run['name'])
            except s3.exceptions.NoSuchBucket:
                pass
        print('Deleting owned stack:',run['name'],flush=True)
        cfn.delete_stack(StackName=run['stack_id'])
        cfn.get_waiter('stack_delete_complete').wait(StackName=run['stack_id'],WaiterConfig={'Delay':5,'MaxAttempts':180})
        run['cleanup']='stack deleted'
        options.state.write_text(json.dumps(record,indent=2,default=str),encoding='utf-8')
        print('Deleted:',run['name'],flush=True)
    options.state.write_text(json.dumps(record,indent=2,default=str),encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
