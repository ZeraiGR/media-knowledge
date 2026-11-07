#!/usr/bin/env python3
"""Direct S3 synthetic probe; run on the owner's computer, never VPS."""
import os
import uuid
import urllib.error
import urllib.request
import boto3

s3 = boto3.client('s3', endpoint_url=os.environ.get('S3_ENDPOINT', 'https://storage.yandexcloud.net'), region_name='ru-central1')
bucket = os.environ['S3_BUCKET']
origin = os.environ['WEB_ORIGIN']
key = f'infra-probe/{uuid.uuid4()}.bin'
payload = b'media-knowledge synthetic range test\n'
version = None
try:
    upload = s3.generate_presigned_url('put_object', Params={'Bucket':bucket,'Key':key}, ExpiresIn=120)
    with urllib.request.urlopen(urllib.request.Request(upload, data=payload, method='PUT')) as result:
        version = result.headers.get('x-amz-version-id')
    download = s3.generate_presigned_url('get_object', Params={'Bucket':bucket,'Key':key}, ExpiresIn=120)
    with urllib.request.urlopen(urllib.request.Request(download, headers={'Range':'bytes=0-14','Origin':origin})) as result:
        assert result.status == 206
        assert result.read() == payload[:15]
        assert result.headers['Access-Control-Allow-Origin'] == origin
        assert result.headers['Content-Range'].startswith('bytes 0-14/')
    unsigned = f'https://storage.yandexcloud.net/{bucket}/{key}'
    try:
        urllib.request.urlopen(unsigned)
        raise AssertionError('Anonymous access is enabled')
    except urllib.error.HTTPError as error:
        assert error.code in (401,403)
    print('Direct presigned PUT, GET Range, CORS and denied anonymous access passed.')
finally:
    args = {'Bucket':bucket,'Key':key}
    if version:
        args['VersionId'] = version
    s3.delete_object(**args)
