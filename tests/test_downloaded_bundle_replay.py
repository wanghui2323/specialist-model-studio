import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from model_harness.generic_recipe import _digest
from model_harness.isolated_execution import ExecutionBundle
from scripts.acceptance.replay_downloaded_bundle import sha, verify_extract


class DownloadedBundleReplayTest(unittest.TestCase):
    def build(self, root, extra=None, mutate=None):
        bundle=ExecutionBundle.create(files={'run.py':'# unit fixture; never executed\n'},stages={'predict':['python','/workspace/source/run.py']},image='sha256:'+'a'*64)
        payload={'artifacts/config.json':b'{}','artifacts/model/weights.json':b'{"weight":2}'}
        model={'task_id':'task-owned','run_id':'run-owned','bundle_sha256':bundle.digest,'model_files':['model/weights.json'],'artifacts':[{'path':name.removeprefix('artifacts/'),'role':'model' if 'weights' in name else 'inference_configuration','stage':'train','bytes':len(data),'sha256':sha(data)} for name,data in payload.items()]}
        model['model_sha256']=_digest(model)
        portable={'bundle':bundle.to_dict(),'bundle_sha256':bundle.digest,'inference':{'extensions':['.txt'],'max_bytes':1024}}
        payload.update({'artifacts/generic_model.json':json.dumps(model).encode(),'artifacts/generic_execution.json':json.dumps(portable).encode()})
        if extra:payload.update(extra)
        manifest={'task_id':'task-owned','run_id':'run-owned','bundle_id':'bundle-owned','files':[{'path':name,'size_bytes':len(data),'sha256':sha(data)} for name,data in payload.items()]}
        manifest['manifest_sha256']=_digest(manifest)
        if mutate:mutate(payload)
        archive=root/'bundle.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for name,data in payload.items():z.writestr(name,data)
            z.writestr('bundle_manifest.json',json.dumps(manifest))
        record={k:manifest[k] for k in ('task_id','run_id','bundle_id','manifest_sha256')}
        record['archive']={'sha256':sha(archive.read_bytes()),'size_bytes':archive.stat().st_size}
        return archive,record

    def test_exact_download_extracts_without_loading_model_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,record=self.build(root)
            manifest,model,portable,bundle=verify_extract(archive,record,root/'clean')
            self.assertEqual(manifest['run_id'],'run-owned')
            self.assertEqual(model['bundle_sha256'],bundle.digest)
            self.assertEqual((root/'clean/artifacts/model/weights.json').read_bytes(),b'{"weight":2}')

    def test_changed_file_fails_before_extraction_even_when_archive_hash_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,record=self.build(root,mutate=lambda payload:payload.update({'artifacts/config.json':b'{"changed":true}'}))
            with self.assertRaisesRegex(ValueError,'digest mismatch'):verify_extract(archive,record,root/'clean')
            self.assertFalse((root/'clean').exists())

    def test_traversal_in_declared_manifest_still_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,record=self.build(root,extra={'../escaped':b'x'})
            with self.assertRaisesRegex(ValueError,'unsafe archive path'):verify_extract(archive,record,root/'clean')
            self.assertFalse((root/'clean').exists())

    def test_wrong_canonical_archive_and_existing_destination_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,record=self.build(root);record['archive']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'canonical'):verify_extract(archive,record,root/'clean')
            (root/'clean').mkdir()
            with self.assertRaisesRegex(ValueError,'fresh extraction'):verify_extract(archive,record,root/'clean')
