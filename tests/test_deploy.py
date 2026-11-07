import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('deploy',Path(__file__).parents[1]/'ops/deploy.py')
deploy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentTest(unittest.TestCase):
    def test_rejects_non_digest_before_docker(self):
        request=io.TextIOWrapper(io.BytesIO(json.dumps({'digest':'latest; rm -rf /','token':'test'}).encode()))
        with patch('sys.argv',['deploy','server']), patch('sys.stdin',request), patch.object(deploy.subprocess,'run') as run:
            with self.assertRaises(ValueError):deploy.main()
            run.assert_not_called()

    def test_failed_readiness_restores_previous_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            images=root/'images.env'
            before='SERVER_IMAGE=previous-server\nWEB_IMAGE=previous-web\n'
            images.write_text(before)
            request=io.TextIOWrapper(io.BytesIO(json.dumps({'digest':'sha256:'+'a'*64,'token':'secret'}).encode()))
            with patch.object(deploy,'ROOT',root),patch.object(deploy,'IMAGES',images),patch('sys.argv',['deploy','server']),patch('sys.stdin',request),patch.object(deploy.subprocess,'run') as run,patch.object(deploy.urllib.request,'urlopen',side_effect=OSError()),patch.object(deploy.time,'sleep'):
                with self.assertRaises(RuntimeError):deploy.main()
                self.assertEqual(images.read_text(),before)
                calls=[str(c) for c in run.call_args_list]
                self.assertTrue(any('--pull' in c and 'never' in c for c in calls))
                self.assertFalse(any('prune' in c for c in calls))

    def test_image_replacement_is_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            images=Path(directory)/'images.env'
            with patch.object(deploy,'IMAGES',images):deploy.write_images({'SERVER_IMAGE':'digest'})
            self.assertEqual(images.stat().st_mode&0o777,0o600)
            self.assertEqual(images.read_text(),'SERVER_IMAGE=digest\n')


if __name__=='__main__':unittest.main()
