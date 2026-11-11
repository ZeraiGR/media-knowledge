#!/usr/bin/env python3
"""Encrypted PostgreSQL backup and isolated restore checks. Never handles media."""
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

CONFIG = Path('/etc/media-knowledge/backup.json')
STATE = Path('/var/lib/media-knowledge-backup')
HOST = 'media-knowledge-db'
TAG = 'postgres'
SOURCE = 'media-knowledge-db-1'
DEPLOY = Path('/opt/media-knowledge')


def atomic_json(path, value):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def command(args, *, env=None, stdin=None, stdout=subprocess.PIPE):
    with (STATE / 'operation.log').open('ab') as log:
        return subprocess.run(args, env=env, stdin=stdin, stdout=stdout, stderr=log,
                              check=True, timeout=1800).stdout


def restic(config, *args, stdin=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith(('RESTIC_', 'RCLONE_'))}
    env.update(RESTIC_REPOSITORY=config['repository'], RESTIC_PASSWORD_FILE=config['passwordFile'],
               RCLONE_CONFIG=config['rcloneConfig'], RESTIC_CACHE_DIR=str(STATE / 'cache'))
    return command(['restic', *args], env=env, stdin=stdin)


def check_repository(config):
    actual = json.loads(restic(config, 'cat', 'config'))['id']
    if actual != config['repositoryId']:
        raise ValueError('Unexpected repository identity')


def check_capacity(config, database_size):
    env = {**os.environ, 'RCLONE_CONFIG': config['rcloneConfig']}
    remote = json.loads(command(['rclone', 'about', config['remote'], '--json'], env=env))
    required = database_size * 2 + 512 * 1024**2
    if remote.get('free', 0) < required or shutil.disk_usage(STATE).free < required:
        raise ValueError('Insufficient backup capacity')


def database_image(container):
    image_id = command(['docker', 'inspect', '--format', '{{.Image}}', container]).decode().strip()
    image = json.loads(command(['docker', 'image', 'inspect', image_id]))[0]
    digest = next((item for item in image.get('RepoDigests', []) if item.startswith('postgres@sha256:')), None)
    if not digest:
        raise ValueError('PostgreSQL image digest not found')
    return digest


def validate_manifest(stage):
    manifest = json.loads((stage / 'manifest.json').read_text())
    if manifest['formatVersion'] != 1 or not re.fullmatch(r'postgres@sha256:[a-f0-9]{64}', manifest['image']):
        raise ValueError('Invalid recovery manifest')
    expected = {'database.dump', 'recovery/compose.yaml', 'recovery/images.env', 'recovery/secrets.env'}
    if set(manifest['sha256']) != expected:
        raise ValueError('Unexpected recovery files')
    for name, digest in manifest['sha256'].items():
        path = stage / name
        if path.is_symlink() or not path.is_file() or sha256(path) != digest:
            raise ValueError('Recovery checksum mismatch')
    return manifest


def take_snapshot(config, container=SOURCE, *, tag=TAG, stage=None):
    size = int(command(['docker', 'exec', container, 'psql', '-U', 'media', '-d', 'media', '-Atc', "SELECT pg_database_size(current_database())"]))
    check_capacity(config, size)
    stage = stage or STATE / 'staging'
    if stage.exists():
        raise ValueError('Stale staging exists; inspect before retry')
    (stage / 'recovery').mkdir(parents=True, mode=0o700)
    try:
        with (stage / 'database.dump').open('wb') as output:
            command(['docker', 'exec', container, 'pg_dump', '-U', 'media', '-d', 'media', '-Fc', '--no-owner', '--no-acl'], stdout=output)
        with (stage / 'database.dump').open('rb') as source:
            command(['docker', 'exec', '-i', container, 'pg_restore', '--list'], stdin=source)
        for name in ['compose.yaml', 'images.env', 'secrets.env']:
            shutil.copy2(DEPLOY / name, stage / 'recovery' / name)
        files = ['database.dump', 'recovery/compose.yaml', 'recovery/images.env', 'recovery/secrets.env']
        manifest = {'formatVersion': 1, 'createdAt': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'image': database_image(container), 'databaseSizeBytes': size,
                    'sha256': {name: sha256(stage / name) for name in files}}
        atomic_json(stage / 'manifest.json', manifest)
        output = restic(config, 'backup', str(stage), '--host', HOST, '--tag', tag, '--json')
        summary = next(item for item in map(json.loads, output.splitlines()) if item.get('message_type') == 'summary')
        snapshot = summary['snapshot_id']
        confirmed = json.loads(restic(config, 'snapshots', snapshot, '--json'))
        if len(confirmed) != 1 or not confirmed[0]['id'].startswith(snapshot):
            raise ValueError('Snapshot not confirmed')
        return {'snapshotId': confirmed[0]['id'], 'time': manifest['createdAt'], 'stagePath': str(stage), 'databaseSizeBytes': size}
    finally:
        # Only this invocation's newly created staging is removed.
        shutil.rmtree(stage)


