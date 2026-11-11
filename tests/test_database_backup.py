import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('database_backup', Path(__file__).parents[1] / 'ops/backup/run.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
IMAGE = 'postgres@sha256:' + 'a' * 64


class RecoveryBoundaryTest(unittest.TestCase):
    def test_manifest_rejects_paths_outside_recovery_set(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'manifest.json').write_text(json.dumps({'formatVersion': 1, 'image': IMAGE, 'sha256': {'../secrets': 'a'}}))
            with self.assertRaises(ValueError):
                backup.validate_manifest(path)

    def test_manifest_rejects_corrupted_file_before_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            files = ['database.dump', 'recovery/compose.yaml', 'recovery/images.env', 'recovery/secrets.env']
            (path / 'recovery').mkdir()
            for name in files:
                (path / name).write_bytes(b'synthetic')
            manifest = {'formatVersion': 1, 'image': IMAGE, 'sha256': {name: backup.sha256(path / name) for name in files}}
            (path / 'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(backup.validate_manifest(path), manifest)
            (path / 'database.dump').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                backup.validate_manifest(path)

    def test_stale_staging_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            sentinel = stage / 'previous.dump'
            sentinel.write_bytes(b'preserve')
            with patch.object(backup, 'command', return_value=b'1024'), patch.object(backup, 'check_capacity'):
                with self.assertRaises(ValueError):
                    backup.take_snapshot({}, stage=stage)
            self.assertEqual(sentinel.read_bytes(), b'preserve')

    def test_insufficient_cloud_capacity_fails_before_dump(self):
        with patch.object(backup, 'command', return_value=b'{"free":1024}'), patch.object(backup.shutil, 'disk_usage', return_value=Mock(free=10**12)):
            with self.assertRaises(ValueError):
                backup.check_capacity({'remote': 'synthetic:', 'rcloneConfig': '/synthetic'}, 1024)

    def test_restore_requires_pinned_postgres_image(self):
        with patch.object(backup, 'command') as run:
            with self.assertRaises(ValueError), backup.isolated_database('postgres:latest'):
                pass
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
