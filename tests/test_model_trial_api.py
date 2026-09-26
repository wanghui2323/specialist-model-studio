"""HTTP boundary fixtures, not real DSH approval or OCI/model execution evidence."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from model_harness.server import create_app
from tests.test_model_trials import FakeExecutor, PNG


@unittest.skipIf(TestClient is None, "server extra is not installed")
class ModelTrialApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token = "fixture-agent-bridge-token-not-a-real-secret"
        with patch.dict("os.environ", {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": self.token}), patch("model_harness.workspace.OCIJobConfig.from_environment", return_value=None):
            self.app = create_app(Path(self.temp.name) / "runs")
        self.workspace = self.app.state.training_workspace
        self.runtime = self.app.state.conversation_runtime
        self.executor = FakeExecutor()
        self.executor.capability = lambda: {"available": True, "reason": "fixture only", "runtime_digest": self.executor.runtime_digest}
        self.workspace.model_trial_executor = self.executor
        self.workspace.model_trials.executor = self.executor
        self.workspace.model_trials.context_provider = self.context
        self.workspace.model_trials.payload_provider = lambda _task, record, _bytes: json.dumps(record).encode()
        for name in ("start", "stop"):
            mocked = patch.object(self.runtime, name); mocked.start(); self.addCleanup(mocked.stop)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.task_id = self.create_task()
        self.base = f"/tasks/{self.task_id}/model-trials"
        self.headers = {"X-Model-Harness-Agent-Token": self.token}

    def create_task(self):
        response = self.client.post("/tasks", json={"name": "API试跑边界测试", "business_goal": "验证固定模型的单张图片输入"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["task"]["task_id"]

    def context(self, task_id):
        owner = self.runtime.store.load_task(task_id)
        return {"task_id": task_id, "spec_revision": owner.get("current_spec_revision", 1), "dataset_id": None,
                "model_asset_id": "fixture-asset", "model_manifest_sha256": "1" * 64, "model_sha256": "2" * 64,
                "config_sha256": "3" * 64, "model_repo_id": "fixture/model", "resolved_commit": "4" * 40,
                "binding_sha256": "5" * 64, "archived": bool(owner.get("archived_at_utc"))}

    def create_body(self, **changes):
        return {"filename": "sample.png", "input_base64": base64.b64encode(PNG).decode(), "request_id": str(uuid4()), **changes}

    def create_trial(self, **changes):
        response = self.client.post(self.base, json=self.create_body(**changes))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["model_trial"]

    def execution_body(self, record, **changes):
        return {"expected_plan_sha256": record["plan_sha256"], "approval": {"actor": "user", "checkpoint_id": "call-fixture"},
                "lineage": {"task_id": self.task_id, "session_id": "root-fixture", "call_id": "call-fixture"}, **changes}

    def call_event(self, record, **changes):
        return {"task_id": self.task_id, "session_id": "root-fixture", "agent_run_id": "agent-run-fixture", "turn_id": "turn-fixture", "call_id": "call-fixture",
                "type": "tool_call", "event_type": "tool_call", "actor_role": "orchestrator", "delegation_id": None, "parent_delegation_id": None,
                "payload": {"tool_name": "model_harness_execute_model_trial", "arguments": {"task_id": self.task_id, "trial_id": record["trial_id"], "expected_plan_sha256": record["plan_sha256"]}}, **changes}

    def execute(self, record, *, body=None, events=None, session="root-fixture", headers=None):
        with patch.object(self.runtime, "session_for", return_value=session), patch.object(self.runtime.store, "current_projection_events", return_value=[self.call_event(record)] if events is None else events):
            return self.client.post(f"{self.base}/{record['trial_id']}/execute", json=body or self.execution_body(record), headers=self.headers if headers is None else headers)

    def wait_terminal(self, record):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = self.workspace.model_trials.get(self.task_id, record["trial_id"])
            if current["status"] in {"succeeded", "failed", "cancelled", "timed_out", "observation_degraded"}:
                return current
            time.sleep(0.005)
        self.fail("fake executor did not settle")

    def test_capability_create_and_get_are_persisted_but_never_authorize_or_create_run(self):
        capability = self.client.get("/model-trials/capability")
        self.assertEqual(capability.status_code, 200)
        self.assertTrue(capability.json()["available"])
        record = self.create_trial()
        self.assertEqual(record["status"], "pending_approval")
        self.assertIsNone(record["approval"])
        self.assertFalse(record["training_run_created"])
        directory = self.workspace.root / "tasks" / self.task_id / "model_trials" / record["trial_id"]
        before = {path.relative_to(directory): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        for _ in range(2):
            self.assertEqual(self.client.get(f"{self.base}/{record['trial_id']}").json()["model_trial"], record)
            self.assertEqual(self.client.get(self.base).json()["model_trials"], [record])
        self.assertEqual({path.relative_to(directory): path.read_bytes() for path in directory.rglob("*") if path.is_file()}, before)
        self.assertEqual(self.executor.calls, [])
        self.assertFalse(self.client.get(f"/tasks/{self.task_id}").json()["task"].get("run_ids"))

    def test_create_idempotency_and_request_conflict(self):
        body = self.create_body(); first = self.client.post(self.base, json=body)
        second = self.client.post(self.base, json=body)
        self.assertEqual(first.json()["model_trial"]["trial_id"], second.json()["model_trial"]["trial_id"])
        conflict = self.client.post(self.base, json={**body, "filename": "different.png"})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(len(self.client.get(self.base).json()["model_trials"]), 1)

    def test_invalid_create_inputs_and_forged_approval_fields_leave_no_trial(self):
        invalid = [self.create_body(input_base64="%%%"), self.create_body(input_base64=3), self.create_body(filename="../sample.png"),
                   self.create_body(input_base64=base64.b64encode(b"not an image content").decode()), self.create_body(request_id="../request"),
                   self.create_body(approval_confirmed=True), self.create_body(approval={"actor": "user"}), self.create_body(extra="unexpected")]
        for body in invalid:
            with self.subTest(body=body):
                response = self.client.post(self.base, json=body)
                self.assertEqual(response.status_code, 409, response.text)
        oversized = self.client.post(self.base, content=b"x" * (6 * 1024 * 1024 + 1), headers={"Content-Type": "application/json"})
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.client.get(self.base).json()["model_trials"], [])
        self.assertEqual(self.executor.calls, [])

    def test_missing_task_and_cross_task_trial_do_not_create_directories(self):
        missing = "task-does-not-exist"
        self.assertEqual(self.client.get(f"/tasks/{missing}/model-trials").status_code, 404)
        self.assertIn(self.client.post(f"/tasks/{missing}/model-trials", json=self.create_body()).status_code, {404, 409})
        self.assertFalse((self.workspace.root / "tasks" / missing).exists())
        record = self.create_trial(); other = self.create_task()
        for method, suffix in (("get", ""), ("post", "/cancel"), ("post", "/retry")):
            response = getattr(self.client, method)(f"/tasks/{other}/model-trials/{record['trial_id']}{suffix}", **({"json": {"request_id": str(uuid4())}} if method == "post" else {}))
            self.assertIn(response.status_code, {404, 409})
        self.assertEqual(self.workspace.model_trials.get(self.task_id, record["trial_id"])["status"], "pending_approval")

    def test_execute_requires_configured_bridge_token_even_with_forged_user_body(self):
        record = self.create_trial()
        for headers in ({}, {"X-Model-Harness-Agent-Token": "wrong"}):
            response = self.execute(record, headers=headers)
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.executor.calls, [])
        self.assertIsNone(self.workspace.model_trials.get(self.task_id, record["trial_id"])["approval"])

    def test_token_without_observed_root_call_or_unique_full_lineage_is_rejected(self):
        record = self.create_trial(); call = self.call_event(record)
        cases = [[], [{**call, "session_id": "child-fixture"}], [{**call, "task_id": "other"}],
                 [{**call, "agent_run_id": None}], [{**call, "turn_id": None}], [{**call, "call_id": "different"}],
                 [call, {**call, "agent_run_id": "other-run"}], [call, {**call, "turn_id": "other-turn"}]]
        for events in cases:
            with self.subTest(events=events):
                response = self.execute(record, events=events)
                self.assertEqual(response.status_code, 409, response.text)
        body = self.execution_body(record); del body["lineage"]
        self.assertEqual(self.execute(record, body=body).status_code, 409)
        body = self.execution_body(record); body["lineage"]["agent_run_id"] = "forged"
        self.assertEqual(self.execute(record, body=body).status_code, 409)
        self.assertEqual(self.execute(record, session="different-root").status_code, 409)
        self.assertEqual(self.executor.calls, [])

    def test_wrong_approval_actor_checkpoint_or_plan_digest_is_rejected(self):
        record = self.create_trial()
        for field, value in (("actor", "assistant"), ("checkpoint_id", "another-call")):
            body = self.execution_body(record); body["approval"][field] = value
            self.assertEqual(self.execute(record, body=body).status_code, 409)
        body = self.execution_body(record, expected_plan_sha256="0" * 64)
        self.assertEqual(self.execute(record, body=body).status_code, 409)
        self.assertEqual(self.executor.calls, [])

    def test_real_dsh_json_string_arguments_bind_exact_trial_scope(self):
        record = self.create_trial()
        event = self.call_event(record)
        event["payload"]["arguments"] = json.dumps(event["payload"]["arguments"], indent=2)
        response = self.execute(record, events=[event])
        self.assertEqual(response.status_code, 200, response.text)
        terminal = self.wait_terminal(record)
        self.assertEqual(terminal["status"], "succeeded")
        self.assertEqual(terminal["approval"]["lineage"]["call_id"], "call-fixture")

    def test_ambiguous_or_invalid_dsh_argument_strings_never_authorize(self):
        record = self.create_trial()
        event = self.call_event(record)
        args = event["payload"]["arguments"]
        malformed = ["{", "[]", "null", json.dumps({**args, "extra": True}),
                     json.dumps({**args, "trial_id": "different"}), "[" * 2000,
                     json.dumps(args)[:-1] + ', "task_id": ' + json.dumps(self.task_id) + '}',
                     " " * 16385 + json.dumps(args)]
        for raw in malformed:
            with self.subTest(raw=raw[:100]):
                changed = deepcopy(event)
                changed["payload"]["arguments"] = raw
                self.assertEqual(self.execute(record, events=[changed]).status_code, 409)
        self.assertEqual(self.executor.calls, [])

    def test_exact_root_call_resolves_canonical_lineage_and_replay_does_not_execute_twice(self):
        record = self.create_trial(); response = self.execute(record)
        self.assertEqual(response.status_code, 200, response.text)
        current = self.wait_terminal(record)
        self.assertEqual(current["status"], "succeeded")
        self.assertEqual(current["approval"]["lineage"], {"task_id": self.task_id, "session_id": "root-fixture", "call_id": "call-fixture", "agent_run_id": "agent-run-fixture", "turn_id": "turn-fixture"})
        self.assertEqual(current["approval"]["bridge_token_sha256"], hashlib.sha256(self.token.encode()).hexdigest())
        self.assertEqual(self.execute(record).status_code, 200)
        self.assertEqual(len(self.executor.calls), 1)
        second = self.create_trial()
        self.assertEqual(self.execute(second).status_code, 409)
        self.assertFalse(current["result"]["business_quality_accepted"])

    def test_result_only_or_delegated_call_and_wrong_observed_arguments_cannot_authorize(self):
        record = self.create_trial(); call = self.call_event(record)
        malformed = [{**call, "type": "tool_result", "event_type": "tool_result"}, {**call, "delegation_id": "child-delegation"}, {**call, "actor_role": "research"}]
        for field, value in (("trial_id", "trial-" + "0" * 32), ("expected_plan_sha256", "0" * 64), ("task_id", "other")):
            event = deepcopy(call); event["payload"]["arguments"][field] = value; malformed.append(event)
        for event in malformed:
            with self.subTest(event=event):
                response = self.execute(record, events=[event])
                self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.executor.calls, [])

    def test_cancel_pending_plan_is_idempotent_and_retry_needs_fresh_approval(self):
        record = self.create_trial()
        self.assertEqual(self.client.post(f"{self.base}/{record['trial_id']}/retry", json={"request_id": str(uuid4())}).status_code, 409)
        first = self.client.post(f"{self.base}/{record['trial_id']}/cancel", json={})
        second = self.client.post(f"{self.base}/{record['trial_id']}/cancel", json={})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["model_trial"]["status"], "cancelled")
        retried = self.client.post(f"{self.base}/{record['trial_id']}/retry", json={"request_id": str(uuid4())})
        self.assertEqual(retried.status_code, 200, retried.text)
        new = retried.json()["model_trial"]
        self.assertNotEqual(new["trial_id"], record["trial_id"])
        self.assertEqual(new["parent_trial_id"], record["trial_id"])
        self.assertEqual(new["status"], "pending_approval")
        self.assertIsNone(new["approval"])
        self.assertEqual(new["input"], record["input"])
        self.assertEqual(self.executor.calls, [])

    def test_running_trial_blocks_archive_and_cancel_settles_before_retry(self):
        self.executor.gate = Event()
        self.addCleanup(self.executor.gate.set)
        record = self.create_trial()
        started = self.execute(record)
        self.assertEqual(started.status_code, 200, started.text)
        self.assertTrue(self.executor.entered.wait(1), "fake execution reached its gate")
        archive = self.client.post(f"/tasks/{self.task_id}/archive")
        self.assertEqual(archive.status_code, 409, archive.text)
        cancellation = self.client.post(f"{self.base}/{record['trial_id']}/cancel", json={})
        self.assertEqual(cancellation.status_code, 200)
        self.assertEqual(cancellation.json()["model_trial"]["status"], "cancel_requested")
        stopped = self.wait_terminal(record)
        self.assertEqual(stopped["status"], "cancelled")
        self.assertTrue(stopped["evidence"]["cleanup_confirmed"])
        self.assertEqual(self.client.post(f"/tasks/{self.task_id}/archive").status_code, 200)
        self.assertEqual(len(self.executor.calls), 1)

    def test_observation_unknown_get_does_not_recover_and_reconcile_never_restarts(self):
        self.executor.raised = True
        record = self.create_trial()
        self.assertEqual(self.execute(record).status_code, 200)
        unknown = self.wait_terminal(record)
        self.assertEqual(unknown["status"], "observation_degraded")
        self.assertEqual(self.client.get(f"{self.base}/{record['trial_id']}").status_code, 200)
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.executor.recover_calls, [])
        self.assertEqual(self.client.post(f"{self.base}/{record['trial_id']}/retry", json={"request_id": str(uuid4())}).status_code, 409)
        response = self.client.post(f"{self.base}/{record['trial_id']}/reconcile", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["model_trial"]["status"], "cancelled")
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(self.executor.recover_calls, [(self.task_id, record["trial_id"])])

    def test_archive_blocks_all_trial_writes_but_preserves_reads_and_restore_never_runs(self):
        record = self.create_trial()
        archived = self.client.post(f"/tasks/{self.task_id}/archive")
        self.assertEqual(archived.status_code, 200, archived.text)
        for suffix, body in (("", self.create_body()), (f"/{record['trial_id']}/execute", self.execution_body(record)),
                             (f"/{record['trial_id']}/cancel", {}), (f"/{record['trial_id']}/retry", {"request_id": str(uuid4())}), (f"/{record['trial_id']}/reconcile", {})):
            response = self.client.post(self.base + suffix, json=body, headers=self.headers)
            self.assertEqual(response.status_code, 409, response.text)
        read = self.client.get(f"{self.base}/{record['trial_id']}")
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json()["model_trial"]["trial_id"], record["trial_id"])
        self.assertTrue(read.json()["model_trial"]["stale"])
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.client.post(f"/tasks/{self.task_id}/restore").status_code, 200)
        self.assertEqual(self.workspace.model_trials.get(self.task_id, record["trial_id"])["status"], "pending_approval")
        self.assertEqual(self.executor.calls, [])

    def test_reconcile_pending_plan_is_read_only_and_never_dispatches_or_recovers(self):
        record = self.create_trial()
        response = self.client.post(f"{self.base}/{record['trial_id']}/reconcile", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model_trial"], record)
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(self.executor.recover_calls, [])


if __name__ == "__main__":
    unittest.main()