@contextlib.contextmanager
def isolated_database(image):
    if not re.fullmatch(r'postgres@sha256:[a-f0-9]{64}', image):
        raise ValueError('PostgreSQL digest required')
    name = 'media-knowledge-restore-' + uuid.uuid4().hex
    command(['docker', 'run', '-d', '--pull', 'never', '--name', name,
             '--label', 'media-knowledge.restore-drill=true', '--network', 'none',
             '--memory', '384m', '--cpus', '0.5', '--pids-limit', '100',
             '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_USER=media', '-e', 'POSTGRES_DB=media', image])
    try:
        for _ in range(60):
            try:
                if command(['docker', 'exec', name, 'cat', '/proc/1/comm']).decode().strip() != 'postgres':
                    time.sleep(1)
                    continue
                command(['docker', 'exec', name, 'psql', '-U', 'media', '-d', 'media', '-Atc', 'SELECT 1'])
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError('Restore database not ready')
        yield name
    finally:
        command(['docker', 'rm', '-f', '-v', name])


def verify_snapshot(config, record, *, expected_probe=None):
    with tempfile.TemporaryDirectory(prefix='restore-', dir=STATE) as destination:
        restic(config, 'restore', record['snapshotId'] + ':' + record['stagePath'], '--target', destination)
        stage = Path(destination)
        manifest = validate_manifest(stage)
        with isolated_database(manifest['image']) as container:
            with (stage / 'database.dump').open('rb') as source:
                command(['docker', 'exec', '-i', container, 'pg_restore', '-U', 'media', '-d', 'media',
                         '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl'], stdin=source)
            if expected_probe is not None:
                actual = command(['docker', 'exec', container, 'psql', '-U', 'media', '-d', 'media', '-Atc',
                                  "SELECT count(*)::text || ':' || md5(string_agg(payload, '|' ORDER BY id)) FROM backup_probe"]).decode().strip()
                if actual != expected_probe:
                    raise ValueError('Restored fixture content mismatch')
            count = int(command(['docker', 'exec', container, 'psql', '-U', 'media', '-d', 'media', '-Atc',
                                 "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"]))
        return {'snapshotId': record['snapshotId'], 'verifiedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'userTables': count}


def drill(config):
    with isolated_database(database_image(SOURCE)) as source:
        command(['docker', 'exec', source, 'psql', '-U', 'media', '-d', 'media', '-v', 'ON_ERROR_STOP=1', '-c',
                 "CREATE TABLE backup_probe(id integer PRIMARY KEY, payload text NOT NULL); INSERT INTO backup_probe SELECT n, 'Проверка резервной копии ' || n FROM generate_series(1,257) n;"])
        expected = command(['docker', 'exec', source, 'psql', '-U', 'media', '-d', 'media', '-Atc',
                            "SELECT count(*)::text || ':' || md5(string_agg(payload, '|' ORDER BY id)) FROM backup_probe"]).decode().strip()
        record = take_snapshot(config, source, tag='drill', stage=STATE / 'drill-staging')
    result = verify_snapshot(config, record, expected_probe=expected)
    result['fixtureRows'] = 257
    atomic_json(STATE / 'drill-success.json', result)
    return result


def main():
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    if action not in {'backup', 'verify', 'drill', 'status'}:
        raise ValueError('Choose backup, verify, drill or status')
    if action == 'status':
        result = {}
        for name in ['success', 'verify-success', 'drill-success', 'backup-failure', 'verify-failure', 'drill-failure']:
            path = STATE / (name + '.json')
            if path.exists():
                result[name] = json.loads(path.read_text())
        print(json.dumps(result))
        return
    with (STATE / 'operation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads(CONFIG.read_text())
        check_repository(config)
        if action == 'backup':
            result = take_snapshot(config)
            atomic_json(STATE / 'success.json', result)
        elif action == 'verify':
            record = json.loads((STATE / 'success.json').read_text())
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(record['time'])
            if age.total_seconds() > 26 * 3600:
                raise ValueError('Latest backup is stale')
            restic(config, 'check', '--read-data')
            result = verify_snapshot(config, record)
            atomic_json(STATE / 'verify-success.json', result)
        else:
            result = drill(config)
        (STATE / (action + '-failure.json')).unlink(missing_ok=True)
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if STATE.exists():
            action = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in {'backup', 'verify', 'drill'} else 'operation'
            atomic_json(STATE / (action + '-failure.json'), {'time': dt.datetime.now(dt.timezone.utc).isoformat(), 'error': type(error).__name__})
        print('Backup operation not confirmed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
