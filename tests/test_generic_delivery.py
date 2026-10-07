from __future__ import annotations

import json
import os
import shutil
import unittest
from copy import deepcopy
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, unquote, urlsplit
from zipfile import ZipFile

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional server extra
    TestClient = None

from tests import test_generic_recipe as fixtures
from model_harness.evidence import ArtifactBundleBuilder, EvidenceError, EvaluationReport, InferenceCheck
from model_harness.errors import HarnessError
from model_harness.generic_inference import generic_sample_artifact
from model_harness.inference_inputs import InferenceInputError, InferenceInputStore
from model_harness.io_utils import read_json, sha256_file, write_json
from model_harness.isolated_execution import ExecutionBundle
from model_harness.sample_inference import SampleInference, SampleInferenceBlocked
from model_harness.server import create_app


class DeliveryExecutor(fixtures.EvidenceExecutor):
    """Fixture transport and bytes only: generated source is never host-executed."""
    media_name = "媒体/回答 #1.wav"
    media_bytes = b"fixture-media-output-not-a-real-trained-waveform"

    def run_stage(self, bundle, stage, **kwargs):
        evidence = super().run_stage(bundle, stage, **kwargs)
        output = kwargs["isolated_root"] / evidence["execution_id"] / "output"
        if stage == "train":
            write_json(output / "private" / "debug.json", {"private": "internal training diagnostics"})
        if stage == "predict":
            media = output / self.media_name
            media.parent.mkdir(parents=True)
            media.write_bytes(self.media_bytes)
            write_json(output / "infer_result.json", {"prediction": [2.5, -0.5], "artifacts": [self.media_name]})
        evidence["artifacts"] = [{"path": path.relative_to(output).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                                 for path in output.rglob("*") if path.is_file()]
        evidence["created_at"] = "2026-10-04T00:00:00+00:00"
        evidence["evidence_sha256"] = fixtures.digest({key: value for key, value in evidence.items() if key != "evidence_sha256"})
        return evidence


@unittest.skipIf(TestClient is None, "server extra is not installed")
class GenericDeliveryTests(unittest.TestCase):
    context = fixtures.GenericRecipeTests.context
    run_fixture = fixtures.GenericRecipeTests.run_fixture

    def setUp(self):
        fixtures.GenericRecipeTests.setUp(self)
        self.executor = DeliveryExecutor()
        self.plugin.executor = self.executor
        self.contract["execution_spec"]["artifacts"].append({"path": "private/debug.json", "role": "private_log", "export": False})
        self.run_dir = self.run_fixture()
        self.run_id = self.run_dir.name
        write_json(self.task_dir / "task.json", {"task_id": self.owner, "name": "Generic delivery fixture", "business_goal": self.contract["business_goal"],
            "status": "completed", "current_spec_revision": 1, "capability_request": self.contract["execution_spec"]["capability"],
            "recipe_id": "generic-isolated-execution", "run_ids": [self.run_id], "current_run_id": self.run_id})
        self.home = self.root / "fake-home"
        write_json(self.home / ".local/share/specialist-model-studio/execution-runtime.json", {"isolated_root": str(self.root / "isolated")})

    @contextmanager
    def client(self):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": "generic-delivery-test-token"}))
            app = create_app(self.root / "runs", workspace_dir=self.root / "workspace")
            runtime = app.state.conversation_runtime
            stack.enter_context(patch.object(runtime, "start"))
            stack.enter_context(patch.object(runtime, "stop"))
            stack.enter_context(patch("model_harness.generic_inference.GenericIsolatedRecipePlugin", return_value=self.plugin))
            stack.enter_context(patch("model_harness.generic_inference.Path.home", return_value=self.home))
            client = stack.enter_context(TestClient(app))
            yield client, app

    def _upload(self, client, *, filename="独立新输入.json", content=b'{"left":5,"right":1}', sample_type="generic"):
        return client.post(f"/tasks/{self.owner}/runs/{self.run_id}/inference-inputs", content=content,
            headers={"X-Filename": quote(filename), "X-Sample-Type": sample_type, "Content-Type": "application/octet-stream"})

    def _authorize_and_predict(self, client):
        uploaded = self._upload(client)
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        record = uploaded.json()["inference_input"]
        self.assertEqual(record["generic_declaration"], self.contract["execution_spec"]["inference"])
        payload = {"inference_input_id": record["inference_input_id"], "inference_input_sha256": record["sha256"],
                   "approval": {"actor": "user", "checkpoint_id": "generic-native-fixture-approval"}}
        url = f"/tasks/{self.owner}/runs/{self.run_id}/sample-inference-authorizations"
        self.assertEqual(client.post(url, json=payload).status_code, 403)
        authorization = client.post(url, json=payload, headers={"X-Model-Harness-Agent-Token": "generic-delivery-test-token"})
        self.assertEqual(authorization.status_code, 201, authorization.text)
        authorized = authorization.json()
        scope = authorized["sample_inference_authorization"]
        self.assertEqual(scope["scope"]["run_id"], self.run_id)
        executed = client.post(f"/tasks/{self.owner}/runs/{self.run_id}/inference-inputs/{record['inference_input_id']}/execute", json={
            "sample_inference_authorization_id": scope["authorization_id"], "authorization_token": authorized["authorization_token"], "sample_inference_request_sha256": scope["scope_sha256"]})
        self.assertEqual(executed.status_code, 201, executed.text)
        body = executed.json()
        self.assertEqual(body["inference_input"]["status"], "consumed")
        self.assertEqual(body["sample_inference_authorization"]["status"], "consumed")
        return body["sample_inference"]

    def test_raw_upload_to_scoped_generic_prediction_media_and_complete_portable_bundle(self):
        with self.client() as (client, app):
            report = self._authorize_and_predict(client)
            self.assertEqual(report["prediction"], [2.5, -0.5])
            self.assertEqual(self.executor.calls[-1]["stage"], "predict")
            self.assertEqual(set(self.executor.calls[-1]["inputs"]), {"sample/input.json", "model/weights/projection.json", "config.json"})
            self.assertEqual(report["model"]["sha256"], read_json(self.run_dir / "artifacts/generic_model.json")["model_sha256"])
            media = report["artifacts"][0]
            self.assertIn("%23", media["url"])
            self.assertNotIn("#", media["url"])
            self.assertTrue(unquote(urlsplit(media["url"]).path).endswith(DeliveryExecutor.media_name))
            downloaded = client.get(media["url"])
            self.assertEqual(downloaded.status_code, 200, downloaded.text)
            self.assertEqual(downloaded.content, DeliveryExecutor.media_bytes)
            self.assertTrue(downloaded.headers["content-type"].startswith("audio/"))
            nested = app.state.run_service.artifact_path(self.run_id, "weights/projection.json")
            self.assertEqual(read_json(nested)["bias"], 0.5)
            builder = ArtifactBundleBuilder(self.run_dir)
            bundle = builder.build(inference_check_id=report["inference_check_id"])
            with ZipFile(builder.bundle_path(bundle["bundle_id"])) as archive:
                names = set(archive.namelist())
                required = {"artifacts/generic_model.json", "artifacts/generic_execution.json", "artifacts/config.json", "artifacts/weights/projection.json", "artifacts/source/unseen.py", "evidence/evaluation_report.json", "evidence/inference_check.json"}
                self.assertTrue(required <= names, sorted(required - names))
                self.assertFalse(any(name.startswith(("datasets/", "train/", "test/", "logs/")) for name in names))
                self.assertNotIn("artifacts/private/debug.json", names)
                self.assertNotIn("artifacts/failure_samples.json", names)
                self.assertNotIn("task_contract.json", names)
                portable = json.loads(archive.read("artifacts/generic_execution.json"))
                self.assertNotIn("data_mapping", portable)
                self.assertNotIn(str(self.root), json.dumps(portable))
                bundle_value = portable["bundle"]
                bundle_value["files"] = {name: archive.read("artifacts/source/" + name).decode() for name in bundle_value["files"]}
                self.assertEqual(ExecutionBundle.from_dict(bundle_value).digest, portable["bundle_sha256"])
                model = json.loads(archive.read("artifacts/generic_model.json"))
                self.assertTrue(all("artifacts/" + name in names for name in model["model_files"]))

    def test_wrong_input_type_extension_size_and_foreign_run_are_rejected_before_execution(self):
        before = len(self.executor.calls)
        with self.client() as (client, app):
            for kwargs in ({"filename": "input.exe"}, {"content": b"x" * 2049}, {"sample_type": "image"}):
                response = self._upload(client, **kwargs)
                self.assertEqual(response.status_code, 422, response.text)
            response = client.post(f"/tasks/{self.owner}/runs/foreign-run/inference-inputs", content=b"{}", headers={"X-Filename": "input.json", "X-Sample-Type": "generic"})
            self.assertEqual(response.status_code, 409)
            record = self._upload(client).json()["inference_input"]
            with self.assertRaisesRegex(InferenceInputError, "another run"):
                app.state.training_workspace.inference_input_store.resolve_staged(task_id=self.owner, run_id="foreign-run", inference_input_id=record["inference_input_id"])
        self.assertEqual(len(self.executor.calls), before)

    def test_changed_weights_and_resealed_wrong_task_manifest_cannot_be_called(self):
        new_input = self.root / "fresh.json"
        write_json(new_input, {"left": 5, "right": 1})
        before = len(self.executor.calls)
        (self.run_dir / "artifacts/weights/projection.json").write_text("tampered")
        with self.client() as (_client, app):
            with self.assertRaisesRegex(HarnessError, "digest changed"):
                app.state.run_service.artifact_path(self.run_id, "weights/projection.json")
            with self.assertRaises(SampleInferenceBlocked) as failed:
                SampleInference(self.run_dir).run(new_input, sample_type="generic")
            self.assertEqual(failed.exception.report["status"], "blocked")
        self.assertEqual(len(self.executor.calls), before)
        another = self.run_fixture()
        model_path = another / "artifacts/generic_model.json"
        model = read_json(model_path)
        model["task_id"] = "foreign-owner"
        model["model_sha256"] = fixtures.digest({key: value for key, value in model.items() if key != "model_sha256"})
        write_json(model_path, model)
        run_manifest = read_json(another / "run_manifest.json")
        run_manifest["artifacts"]["generic_model.json"] = {"sha256": sha256_file(model_path), "bytes": model_path.stat().st_size}
        write_json(another / "run_manifest.json", run_manifest)
        before = len(self.executor.calls)
        with self.client():
            with self.assertRaisesRegex(SampleInferenceBlocked, "another task, run or execution bundle"):
                SampleInference(another).run(new_input, sample_type="generic")
        self.assertEqual(len(self.executor.calls), before, "a self-consistent hash cannot override the model owner")

    def test_media_route_is_task_owned_and_detects_output_tamper(self):
        with self.client() as (client, app):
            report = self._authorize_and_predict(client)
            media = report["artifacts"][0]
            foreign_task = app.state.training_workspace.tasks_dir / "other-owner" / "task.json"
            write_json(foreign_task, {"task_id": "other-owner", "run_ids": []})
            self.assertEqual(client.get(media["url"].replace(f"/tasks/{self.owner}/", "/tasks/other-owner/")).status_code, 409)
            adapter = SampleInference(self.run_dir)
            path = generic_sample_artifact(adapter, report["check_id"], DeliveryExecutor.media_name)
            path.write_bytes(b"changed")
            self.assertEqual(client.get(media["url"]).status_code, 409)
            with self.assertRaises(FileNotFoundError):
                generic_sample_artifact(adapter, report["check_id"], "../weights/projection.json")

    def test_inference_reference_from_another_model_cannot_enter_the_bundle(self):
        with self.client() as (client, _app):
            report = self._authorize_and_predict(client)
        inference = InferenceCheck(self.run_dir).get(report["inference_check_id"])
        inference["model"]["sha256"] = "0" * 64
        InferenceCheck(self.run_dir)._persist(inference)
        with self.assertRaisesRegex(EvidenceError, "current run model"):
            ArtifactBundleBuilder(self.run_dir).build(inference_check_id=report["inference_check_id"])

    def set_frozen_bundle(self, files, *, container_executable="/usr/local/bin/python"):
        value = deepcopy(self.contract["execution_spec"]["bundle"])
        value["files"] = files
        for argv in value["stages"].values():
            argv[0] = container_executable
            argv.extend(["--scratch", "/tmp/studio-cache"])
        bundle = ExecutionBundle.from_dict(value)
        self.contract["execution_spec"].update(bundle=bundle.to_dict(), bundle_sha256=bundle.digest)
        return bundle

    def reseal_artifacts_without_changing_frozen_contract(self, run_dir, changed):
        # Simulate tampered/self-consistent artifact metadata. Source authority
        # must still come from the separate immutable contract snapshot.
        model_path = run_dir / "artifacts/generic_model.json"
        model = read_json(model_path)
        for record in model["artifacts"]:
            if record["path"] in changed:
                path = run_dir / "artifacts" / record["path"]
                record.update(sha256=sha256_file(path), bytes=path.stat().st_size)
        model["model_sha256"] = fixtures.digest({key: value for key, value in model.items() if key != "model_sha256"})
        write_json(model_path, model)
        manifest_path = run_dir / "run_manifest.json"
        manifest = read_json(manifest_path)
        for name in {*changed, "generic_model.json"}:
            path = run_dir / "artifacts" / name
            manifest["artifacts"][name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        write_json(manifest_path, manifest)
        EvaluationReport(run_dir).build(minimum_test_samples=20)

    def test_frozen_container_source_and_argv_ship_exact_bytes_and_digest(self):
        files = {
            "unseen.py": '#!/usr/bin/env python3\r\nCACHE = "/tmp/studio-cache"\r\nFONT = "/usr/share/fonts/example.ttf"\r\nRUNTIME = "/opt/runtime"\r\nDOCS = "https://example.com/model"\r\ndef predict(x):\r\n    if x:\r\n        return x\r\n    else:\r\n        return 0\r\n',
            "launch.sh": '#!/bin/sh\n/usr/local/bin/python /workspace/source/unseen.py --cache /tmp/studio-cache\n',
        }
        bundle = self.set_frozen_bundle(files)
        run_dir = self.run_fixture()
        builder = ArtifactBundleBuilder(run_dir)
        record = builder.build()
        with ZipFile(builder.bundle_path(record["bundle_id"])) as archive:
            for name, source in files.items():
                self.assertEqual(archive.read("artifacts/source/" + name), source.encode("utf-8"))
            portable = json.loads(archive.read("artifacts/generic_execution.json"))
            self.assertEqual(portable["bundle"]["files"], files)
            self.assertEqual(portable["bundle"]["stages"], bundle.to_dict()["stages"])
            self.assertEqual(ExecutionBundle.from_dict(portable["bundle"]).digest, bundle.digest)
            self.assertEqual(archive.read("artifacts/generic_execution.json"), (run_dir / "artifacts/generic_execution.json").read_bytes())

    def test_frozen_source_does_not_exempt_private_host_roots_or_user_home(self):
        for index, private_path in enumerate(["/Users/private/account.csv", "/home/private/data.csv", "/private/var/folders/private/cache", "/var/folders/private/cache", "C:/Users/private/data.csv", "C:\\private\\data.csv", str(self.root / "workspace/tasks")]):
            with self.subTest(private_path=private_path):
                # Use a non-.py source too: being a .sh/no-extension source
                # cannot bypass the mandatory private-root scan.
                self.set_frozen_bundle({"unseen.py": "# no host execution\n", "launch.sh": f'CACHE = {private_path!r}\n'})
                run_dir = self.run_fixture()
                with self.assertRaisesRegex(EvidenceError, "missing required"):
                    ArtifactBundleBuilder(run_dir).build()
        private_home = self.root / "private-user-home"
        self.set_frozen_bundle({"unseen.py": f'HOME_CACHE = {str(private_home / "cache")!r}\n'})
        run_dir = self.run_fixture()
        with patch("model_harness.evidence.Path.home", return_value=private_home), self.assertRaises(EvidenceError):
            ArtifactBundleBuilder(run_dir).build()

    def test_source_role_label_alone_cannot_bypass_metadata_path_filter(self):
        self.contract["execution_spec"]["artifacts"].append({"path": "claimed_source.py", "role": "inference_source", "export": True})
        self.executor.additional_outputs["train"] = {"claimed_source.py": b'CACHE = "/tmp/not-frozen-source"\n'}
        run_dir = self.run_fixture()
        with self.assertRaisesRegex(EvidenceError, "missing required"):
            ArtifactBundleBuilder(run_dir).build()

    def test_regular_generic_metadata_and_raw_data_keep_the_original_privacy_filter(self):
        self.contract["execution_spec"]["artifacts"].extend([
            {"path": "report.json", "role": "report", "export": True},
            {"path": "raw.csv", "role": "raw_data", "export": True},
            {"path": "test/hidden.txt", "role": "report", "export": True},
            {"path": "logs/hidden.txt", "role": "report", "export": True},
        ])
        self.executor.additional_outputs["train"] = {
            "report.json": {"interpreter": "/usr/local/bin/python", "scratch": "/tmp/private-metadata"},
            "raw.csv": b"raw,user-data\n", "test/hidden.txt": b"held-out data", "logs/hidden.txt": b"private log",
        }
        run_dir = self.run_fixture()
        builder = ArtifactBundleBuilder(run_dir); record = builder.build()
        with ZipFile(builder.bundle_path(record["bundle_id"])) as archive:
            names = set(archive.namelist())
            for name in ["report.json", "raw.csv", "test/hidden.txt", "logs/hidden.txt", "private/debug.json"]:
                self.assertNotIn("artifacts/" + name, names)
        self.assertTrue(any(item["path"] == "artifacts/report.json" and item["reason"] == "absolute path content" for item in record["manifest"]["excluded"]))

    def test_resealed_source_or_portable_bundle_cannot_override_frozen_contract(self):
        self.set_frozen_bundle({"unseen.py": 'CACHE = "/tmp/original"\n'})
        source_run = self.run_fixture()
        (source_run / "artifacts/source/unseen.py").write_text('CACHE = "/tmp/replaced"\n')
        self.reseal_artifacts_without_changing_frozen_contract(source_run, {"source/unseen.py"})
        with self.assertRaisesRegex(EvidenceError, "frozen execution bundle"):
            ArtifactBundleBuilder(source_run).build()
        portable_run = self.run_fixture()
        path = portable_run / "artifacts/generic_execution.json"
        portable = read_json(path)
        portable["bundle"]["stages"]["predict"].append("--different")
        portable["bundle_sha256"] = ExecutionBundle.from_dict(portable["bundle"]).digest
        write_json(path, portable)
        self.reseal_artifacts_without_changing_frozen_contract(portable_run, {"generic_execution.json"})
        with self.assertRaisesRegex(EvidenceError, "frozen Run contract"):
            ArtifactBundleBuilder(portable_run).build()

    def test_source_cannot_change_between_privacy_check_and_copy(self):
        self.set_frozen_bundle({"unseen.py": 'CACHE = "/tmp/frozen"\n'})
        run_dir = self.run_fixture()
        original_copy = shutil.copyfile
        def replace_before_copy(source, target):
            if Path(source) == run_dir / "artifacts/source/unseen.py":
                Path(source).write_text('CACHE = "/tmp/replaced-after-check"\n')
            return original_copy(source, target)
        builder = ArtifactBundleBuilder(run_dir)
        with patch("model_harness.evidence.shutil.copyfile", side_effect=replace_before_copy), self.assertRaisesRegex(EvidenceError, "changed after Run integrity"):
            builder.build()
        self.assertEqual(builder.list(), [])

    def test_delivery_rejects_omission_of_required_model_files(self):
        self.contract["execution_spec"]["artifacts"][0]["export"] = False
        another = self.run_fixture()
        with self.assertRaisesRegex(EvidenceError, "missing required model or inference dependencies"):
            ArtifactBundleBuilder(another).build()


if __name__ == "__main__":
    unittest.main()
