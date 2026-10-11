"""Build one disposable VM stack; this module never calls AWS."""
from pathlib import Path


def ref(name):
    return {'Ref': name}


def sub(value):
    return {'Fn::Sub': value}


def attr(name, key):
    return {'Fn::GetAtt': [name, key]}


def resource(kind, properties, why, must=(), **extra):
    return {'Type': kind, 'Metadata': {'com.aws.cloudformation.Context':
            {'why': why, 'must': list(must)}}, 'Properties': properties, **extra}


def trust(service):
    return {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
            'Principal': {'Service': service}, 'Action': 'sts:AssumeRole'}]}


def build():
    tags = [{'Key': 'ManagedBy', 'Value': 'FactumDBBenchmark'},
            {'Key': 'FactumDBCampaign', 'Value': ref('Campaign')},
            {'Key': 'ExpiresAt', 'Value': ref('ExpiresAt')}]
    watchdog = Path(__file__).with_name('watchdog.py').read_text(encoding='utf-8')
    resources = {}
    resources['Artifacts'] = resource('AWS::S3::Bucket', {
        'PublicAccessBlockConfiguration': {key: True for key in
            ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')},
        'BucketEncryption': {'ServerSideEncryptionConfiguration': [
            {'ServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]},
        'OwnershipControls': {'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]},
        'LifecycleConfiguration': {'Rules': [{'Id': 'ExpireTemporaryArtifacts', 'Status': 'Enabled',
                                             'ExpirationInDays': 1,
                                             'AbortIncompleteMultipartUpload': {'DaysAfterInitiation': 1}}]},
        'Tags': tags}, 'Disposable synthetic artifacts; versioning intentionally omitted to simplify complete removal.',
        ['Private, encrypted; copy results locally before deletion; empty before DeleteStack'],
        DeletionPolicy='Delete', UpdateReplacePolicy='Delete')
    resources['ArtifactPolicy'] = resource('AWS::S3::BucketPolicy', {
        'Bucket': ref('Artifacts'), 'PolicyDocument': {'Version': '2012-10-17', 'Statement': [{
            'Effect': 'Deny', 'Principal': '*', 'Action': 's3:*',
            'Resource': [attr('Artifacts', 'Arn'), sub('${Artifacts.Arn}/*')],
            'Condition': {'Bool': {'aws:SecureTransport': 'false'}}}]}},
        'Require TLS for artifacts and results.', ['No public or unencrypted transport'])
    resources['GuestRole'] = resource('AWS::IAM::Role', {
        'AssumeRolePolicyDocument': trust('ec2.amazonaws.com'),
        'ManagedPolicyArns': [sub('arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore')],
        'Policies': [{'PolicyName': 'CampaignArtifacts', 'PolicyDocument': {
            'Version': '2012-10-17', 'Statement': [
                {'Effect': 'Allow', 'Action': ['s3:GetObject'], 'Resource': sub('${Artifacts.Arn}/input/*')},
                {'Effect': 'Allow', 'Action': ['s3:PutObject'], 'Resource': sub('${Artifacts.Arn}/results/*')} ]}}],
        'Tags': tags}, 'SSM remote execution without SSH/RDP; read input and write results only.',
        ['Never assign to human team members; no access to other buckets'])
    resources['GuestProfile'] = resource('AWS::IAM::InstanceProfile', {'Roles': [ref('GuestRole')]},
                                       'Attach the disposable guest service role.')
    resources['GuestSecurityGroup'] = resource('AWS::EC2::SecurityGroup', {
        'GroupDescription': 'No inbound management; outbound web for SSM and tool installation',
        'VpcId': ref('VpcId'), 'SecurityGroupIngress': [],
        'SecurityGroupEgress': [{'IpProtocol': 'tcp', 'FromPort': port, 'ToPort': port,
                                'CidrIp': '0.0.0.0/0'} for port in (80, 443)], 'Tags': tags},
        'Isolate the VM without public inbound ports or a NAT gateway.', ['Ingress must remain empty'])
    resources['WatchdogRole'] = resource('AWS::IAM::Role', {
        'AssumeRolePolicyDocument': trust('lambda.amazonaws.com'), 'Tags': tags,
        'Policies': [{'PolicyName': 'ExpireCampaignVM', 'PolicyDocument': {
            'Version': '2012-10-17', 'Statement': [
                {'Effect': 'Allow', 'Action': ['ec2:DescribeInstances'], 'Resource': '*'},
                {'Effect': 'Allow', 'Action': ['ec2:TerminateInstances'],
                 'Resource': sub('arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/*'),
                 'Condition': {'StringEquals': {'ec2:ResourceTag/FactumDBCampaign': ref('Campaign'),
                                               'ec2:ResourceTag/ManagedBy': 'FactumDBBenchmark'}}},
                {'Effect': 'Allow', 'Action': ['logs:CreateLogStream', 'logs:PutLogEvents'],
                 'Resource': sub('arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/${AWS::StackName}-expiry:*')}
            ]}}]}, 'Independent compute cutoff even if laptop/controller disconnects.',
        ['Terminate only this campaign and ManagedBy tag; describe API requires wildcard resource'])
    resources['WatchdogLogs'] = resource('AWS::Logs::LogGroup', {
        'LogGroupName': sub('/aws/lambda/${AWS::StackName}-expiry'), 'RetentionInDays': 1},
        'Short retention diagnostics; explicitly owned by stack for deletion.',
        ['Delete with stack after results copied'], DeletionPolicy='Delete', UpdateReplacePolicy='Delete')
    resources['Watchdog'] = resource('AWS::Lambda::Function', {
        'FunctionName': sub('${AWS::StackName}-expiry'), 'Runtime': 'python3.12', 'Handler': 'index.handler',
        'Role': attr('WatchdogRole', 'Arn'), 'Timeout': 60, 'MemorySize': 128,
        'Environment': {'Variables': {'CAMPAIGN': ref('Campaign')}},
        'Code': {'ZipFile': watchdog}, 'Tags': tags},
        'Check expiry every minute; local controller handles complete stack cleanup.',
        ['Fixed per-machine expiry; do not treat compute cutoff as proof of full teardown'],
        DependsOn=['WatchdogLogs'])
    resources['ExpiryRule'] = resource('AWS::Events::Rule', {
        'ScheduleExpression': 'rate(1 minute)', 'State': 'ENABLED',
        'Targets': [{'Id': 'ExpireVM', 'Arn': attr('Watchdog', 'Arn'),
                     'RetryPolicy': {'MaximumEventAgeInSeconds': 300, 'MaximumRetryAttempts': 2}}]},
        'Invoke compute failsafe without depending on guest or local host.')
    resources['WatchdogPermission'] = resource('AWS::Lambda::Permission', {
        'Action': 'lambda:InvokeFunction', 'FunctionName': ref('Watchdog'),
        'Principal': 'events.amazonaws.com', 'SourceArn': attr('ExpiryRule', 'Arn'),
        'SourceAccount': ref('AWS::AccountId')}, 'Constrain EventBridge invocation to this rule and project.')
    linux = '#!/bin/bash\nset -eu\nshutdown -P +90\n'
    windows = '<powershell>\nshutdown.exe /s /t 5400 /f\n</powershell>'
    resources['Guest'] = resource('AWS::EC2::Instance', {
        'ImageId': ref('ImageId'), 'InstanceType': ref('InstanceType'),
        'IamInstanceProfile': ref('GuestProfile'), 'InstanceInitiatedShutdownBehavior': 'terminate',
        'MetadataOptions': {'HttpTokens': 'required', 'HttpEndpoint': 'enabled'},
        'NetworkInterfaces': [{'DeviceIndex': '0', 'AssociatePublicIpAddress': True,
                               'SubnetId': ref('SubnetId'), 'GroupSet': [ref('GuestSecurityGroup')]}],
        'BlockDeviceMappings': [{'DeviceName': '/dev/sda1', 'Ebs': {
            'VolumeSize': 40, 'VolumeType': 'gp3', 'Encrypted': True, 'DeleteOnTermination': True}}],
        'CreditSpecification': {'Fn::If': ['IsT3', {'CPUCredits': 'standard'}, ref('AWS::NoValue')]},
        'UserData': {'Fn::Base64': {'Fn::If': ['IsWindows', windows, linux]}}, 'Tags': tags},
        'One temporary machine per stack; encrypted disk auto-deletes on termination.',
        ['No launch before watchdog is present; no inbound ports; delete root disk; Sydney only'],
        DependsOn=['ExpiryRule', 'WatchdogPermission'])
    return {'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'Disposable application benchmark VM with a separate expiry watchdog and private temporary artifacts.',
            'Metadata': {'AWSToolsMetrics': {'AWSAgentToolkit': 'aws-cloudformation@3'},
                         'com.aws.cloudformation.Context': {'must': ['Sydney only; USD 20 total; sequential machines; disposable resources'],
                         'ref': [{'at': 'docs/aws-testing.md', 'has': 'launch gates, costs and full cleanup'}]}},
            'Parameters': {
                'Campaign': {'Type': 'String', 'AllowedPattern': 'factumdb-[a-z0-9-]{8,50}'},
                'ExpiresAt': {'Type': 'String', 'AllowedPattern': '[0-9T:.+Z-]+'},
                'GuestOS': {'Type': 'String', 'AllowedValues': ['ubuntu', 'windows']},
                'InstanceType': {'Type': 'String', 'AllowedValues': ['t3.micro', 't3.small', 'c7i-flex.large', 'm7i-flex.large']},
                'ImageId': {'Type': 'AWS::EC2::Image::Id'}, 'VpcId': {'Type': 'AWS::EC2::VPC::Id'},
                'SubnetId': {'Type': 'AWS::EC2::Subnet::Id'}},
            'Rules': {'SydneyOnly': {'Assertions': [{'Assert': {'Fn::Equals': [ref('AWS::Region'), 'ap-southeast-2']},
                                                   'AssertDescription': 'Benchmark resources must stay in Sydney'}]}},
            'Conditions': {'IsWindows': {'Fn::Equals': [ref('GuestOS'), 'windows']},
                           'IsT3': {'Fn::Or': [{'Fn::Equals': [ref('InstanceType'), 't3.micro']},
                                              {'Fn::Equals': [ref('InstanceType'), 't3.small']}]}},
            'Resources': resources,
            'Outputs': {name: {'Description': description, 'Value': value} for name, description, value in (
                ('InstanceId', 'Disposable test machine', ref('Guest')),
                ('Bucket', 'Temporary private artifacts/results bucket', ref('Artifacts')),
                ('WatchdogFunction', 'Independent expiry checker', ref('Watchdog')))}}
