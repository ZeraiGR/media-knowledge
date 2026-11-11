#!/usr/bin/env python3
"""Render a scoped bucket policy without embedding deployment identifiers."""
import json
import os

bucket = os.environ['S3_BUCKET']
owner = os.environ['S3_OWNER_ID']
service_account = os.environ['S3_SERVICE_ACCOUNT_ID']
assert owner != service_account, 'Owner and runtime service account must differ'
resource = f'arn:aws:s3:::{bucket}'
policy = {'Version': '2012-10-17', 'Statement': [
    {'Effect': 'Allow', 'Principal': {'CanonicalUser': owner}, 'Action': 's3:*', 'Resource': [resource, resource + '/*']},
    {'Effect': 'Allow', 'Principal': {'CanonicalUser': service_account},
     'Action': ['s3:GetObject', 's3:PutObject', 's3:DeleteObject', 's3:AbortMultipartUpload', 's3:ListMultipartUploadParts'],
     'Resource': resource + '/*'},
    {'Effect': 'Allow', 'Principal': {'CanonicalUser': service_account},
     'Action': ['s3:ListBucket', 's3:ListBucketMultipartUploads'], 'Resource': resource},
    {'Effect': 'Allow', 'Principal': {'CanonicalUser': service_account},
     'Action': ['s3:DeleteObjectVersion'], 'Resource': resource + '/infra-probe/*'},
]}
print(json.dumps(policy, indent=2))
