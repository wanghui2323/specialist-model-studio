from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from model_harness.model_trials import (
    MAX_INPUT_BYTES, ModelTrialConflictError, ModelTrialError, ModelTrialIntegrityError, ModelTrialService,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-header-only-no-host-decoder"
CONTAINER = "c" * 64
IMAGE = "sha256:" + "d" * 64


class FakeExecutor:
    def __init__(self, *, gate=None, honour_cancel=True, mutate=None, raised=False, no_callback=False):
        self.config = SimpleNamespace(memory_bytes=536870912, timeout_seconds=30, pids_limit=128)
        self.runtime_digest = "a" * 64
        self.gate = gate
        self.honour_cancel = honour_cancel
        self.mutate = mutate
        self.raised = raised
        self.no_callback = no_callback
        self.entered = threading.Event()
        self.finished = threading.Event()
        self.calls = []
        self.recover_calls = []
        self.recovery_confirmed = True

    def outcome(self, *, status="succeeded", stdout="", cleanup=True):
        return {"status": status, "exit_code": 0, "stdout": stdout, "stderr": "",
                "container_id": CONTAINER, "image_id": IMAGE, "runtime_digest": self.runtime_digest,
                "cleanup_confirmed": cleanup, "error_code": None,
                "started_at_utc": "2026-09-12T01:00:00Z", "finished_at_utc": "2026-09-12T01:00:01Z"}

    def execute(self, *, job_id, task_id, payload, cancel_event, on_started):
        record = json.loads(payload)
        self.calls.append({"job_id": job_id, "task_id": task_id, "record": record, "cancel_event": cancel_event})
        if not self.no_callback:
            for phase in ("created", "running"):
                on_started({"phase": phase, "container_id": CONTAINER, "image_id": IMAGE,
                            "runtime_digest": self.runtime_digest, "started_at_utc": "2026-09-12T01:00:00Z"})
        self.entered.set()
        if self.gate:
            while not self.gate.wait(0.01):
                if self.honour_cancel and cancel_event.is_set():
                    break
        try:
            if self.raised:
                raise RuntimeError("unsafe detail /Users/private-user/model.onnx")
            values = [0.25, -0.5]
            result = {"schema_version": "1.0", "task_id": task_id, "trial_id": job_id,
                      "plan_sha256": record["plan_sha256"], "status": "succeeded",
                      "input_sha256": record["input"]["sha256"], "model_sha256": record["context"]["model_sha256"],
                      "config_sha256": record["context"]["config_sha256"], "provider": "CPUExecutionProvider",
                      "features": values, "classes": ["a", "b"], "output_sha256": hashlib.sha256(struct.pack("<2f", *values)).hexdigest(),
                      "timing": {"inference_ms": 1.25}}
            outcome = self.outcome(stdout=json.dumps(result))
            if cancel_event.is_set():
                outcome.update(status="cancelled", exit_code=137)
            if self.mutate:
                self.mutate(result, outcome)
            return outcome
        finally:
            self.finished.set()

    def recover(self, *, job_id, task_id):
        self.recover_calls.append((task_id, job_id))
        return self.outcome(status="cancelled" if self.recovery_confirmed else "observation_degraded", cleanup=self.recovery_confirmed)


class ModelTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contexts = {}
        for task_id in ("task-one", "task-two"):
            directory = self.root / "tasks" / task_id
            directory.mkdir(parents=True)
            (directory / "task.json").write_text('{"owned": true}\n', encoding="utf-8")
            self.contexts[task_id] = {"task_id": task_id, "spec_revision": 1, "dataset_id": None,
                                     "model_asset_id": "asset-one", "model_manifest_sha256": "1" * 64,
                                     "model_sha256": "2" * 64, "config_sha256": "3" * 64,
                                     "model_repo_id": "owner/model", "resolved_commit": "4" * 40,
                                     "binding_sha256": "5" * 64, "archived": False}
        self.services = []
        self.addCleanup(self.close_services)

    def close_services(self):
        for service in reversed(self.services):
            for call in getattr(service.executor, "calls", []):
                call["cancel_event"].set()
            if getattr(service.executor, "gate", None):
                service.executor.gate.set()
            service.close(timeout=1)

    def context(self, task_id):
        value = self.contexts[task_id]
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)

    def service(self, executor=None, *, start=True, payload_provider=None, configured=True):
        selected = (executor or FakeExecutor()) if configured else None
        instance = ModelTrialService(self.root, selected, self.context,
                                     payload_provider or (lambda _task, record, _data: json.dumps(record).encode()),
                                     lock=threading.RLock())
        self.services.append(instance)
        if start:
            instance.start()
        return instance

    def create(self, service, *, task="task-one", request="request-one", data=PNG, filename="sample.png", parent=None):
        return service.create(task, filename=filename, input_bytes=data, request_id=request, parent_trial_id=parent)

    def approval(self, record, **changes):
        return {"actor": "user", "verified_by": "agent_bridge_token", "bridge_token_sha256": "6" * 64,
                "checkpoint_id": "checkpoint-" + record["trial_id"], "scope_sha256": record["plan_sha256"], **changes}

    def approve(self, service, record, approval=None):
        return service.approve_and_start(record["task_id"], record["trial_id"], expected_plan_sha256=record["plan_sha256"],
                                         approval=approval or self.approval(record))

    def wait_status(self, service, record, statuses=None):
        expected = statuses or {"succeeded", "failed", "cancelled", "timed_out", "observation_degraded"}
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = service.get(record["task_id"], record["trial_id"])
            if current["status"] in expected:
                # The durable outcome is written before _work's finally clears
                # its worker identity. Terminal-status assertions below also
                # inspect stop truth, so wait for both independent observations.
                action = next(item for item in service.background_actions(record["task_id"])
                              if item["trial_id"] == record["trial_id"])
                if not action["worker_running"]:
                    return current
            time.sleep(0.005)
        self.fail(f"trial did not reach {expected}: {current}")

    def directory(self, record):
        return self.root / "tasks" / record["task_id"] / "model_trials" / record["trial_id"]

    def test_create_is_durable_immutable_no_run_and_reuses_exact_idempotent_request(self):
        service = self.service()
        task_before = (self.root / "tasks/task-one/task.json").read_bytes()
        record = self.create(service)
        directory = self.directory(record)
        self.assertEqual(record["status"], "pending_approval")
        self.assertIsNone(record["approval"])
        self.assertIsNone(record["result"])
        self.assertFalse(record["training_run_created"])
        self.assertEqual(service.executor.calls, [])
        immutable = (directory / "plan.json").read_bytes()
        self.assertEqual(service.read_input("task-one", record["trial_id"]), PNG)
        self.assertEqual(self.create(service)["trial_id"], record["trial_id"])
        self.assertEqual((directory / "plan.json").read_bytes(), immutable)
        reloaded = self.service(start=False)
        self.assertEqual(reloaded.get("task-one", record["trial_id"]), service.get("task-one", record["trial_id"]))
        self.assertEqual(len(reloaded.list("task-one")), 1)
        self.assertEqual((self.root / "tasks/task-one/task.json").read_bytes(), task_before)
        self.assertFalse((self.root / "runs").exists())
        self.assertFalse(any(path.name in {"run_state.json", "task_contract.json"} for path in directory.rglob("*")))

    def test_missing_task_unsafe_identifiers_and_unconfigured_runtime_never_create_plan(self):
        service = self.service()
        for task in ("missing", "..", "../task-one", "/task-one", "task\\one", "task\x00one"):
            with self.subTest(task=task), self.assertRaises(ModelTrialError):
                self.create(service, task=task)
        self.assertFalse((self.root / "tasks/missing").exists())
        absent = self.service(configured=False)
        with self.assertRaisesRegex(ModelTrialError, "runtime_unconfigured"):
            self.create(absent)
        self.assertFalse((self.root / "tasks/task-one/model_trials").exists())
        for request in ("", "../request", "with space"):
            with self.assertRaises(ModelTrialError):
                self.create(service, request=request)

    def test_input_magic_limit_and_filename_guard_without_host_decoder(self):
        service = self.service()
        for filename, data in [("../sample.png", PNG), ("/sample.png", PNG), ("bad\x00.png", PNG), ("sample.exe", PNG),
                               ("sample.jpg", PNG), ("sample.png", b"not an image payload"), ("sample.png", PNG[:7]),
                               ("sample.png", PNG + b"x" * MAX_INPUT_BYTES)]:
            with self.subTest(filename=filename, size=len(data)), self.assertRaises(ModelTrialError):
                self.create(service, filename=filename, data=data)
        for index, (filename, data) in enumerate([("sample.jpg", b"\xff\xd8\xff" + b"x" * 12),
                                                 ("sample.webp", b"RIFF1234WEBPdata"), ("sample.bmp", b"BM" + b"x" * 12)]):
            self.assertEqual(self.create(service, request=f"format-{index}", filename=filename, data=data)["status"], "pending_approval")

    def test_context_input_filename_and_runtime_drift_do_not_reuse_request_or_approval(self):
        service = self.service()
        record = self.create(service)
        for changes in [{"data": PNG + b"new"}, {"filename": "renamed.png"}]:
            with self.assertRaises(ModelTrialConflictError):
                self.create(service, **changes)
        for key, replacement in [("spec_revision", 2), ("dataset_id", "dataset-new"), ("model_asset_id", "asset-new"),
                                 ("model_manifest_sha256", "7" * 64), ("model_sha256", "8" * 64),
                                 ("config_sha256", "9" * 64), ("binding_sha256", "0" * 64)]:
            previous = self.contexts["task-one"][key]
            self.contexts["task-one"][key] = replacement
            with self.subTest(key=key):
                self.assertTrue(service.get("task-one", record["trial_id"])["stale"])
                with self.assertRaises(ModelTrialConflictError):
                    self.approve(service, record)
                with self.assertRaises(ModelTrialConflictError):
                    self.create(service)
            self.contexts["task-one"][key] = previous
        service.executor.runtime_digest = "f" * 64
        with self.assertRaises(ModelTrialConflictError):
            self.approve(service, record)
        self.assertEqual(service.executor.calls, [])

    def test_archived_tasks_allow_reading_but_never_creating_or_approving(self):
        service = self.service()
        record = self.create(service)
        self.contexts["task-one"]["archived"] = True
        self.assertEqual(service.get("task-one", record["trial_id"])["status"], "pending_approval")
        self.assertEqual(service.read_input("task-one", record["trial_id"]), PNG)
        self.assertIn("task_archived", service.list("task-one")[0]["stale_reasons"])
        with self.assertRaisesRegex(ModelTrialConflictError, "task_archived"):
            self.approve(service, record)
        with self.assertRaisesRegex(ModelTrialConflictError, "task_archived"):
            self.create(service, request="new")

    def test_missing_binding_keeps_empty_list_and_historical_stale_read_available(self):
        service = self.service()
        self.contexts["task-two"] = RuntimeError("no compatible model")
        self.assertEqual(service.list("task-two"), [])
        self.assertEqual(service.background_actions("task-two"), [])
        record = self.create(service)
        self.contexts["task-one"] = RuntimeError("/Users/private-user/source missing")
        current = service.get("task-one", record["trial_id"])
        self.assertEqual(current["stale_reasons"], ["trial_context_unavailable"])
        self.assertNotIn("private-user", json.dumps(current))

    def test_cross_task_trial_and_input_reads_fail_closed(self):
        service = self.service()
        record = self.create(service)
        for operation in [lambda: service.get("task-two", record["trial_id"]),
                          lambda: service.read_input("task-two", record["trial_id"]),
                          lambda: service.cancel("task-two", record["trial_id"]),
                          lambda: service.approve_and_start("task-two", record["trial_id"], expected_plan_sha256=record["plan_sha256"], approval=self.approval(record))]:
            with self.assertRaises(ModelTrialError):
                operation()
        self.assertEqual(service.executor.calls, [])

    def test_forged_approval_digest_and_lineage_are_rejected(self):
        service = self.service()
        record = self.create(service)
        for changes in [{"actor": "agent"}, {"verified_by": "browser"}, {"bridge_token_sha256": ""},
                        {"bridge_token_sha256": "x" * 64}, {"checkpoint_id": ""}, {"scope_sha256": "0" * 64},
                        {"task_id": "task-two"}, {"trial_id": "another"}, {"model_sha256": "0" * 64}, {"decision": "rejected"},
                        {"approval_sha256": "0" * 64}]:
            with self.subTest(changes=changes), self.assertRaises(ModelTrialError):
                self.approve(service, record, self.approval(record, **changes))
        with self.assertRaises(ModelTrialConflictError):
            service.approve_and_start("task-one", record["trial_id"], expected_plan_sha256="0" * 64, approval=self.approval(record))
        self.assertEqual(service.executor.calls, [])

    def test_double_approval_same_proof_runs_once_but_changed_proof_cannot_replay(self):
        gate = threading.Event()
        executor = FakeExecutor(gate=gate)
        service = self.service(executor)
        record = self.create(service)
        decisions = []
        threads = [threading.Thread(target=lambda: decisions.append(self.approve(service, record))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(decisions), 2)
        self.assertTrue(executor.entered.wait(1))
        with self.assertRaises(ModelTrialConflictError):
            self.approve(service, record, self.approval(record, bridge_token_sha256="7" * 64))
        gate.set()
        completed = self.wait_status(service, record)
        self.assertEqual(completed["status"], "succeeded", completed)
        self.assertEqual(self.approve(service, record)["status"], "succeeded")
        self.assertEqual(len(executor.calls), 1)
        self.assertFalse(completed["business_quality_accepted"])
        self.assertFalse(completed["training_run_created"])
        self.assertEqual(completed["result"]["output_shape"], [2])
        self.assertTrue(completed["evidence"]["cleanup_confirmed"])

    def test_checkpoint_cannot_approve_a_second_plan(self):
        service = self.service()
        first = self.create(service)
        self.approve(service, first)
        self.wait_status(service, first)
        second = self.create(service, request="second")
        with self.assertRaisesRegex(ModelTrialConflictError, "checkpoint_already_consumed"):
            self.approve(service, second, self.approval(second, checkpoint_id=self.approval(first)["checkpoint_id"]))

    def test_plan_input_and_event_tampering_and_symlinks_fail_closed(self):
        for target in ("plan", "input", "event", "pointer", "symlink"):
            with self.subTest(target=target):
                service = self.service()
                record = self.create(service, request=target)
                directory = self.directory(record)
                if target == "plan":
                    value = json.loads((directory / "plan.json").read_text())
                    value["limits"]["cpus"] = 10
                    (directory / "plan.json").write_text(json.dumps(value))
                elif target == "input":
                    (directory / "input.blob").write_bytes(PNG + b"changed")
                elif target == "event":
                    value = json.loads((directory / "events/000001.json").read_text())
                    value["status"] = "succeeded"
                    (directory / "events/000001.json").write_text(json.dumps(value))
                elif target == "pointer":
                    (directory / "state.json").write_text("{}")
                else:
                    (directory / "input.blob").unlink()
                    (directory / "input.blob").symlink_to(self.root / "tasks/task-one/task.json")
                with self.assertRaises(ModelTrialError):
                    service.get("task-one", record["trial_id"])
                with self.assertRaises(ModelTrialError):
                    self.approve(service, record)
                # Keep each corruption case in a separate task-owned directory;
                # creating another record must also fail closed while it exists.
                for path in sorted(directory.rglob("*"), reverse=True):
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                directory.rmdir()

    def test_event_commit_survives_stale_atomic_pointer_without_rewriting_prior_events(self):
        service = self.service()
        record = self.create(service)
        directory = self.directory(record)
        initial = (directory / "state.json").read_bytes()
        initial_event = (directory / "events/000001.json").read_bytes()
        service.cancel("task-one", record["trial_id"])
        (directory / "state.json").write_bytes(initial)
        state = service.get("task-one", record["trial_id"])
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(state["state_revision"], 2)
        self.assertEqual((directory / "events/000001.json").read_bytes(), initial_event)
        self.assertEqual((directory / "state.json").read_bytes(), initial)

    def test_pending_cancel_and_retry_preserve_history_and_require_new_approval(self):
        service = self.service()
        parent = self.create(service)
        old_plan = (self.directory(parent) / "plan.json").read_bytes()
        cancelled = service.cancel("task-one", parent["trial_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(ModelTrialConflictError):
            self.approve(service, parent)
        retry = self.create(service, request="retry", parent=parent["trial_id"], data=service.read_input("task-one", parent["trial_id"]))
        self.assertNotEqual(retry["trial_id"], parent["trial_id"])
        self.assertEqual(retry["status"], "pending_approval")
        self.assertIsNone(retry["approval"])
        self.assertEqual((self.directory(parent) / "plan.json").read_bytes(), old_plan)
        self.assertEqual(service.get("task-one", parent["trial_id"])["status"], "cancelled")
        self.assertEqual(service.executor.calls, [])

    def test_running_cancel_is_immediate_and_never_claims_stop_before_executor_confirms(self):
        gate = threading.Event()
        executor = FakeExecutor(gate=gate, honour_cancel=False)
        service = self.service(executor)
        record = self.create(service)
        self.approve(service, record)
        self.assertTrue(executor.entered.wait(1))
        start = time.monotonic()
        cancelling = service.cancel("task-one", record["trial_id"])
        self.assertLess(time.monotonic() - start, 0.3)
        self.assertEqual(cancelling["status"], "cancel_requested")
        self.assertTrue(service.background_actions("task-one")[0]["running"])
        self.assertTrue(service.background_actions("task-one")[0]["worker_running"])
        gate.set()
        self.assertEqual(self.wait_status(service, record)["status"], "cancelled")
        self.assertFalse(service.background_actions("task-one")[0]["running"])

    def test_payload_materialization_is_unlocked_and_rechecks_context_before_docker(self):
        entered, release = threading.Event(), threading.Event()
        def payload(_task, record, _data):
            entered.set()
            self.assertTrue(release.wait(2))
            return json.dumps(record).encode()
        service = self.service(payload_provider=payload)
        record = self.create(service)
        self.approve(service, record)
        self.assertTrue(entered.wait(1))
        self.contexts["task-one"]["spec_revision"] = 2
        self.assertTrue(service.get("task-one", record["trial_id"])["stale"])
        release.set()
        self.assertEqual(self.wait_status(service, record)["status"], "failed")
        self.assertEqual(service.executor.calls, [])

    def test_payload_failure_is_sanitized_and_never_reaches_executor(self):
        def payload(_task, _record, _data):
            raise RuntimeError("secret /Users/private-user/model.onnx")
        service = self.service(payload_provider=payload)
        record = self.create(service)
        self.approve(service, record)
        failed = self.wait_status(service, record)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "trial_dispatch_failed")
        self.assertNotIn("private-user", json.dumps(failed))
        self.assertEqual(service.executor.calls, [])

    def test_forged_or_nonfinite_outputs_never_become_success(self):
        changes = [{"task_id": "task-two"}, {"trial_id": "wrong"}, {"plan_sha256": "0" * 64},
                   {"input_sha256": "0" * 64}, {"model_sha256": "0" * 64}, {"config_sha256": "0" * 64},
                   {"provider": "CUDAExecutionProvider"}, {"features": [float("nan"), 1]}, {"features": [True, 1]},
                   {"features": [3.5e39, 1]}, {"features": [10 ** 1000, 1]}, {"timing": {"total_ms": 10 ** 1000}},
                   {"classes": ["only-one"]}, {"output_sha256": "0" * 64},
                   {"extra": "unapproved"}, {"features": [1] * 4096, "classes": ["a"] * 4096}]
        for index, change in enumerate(changes):
            with self.subTest(change=next(iter(change))):
                def mutate(result, outcome, selected=change):
                    result.update(selected)
                    outcome["stdout"] = json.dumps(result)
                service = self.service(FakeExecutor(mutate=mutate))
                record = self.create(service, request=f"invalid-{index}")
                self.approve(service, record)
                state = self.wait_status(service, record)
                self.assertEqual(state["status"], "failed", state)
                self.assertIsNone(state["result"])
                self.assertFalse(state["business_quality_accepted"])

    def test_deeply_nested_stdout_fails_after_confirmed_cleanup_without_false_running(self):
        service = self.service(FakeExecutor(mutate=lambda _result, outcome: outcome.update(stdout="[" * 2000 + "]" * 2000)))
        record = self.create(service)
        self.approve(service, record)
        failed = self.wait_status(service, record)
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["evidence"]["cleanup_confirmed"])
        self.assertFalse(service.background_actions("task-one")[0]["running"])

    def test_concurrent_start_creates_only_one_queue_consumer(self):
        service = self.service(start=False)
        barrier = threading.Barrier(3)
        errors = []
        def start():
            barrier.wait()
            try:
                service.start()
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        original_loop = service._loop
        loops = []
        def loop():
            loops.append(threading.current_thread())
            original_loop()
        with patch.object(service, "_loop", loop):
            barrier.wait()
            for thread in threads:
                thread.join(1)
                self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(loops), 1)

    def test_stderr_warning_is_bounded_without_turning_valid_output_into_failure(self):
        service = self.service(FakeExecutor(mutate=lambda _result, outcome: outcome.update(stderr="vendor warning /Users/private-user/file " * 500)))
        record = self.create(service)
        self.approve(service, record)
        state = self.wait_status(service, record)
        self.assertEqual(state["status"], "succeeded")
        self.assertLessEqual(len(state["evidence"]["stderr_warning"]), 1024)
        self.assertNotIn("private-user", state["evidence"]["stderr_warning"])

    def test_exit_status_and_cleanup_override_successful_stdout(self):
        for index, (change, expected) in enumerate([({"exit_code": 1}, "failed"), ({"exit_code": False}, "failed"),
                                                   ({"status": "timed_out", "exit_code": 137}, "timed_out"),
                                                   ({"cleanup_confirmed": False}, "observation_degraded"),
                                                   ({"runtime_digest": "0" * 64}, "observation_degraded")]):
            service = self.service(FakeExecutor(mutate=lambda _result, outcome, values=change: outcome.update(values)))
            record = self.create(service, request=f"exit-{index}")
            self.approve(service, record)
            state = self.wait_status(service, record)
            self.assertEqual(state["status"], expected, state)
            self.assertIsNone(state["result"])
            action = next(item for item in service.background_actions("task-one") if item["trial_id"] == record["trial_id"])
            self.assertEqual(action["running"], expected == "observation_degraded")

    def test_terminal_outcome_does_not_claim_worker_exit_before_finally(self):
        service = self.service(FakeExecutor(mutate=lambda _result, outcome: outcome.update(exit_code=1)))
        record = self.create(service)
        persisted, release = threading.Event(), threading.Event()
        original_finish = service._finish

        def finish_then_pause(key, outcome):
            original_finish(key, outcome)
            persisted.set()
            self.assertTrue(release.wait(2))

        with patch.object(service, "_finish", side_effect=finish_then_pause):
            try:
                self.approve(service, record)
                self.assertTrue(persisted.wait(1))
                state = service.get("task-one", record["trial_id"])
                self.assertEqual(state["status"], "failed")
                self.assertTrue(state["evidence"]["cleanup_confirmed"])
                action = next(item for item in service.background_actions("task-one")
                              if item["trial_id"] == record["trial_id"])
                self.assertTrue(action["worker_running"])
                self.assertTrue(action["running"])
            finally:
                release.set()
            self.assertEqual(self.wait_status(service, record)["status"], "failed")
        action = next(item for item in service.background_actions("task-one")
                      if item["trial_id"] == record["trial_id"])
        self.assertFalse(action["worker_running"])
        self.assertFalse(action["running"])

    def test_exception_after_executor_entry_is_degraded_not_false_failure_or_stopped(self):
        service = self.service(FakeExecutor(raised=True))
        record = self.create(service)
        self.approve(service, record)
        state = self.wait_status(service, record)
        self.assertEqual(state["status"], "observation_degraded")
        self.assertTrue(service.background_actions("task-one")[0]["running"])
        self.assertNotIn("private-user", json.dumps(state))

    def test_degraded_cleanup_remains_archive_blocking_until_explicit_reconcile_confirms_stop(self):
        executor = FakeExecutor(mutate=lambda _result, outcome: outcome.update(cleanup_confirmed=False))
        executor.recovery_confirmed = False
        service = self.service(executor)
        record = self.create(service)
        self.approve(service, record)
        self.assertEqual(self.wait_status(service, record)["status"], "observation_degraded")
        self.assertEqual(service.reconcile("task-one", record["trial_id"])["status"], "observation_degraded")
        self.assertTrue(service.background_actions("task-one")[0]["running"])
        executor.recovery_confirmed = True
        self.assertEqual(service.reconcile("task-one", record["trial_id"])["status"], "cancelled")
        self.assertFalse(service.background_actions("task-one")[0]["running"])
        self.assertEqual(len(executor.calls), 1)

    def test_start_requires_lease_phase_and_recovers_queued_approval_without_reexecution(self):
        service = self.service(start=False)
        record = self.create(service)
        with self.assertRaisesRegex(ModelTrialError, "not_started"):
            self.approve(service, record)
        service.start()
        with patch.object(service._queue, "put"):
            self.approve(service, record)
        self.assertEqual(service.get("task-one", record["trial_id"])["status"], "queued")
        restored = self.service()
        state = restored.get("task-one", record["trial_id"])
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(state["error_code"], "service_restarted_before_dispatch")
        self.assertEqual(restored.executor.calls, [])
        self.assertEqual(restored.executor.recover_calls, [])
        self.assertEqual(service.executor.calls, [])

    def test_start_stops_existing_exact_job_without_rerunning_and_runtime_drift_blocks_recovery(self):
        gate = threading.Event()
        old = self.service(FakeExecutor(gate=gate, honour_cancel=False))
        record = self.create(old)
        self.approve(old, record)
        self.assertTrue(old.executor.entered.wait(1))
        changed = FakeExecutor()
        changed.runtime_digest = "f" * 64
        replacement = self.service(changed)
        self.assertEqual(replacement.get("task-one", record["trial_id"])["status"], "observation_degraded")
        self.assertEqual(changed.recover_calls, [])
        matching = self.service()
        state = matching.get("task-one", record["trial_id"])
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(matching.executor.recover_calls, [("task-one", record["trial_id"])])
        self.assertEqual(matching.executor.calls, [])
        gate.set()
        self.assertTrue(old.executor.finished.wait(1))
        self.assertEqual(matching.get("task-one", record["trial_id"])["status"], "cancelled")

    def test_close_cancels_queued_work_and_unconfirmed_worker_remains_blocking(self):
        gate = threading.Event()
        service = self.service(FakeExecutor(gate=gate, honour_cancel=False))
        first = self.create(service)
        self.approve(service, first)
        self.assertTrue(service.executor.entered.wait(1))
        second = self.create(service, request="second")
        self.approve(service, second)
        service.close(timeout=0.01)
        self.assertEqual(service.get("task-one", second["trial_id"])["status"], "cancelled")
        self.assertEqual(service.get("task-one", first["trial_id"])["status"], "observation_degraded")
        self.assertTrue(next(item for item in service.background_actions("task-one") if item["trial_id"] == first["trial_id"])["running"])
        with self.assertRaises(ModelTrialError):
            self.approve(service, second)
        gate.set()
        self.assertEqual(self.wait_status(service, first, {"cancelled"})["status"], "cancelled")
        self.assertEqual(len(service.executor.calls), 1)

    def test_per_task_limit_never_silently_discards_old_trials(self):
        service = self.service()
        with patch("model_harness.model_trials.MAX_TRIALS_PER_TASK", 2):
            first = self.create(service)
            self.create(service, request="second")
            with self.assertRaisesRegex(ModelTrialError, "trial_count_limit"):
                self.create(service, request="third")
            self.assertEqual(len(service.list("task-one")), 2)
            self.assertEqual(self.create(service)["trial_id"], first["trial_id"])


if __name__ == "__main__":
    unittest.main()
