import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prepare_cpu_worker',ROOT/'scripts/prepare_cpu_worker.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CpuWorkerRecipeTest(unittest.TestCase):
    def test_build_context_excludes_repo_credentials_and_data(self):
        args=module.build_arguments('arm64','studio-cpu:rc2')
        self.assertEqual(args[-1],str(ROOT/'runtime/cpu'))
        self.assertNotIn('--privileged',args)
        self.assertEqual((ROOT/'runtime/cpu/.dockerignore').read_text().splitlines(),['*','!Dockerfile','!requirements-linux-arm64.lock','!requirements-linux-amd64.lock','!wheels/','!wheels/*.whl'])
        for arch in ['arm64','amd64']:
            lock=(ROOT/f'runtime/cpu/requirements-linux-{arch}.lock').read_text()
            self.assertIn('https://download.pytorch.org/whl/cpu',lock)
            self.assertIn('torch==2.8.0+cpu',lock)
            self.assertNotIn('nvidia-',lock)
            self.assertIn('--hash=sha256:',lock)
        docker=(ROOT/'runtime/cpu/Dockerfile').read_text()
        self.assertIn('ARG BASE_IMAGE=python:3.12.15-slim@sha256:',docker)
        self.assertIn('FROM ${BASE_IMAGE}',docker)
        with self.assertRaises(ValueError):module.build_arguments('arm64','studio:rc2','unverified:latest')
        self.assertIn('--no-index --find-links=/tmp/wheels --require-hashes --only-binary=:all:',docker)
        self.assertIn('--network=none',args)
        self.assertIn('USER 65532:65532',docker)
        self.assertNotIn('COPY . ',docker)

    def test_unsafe_architecture_and_tag_are_rejected(self):
        for arch,tag in [('unsupported','studio:rc2'),('arm64','bad; echo secret'),('arm64','../../data')]:
            with self.assertRaises(ValueError):module.build_arguments(arch,tag)

    def test_atomic_config_is_private_and_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'config.json';module.atomic_json(p,{'image':'owned'})
            self.assertEqual(json.loads(p.read_text()),{'image':'owned'})
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            alias=root/'alias.json';alias.symlink_to(p)
            with self.assertRaises(ValueError):module.atomic_json(alias,{'image':'other'})
            self.assertEqual(json.loads(p.read_text()),{'image':'owned'})

    def test_pinned_official_base_metadata_and_redirect_do_not_expose_credentials(self):
        import hashlib
        import urllib.request
        spec=importlib.util.spec_from_file_location('prepare_cpu_base',ROOT/'scripts/prepare_cpu_base.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
        index=ROOT/'runtime/cpu/base-manifests'/(base.INDEX.split(':')[1]+'.json')
        self.assertEqual('sha256:'+hashlib.sha256(index.read_bytes()).hexdigest(),base.INDEX)
        v=json.loads(index.read_bytes())
        for arch in ['arm64','amd64']:
            row=next(r for r in v['manifests'] if r['platform'].get('architecture')==arch)
            path=index.parent/(row['digest'].split(':')[1]+'.json')
            self.assertEqual('sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),row['digest'])
        req=urllib.request.Request('https://registry-1.docker.io/v2/blob',headers={'Authorization':'Bearer private-fixture'})
        redirected=base.SafeRedirect().redirect_request(req,None,302,'',{},'https://docker-images-prod.s3.amazonaws.com/public-layer')
        self.assertIsNone(redirected.get_header('Authorization'))
        with self.assertRaises(ValueError):base.SafeRedirect().redirect_request(req,None,302,'',{},'http://example.com/layer')

    def test_setup_progress_redacts_signed_urls_and_terminates_timed_out_command(self):
        import contextlib
        import io
        import subprocess
        import sys
        output=io.StringIO()
        with contextlib.redirect_stderr(output):
            module.command([sys.executable,'-c',"print('download https://user:private-fixture@example.com/object?signature=private-fixture')"],timeout=3)
        self.assertIn('https://example.com/object',output.getvalue())
        self.assertNotIn('private-fixture',output.getvalue())
        with self.assertRaises(subprocess.TimeoutExpired):
            module.command([sys.executable,'-c','import time;time.sleep(20)'],timeout=.05)
