#!/usr/bin/env python3
"""Admin SSH helper. Returns short-lived URLs for synthetic probes only."""
import json
from pathlib import Path
import re
import sys

METHODS = {'put': 'put_object', 'get': 'get_object', 'head': 'head_object', 'delete': 'delete_object'}


def sign_request(request, client, bucket):
    key = request.get('key', '')
    operation = request.get('operation')
    if operation not in METHODS or not re.fullmatch(r'infra-probe/[a-f0-9-]{36}\.bin', key):
        raise ValueError('only synthetic probe operations are allowed')
    params = {'Bucket': bucket, 'Key': key}
    if request.get('versionId'):
        if operation != 'delete':
            raise ValueError('versionId is only accepted for probe cleanup')
        params['VersionId'] = request['versionId']
    return client.generate_presigned_url(METHODS[operation], Params=params, ExpiresIn=120)


def main():
    import boto3
    from botocore.config import Config
    config = json.loads(Path('/etc/media-knowledge/storage.json').read_text())
    client = boto3.client('s3', endpoint_url=config['endpoint'], region_name=config['region'],
                          aws_access_key_id=config['accessKeyId'], aws_secret_access_key=config['secretAccessKey'],
                          config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}))
    request = json.loads(sys.stdin.buffer.read(2049))
    print(json.dumps({'url': sign_request(request, client, config['bucket'])}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Probe signer failed: {type(error).__name__}', file=sys.stderr)
        sys.exit(1)
