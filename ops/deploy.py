#!/usr/bin/env python3
"""Forced SSH command. Root-owned installation; input carries one digest and a short-lived pull token."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path('/opt/media-knowledge')
IMAGES = ROOT / 'images.env'
REPOS = {'server': ('api', 'SERVER_IMAGE', 'media-knowledge-server', 18501, '/readyz'),
         'web': ('web', 'WEB_IMAGE', 'media-knowledge-web', 18500, '/')}


def write_images(values):
    target = IMAGES.with_suffix('.new')
    target.write_text(''.join(f'{k}={v}\n' for k, v in sorted(values.items())))
    os.chmod(target, 0o600)
    target.replace(IMAGES)


def main():
    component = sys.argv[1]
    service, variable, repo, port, path = REPOS[component]
    request = json.loads(sys.stdin.buffer.read(16385))
    digest, token = request['digest'], request['token']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('invalid digest')
    if not isinstance(token, str) or not 1 <= len(token) <= 4096:
        raise ValueError('invalid token')
    with (ROOT / 'deploy.lock').open('a') as lock, tempfile.TemporaryDirectory() as config:
        fcntl.flock(lock, fcntl.LOCK_EX)
        env = {**os.environ, 'DOCKER_CONFIG': config}
        subprocess.run(['docker', 'login', 'ghcr.io', '-u', 'ZeraiGR', '--password-stdin'], input=token.encode(), env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        image = f'ghcr.io/zeraigr/{repo}@{digest}'
        subprocess.run(['docker', 'pull', image], env=env, check=True)
        previous = dict(line.split('=', 1) for line in IMAGES.read_text().splitlines() if line)
        updated = {**previous, variable: image}
        write_images(updated)
        compose = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(ROOT / 'secrets.env'), '--env-file', str(IMAGES), '-f', str(ROOT / 'compose.yaml')]
        def up():
            if component == 'server':
                subprocess.run(compose + ['up', '-d', '--wait', 'db'], env=env, check=True)
            subprocess.run(compose + ['up', '-d', '--no-deps', '--pull', 'never', service], env=env, check=True)
        try:
            up()
            for _ in range(30):
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=2) as response:
                        if response.status == 200:
                            print(f'{component} deployed at {digest}')
                            return
                except OSError:
                    pass
                time.sleep(2)
            raise RuntimeError('readiness timed out')
        except Exception:
            write_images(previous)
            if '@sha256:' in previous.get(variable, ''):
                subprocess.run(compose + ['up', '-d', '--no-deps', '--pull', 'never', service], env=env, check=False)
            else:
                subprocess.run(compose + ['stop', service], env=env, check=False)
            raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never log the request, token, environment, or database credentials.
        print(f'Deployment failed: {type(exc).__name__}', file=sys.stderr)
        sys.exit(1)
