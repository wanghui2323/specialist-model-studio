from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from tests import test_generic_delivery as fixtures
from model_harness.io_utils import read_json


class BlockingPredictionExecutor(fixtures.DeliveryExecutor):
    """Transport fixture only; no submitted source is executed on the host."""
    def __init__(self):
        super().__init__()
        self.prediction_started = Event()
        self.prediction_cancelled = Event()

    def run_stage(self, bundle, stage, **kwargs):
        if stage == "predict":
            self.prediction_started.set()
            deadline = time.monotonic() + 5
            signal = kwargs.get("cancel_event")
            while signal is None or not signal.is_set():
                if time.monotonic() >= deadline:
                    raise AssertionError("prediction did not receive its task stop signal")
                time.sleep(.005)
            self.prediction_cancelled.set()
        evidence = super().run_stage(bundle, stage, **kwargs)
        if stage == "predict":
            evidence.update(status="cancelled", errors=["fixture_worker_acknowledged_stop"], exit_code=137)
            evidence["evidence_sha256"] = fixtures.fixtures.digest({k: v for k, v in evidence.items() if k != "evidence_sha256"})
        return evidence


class GenericInferenceCancellationTests(unittest.TestCase):
    context = fixtures.GenericDeliveryTests.context
    run_fixture = fixtures.GenericDeliveryTests.run_fixture
    client = fixtures.GenericDeliveryTests.client
    _upload = fixtures.GenericDeliveryTests._upload

    def setUp(self):
        fixtures.GenericDeliveryTests.setUp(self)
        self.executor = BlockingPredictionExecutor()
        self.plugin.executor = self.executor

    def test_prediction_keeps_http_and_task_reads_responsive_and_stop_reaches_worker(self):
        with self.client() as (client, app), ThreadPoolExecutor(max_workers=3) as pool:
            uploaded = self._upload(client).json()["inference_input"]
            route = f"/tasks/{self.owner}/runs/{self.run_id}"
            granted = client.post(route + "/sample-inference-authorizations", json={
                "inference_input_id": uploaded["inference_input_id"], "inference_input_sha256": uploaded["sha256"],
                "approval": {"actor": "user", "checkpoint_id": "stop-inference-fixture"}},
                headers={"X-Model-Harness-Agent-Token": "generic-delivery-test-token"}).json()
            authorization = granted["sample_inference_authorization"]
            body = {"sample_inference_authorization_id": authorization["authorization_id"],
                    "authorization_token": granted["authorization_token"],
                    "sample_inference_request_sha256": authorization["scope_sha256"]}
            job = pool.submit(client.post, route + "/inference-inputs/" + uploaded["inference_input_id"] + "/execute", json=body)
            self.assertTrue(self.executor.prediction_started.wait(2))
            workspace = app.state.training_workspace
            self.assertEqual(pool.submit(client.get, "/health").result(timeout=1).status_code, 200)
            self.assertEqual(pool.submit(workspace.get_task, self.owner).result(timeout=1)["task_id"], self.owner)
            actions = workspace.task_background_actions(self.owner)
            active = [row for row in actions if row["action_type"] == "sample_inference"]
            self.assertEqual(len(active), 1)
            self.assertTrue(active[0]["running"])
            app.state.run_service.cancel_sample_inferences("different-owner")
            self.assertFalse(self.executor.prediction_cancelled.is_set())
            workspace.cancel_task_background_actions(self.owner)
            self.assertTrue(self.executor.prediction_cancelled.wait(2))
            stopped = job.result(timeout=2)
            self.assertEqual(stopped.status_code, 422, stopped.text)
            self.assertTrue(stopped.json()["sample_inference"]["blocked"])
            self.assertNotEqual(stopped.json()["sample_inference"]["status"], "passed")
            self.assertEqual(app.state.run_service.sample_inference_background_actions(self.owner), [])
            records = list((self.run_dir / "evidence/sample_jobs").glob("sample-job-*.json"))
            self.assertEqual(len(records), 1)
            terminal = read_json(records[0])
            self.assertEqual(terminal["status"], "cancelled")
            self.assertTrue(terminal["cancel_requested"])
            self.assertFalse(terminal["running"])
            self.assertNotIn("cancel_event", terminal)
            replay = client.post(route + "/inference-inputs/" + uploaded["inference_input_id"] + "/execute", json=body)
            self.assertEqual(replay.status_code, 409)
