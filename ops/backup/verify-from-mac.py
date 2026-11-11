#!/usr/bin/env python3
"""Read and verify DB recovery files directly from external storage, without VPS."""
import datetime as dt
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def keychain(service):
    return subprocess.check_output(['security', 'find-generic-password', '-a', getpass.getuser(),
                                    '-s', service, '-w'], stderr=subprocess.DEVNULL, text=True, timeout=30).strip()


def main():
    config = json.loads((Path.home() / '.config/media-knowledge/database-backup.json').read_text())
    env = {k: v for k, v in os.environ.items() if not k.startswith(('RESTIC_', 'RCLONE_'))}
    env.update(RESTIC_REPOSITORY=config['macRepository'], RESTIC_PASSWORD=keychain(config['keychainService']),
               RCLONE_CONFIG=config['macRcloneConfig'], RCLONE_CONFIG_PASS=keychain(config['rcloneKeychainService']))
    with tempfile.TemporaryDirectory(prefix='media-knowledge-db-check-') as cache:
        env['RESTIC_CACHE_DIR'] = cache
        def read(*args):
            return subprocess.check_output([config['restic'], *args], env=env, stderr=subprocess.DEVNULL, timeout=1800)
        if json.loads(read('cat', 'config'))['id'] != config['repositoryId']:
            raise ValueError('Repository identity mismatch')
        snapshots = json.loads(read('snapshots', '--host', 'media-knowledge-db', '--tag', 'postgres', '--json'))
        if not snapshots:
            raise ValueError('No database snapshots')
        snapshot = max(snapshots, key=lambda item: item['time'])
        if snapshot['paths'] != ['/var/lib/media-knowledge-backup/staging']:
            raise ValueError('Unexpected snapshot path')
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(snapshot['time'].replace('Z', '+00:00'))
        if age.total_seconds() > 26 * 3600:
            raise ValueError('Database backup is stale')
        prefix = snapshot['paths'][0] + '/'
        manifest = json.loads(read('dump', snapshot['id'], prefix + 'manifest.json'))
        expected = {'database.dump', 'recovery/compose.yaml', 'recovery/images.env', 'recovery/secrets.env'}
        if manifest['formatVersion'] != 1 or set(manifest['sha256']) != expected:
            raise ValueError('Invalid recovery manifest')
        for name, expected_hash in manifest['sha256'].items():
            digest = hashlib.sha256()
            with subprocess.Popen([config['restic'], 'dump', snapshot['id'], prefix + name], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
                for block in iter(lambda: process.stdout.read(1024 * 1024), b''):
                    digest.update(block)
                if process.wait(timeout=1800) != 0 or digest.hexdigest() != expected_hash:
                    raise ValueError('Recovery file checksum mismatch')
        result = {'snapshotId': snapshot['id'], 'verifiedFiles': len(expected), 'withoutVPS': True, 'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'ok': True}
        status = Path.home() / '.config/media-knowledge/db-recovery-check.json'
        temporary = status.with_suffix('.new')
        temporary.write_text(json.dumps(result, indent=2) + '\n')
        temporary.chmod(0o600)
        temporary.replace(status)
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        status = Path.home() / '.config/media-knowledge/db-recovery-check.json'
        status.write_text(json.dumps({'ok': False, 'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'error': type(error).__name__}) + '\n')
        status.chmod(0o600)
        subprocess.run(['osascript', '-e', 'display notification "Копия БД не подтверждена. Проверьте сеть, Keychain и журнал резервирования." with title "Media Knowledge: резервная копия"'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('Independent DB recovery check failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
