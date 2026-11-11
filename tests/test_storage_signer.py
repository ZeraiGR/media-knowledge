import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('sign_probe', Path(__file__).parents[1] / 'ops/storage/sign-probe.py')
signer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signer)
KEY = 'infra-probe/12345678-1234-1234-1234-123456789abc.bin'


class SignerBoundaryTest(unittest.TestCase):
    def test_rejects_owner_objects_and_unknown_operations_before_signing(self):
        client = Mock()
        for key, operation in [('originals/recording.mp4', 'get'), ('infra-probe/../owner.bin', 'delete'), (KEY, 'list')]:
            with self.assertRaises(ValueError):
                signer.sign_request({'key': key, 'operation': operation}, client, 'synthetic')
        client.generate_presigned_url.assert_not_called()

    def test_cleanup_is_scoped_to_exact_probe_version_and_short_lived(self):
        client = Mock()
        signer.sign_request({'key': KEY, 'operation': 'delete', 'versionId': 'test-version'}, client, 'synthetic')
        client.generate_presigned_url.assert_called_once_with('delete_object', Params={'Bucket': 'synthetic', 'Key': KEY, 'VersionId': 'test-version'}, ExpiresIn=120)

    def test_read_cannot_select_an_old_version(self):
        with self.assertRaises(ValueError):
            signer.sign_request({'key': KEY, 'operation': 'get', 'versionId': 'old'}, Mock(), 'synthetic')


if __name__ == '__main__':
    unittest.main()
