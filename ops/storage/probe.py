#!/usr/bin/env python3
"""Direct S3 synthetic probe on owner's computer. Permanent keys may stay on VPS."""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET


def presign(operation, key, version=None):
    request = {'operation': operation, 'key': key}
    if version:
        request['versionId'] = version
    target = os.environ.get('S3_SIGNER_SSH')
    if target:
        if not re.fullmatch(r'[A-Za-z0-9_@.-]+', target) or target.startswith('-'):
            raise ValueError('invalid SSH target')
        result = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', target,
                                 '/opt/media-knowledge/storage-venv/bin/python /usr/local/libexec/media-knowledge/sign-probe.py'],
                                input=json.dumps(request), text=True, capture_output=True, check=True, timeout=30)
        return json.loads(result.stdout)['url']
    import boto3
    from botocore.config import Config
    s3 = boto3.client('s3', endpoint_url=os.environ.get('S3_ENDPOINT', 'https://storage.yandexcloud.net'),
                      region_name='ru-central1', config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}))
    params = {'Bucket': os.environ['S3_BUCKET'], 'Key': key}
    if version:
        params['VersionId'] = version
    method = {'put': 'put_object', 'get': 'get_object', 'head': 'head_object', 'delete': 'delete_object'}[operation]
    return s3.generate_presigned_url(method, Params=params, ExpiresIn=120)


def main():
    bucket, origin = os.environ['S3_BUCKET'], os.environ['WEB_ORIGIN']
    key = f'infra-probe/{uuid.uuid4()}.bin'
    payload = b'media-knowledge synthetic range test\n'
    version, uploaded = None, False
    stage = 'preflight'
    try:
        upload = presign('put', key)
        preflight = urllib.request.Request(upload, method='OPTIONS', headers={
            'Origin': origin, 'Access-Control-Request-Method': 'PUT',
            'Access-Control-Request-Headers': 'content-type'})
        with urllib.request.urlopen(preflight, timeout=15) as response:
            assert response.headers['Access-Control-Allow-Origin'] == origin
            assert 'PUT' in response.headers['Access-Control-Allow-Methods']
        stage = 'put'
        with urllib.request.urlopen(urllib.request.Request(upload, data=payload, method='PUT'), timeout=15) as response:
            uploaded = True
            version = response.headers.get('x-amz-version-id')
            assert version and version != 'null', 'versioning not enabled'
        stage = 'head'
        with urllib.request.urlopen(urllib.request.Request(presign('head', key), method='HEAD'), timeout=15) as response:
            assert int(response.headers['Content-Length']) == len(payload)
        stage = 'range'
        download = presign('get', key)
        with urllib.request.urlopen(urllib.request.Request(download, headers={'Range': 'bytes=0-14', 'Origin': origin}), timeout=15) as response:
            assert response.status == 206
            assert response.read() == payload[:15]
            assert response.headers['Access-Control-Allow-Origin'] == origin
            assert response.headers['Content-Range'].startswith('bytes 0-14/')
        stage = 'foreign-origin'
        with urllib.request.urlopen(urllib.request.Request(download, headers={'Origin': 'https://untrusted.example'}), timeout=15) as response:
            assert response.headers.get('Access-Control-Allow-Origin') is None
        for url in [f'https://storage.yandexcloud.net/{bucket}/{key}', f'https://storage.yandexcloud.net/{bucket}?list-type=2']:
            try:
                with urllib.request.urlopen(url, timeout=15):
                    raise AssertionError('Anonymous access enabled')
            except urllib.error.HTTPError as error:
                assert error.code in (401, 403)
        print('PASS: direct presigned PUT, versioning, HEAD, GET Range, CORS preflight, rejected foreign origin and anonymous object/list access.')
    except urllib.error.HTTPError as error:
        try:
            code = ET.fromstring(error.read()).findtext('Code', default='unknown')
        except ET.ParseError:
            code = 'unknown'
        if not re.fullmatch(r'[A-Za-z0-9_-]+', code):
            code = 'unknown'
        print(f'S3 stage={stage}; error={code}', file=sys.stderr)
        raise
    finally:
        if uploaded:
            with urllib.request.urlopen(urllib.request.Request(presign('delete', key, version), method='DELETE'), timeout=15):
                pass
            print('Synthetic object version removed.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # HTTPError may embed a signed URL, so never print the exception or traceback.
        print(f'S3 probe failed: {type(error).__name__}; status={getattr(error, "code", "n/a")}', file=sys.stderr)
        sys.exit(1)
