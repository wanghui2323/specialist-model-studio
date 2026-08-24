from __future__ import annotations

import importlib.util
import json
import os
import socket
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_v09_l1_live.py"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self.payload


class ScriptedTrace:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []
        self.requests: list[dict] = []

    def request(self, _client, method: str, path: str, **kwargs):
        self.calls.append((method, path))
        self.requests.append({"method": method, "path": path, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {path}")
        return self.responses.pop(0)


def load_script():
    spec = importlib.util.spec_from_file_location("verify_v09_l1_live", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load live acceptance script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyV09L1LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script()

    def _blocker(
        self,
        task_id: str,
        *,
        stage: str,
        code: str,
        retry_action: str,
    ) -> dict:
        from model_harness.blockers import BlockerStore

        with tempfile.TemporaryDirectory() as temporary:
            return BlockerStore(temporary).append(
                task_id,
                stage=stage,
                code=code,
                message="formal blocker evidence",
                retry_action=retry_action,
                details={"reason_code": "fixture_reason"},
                detector="acceptance-test@0.9",
                facts={"reason_code": "fixture_reason"},
                rule={"failure_closed": True},
                recovery_actions=[retry_action],
                retryable=True,
            )

    def test_default_invocation_is_inert_and_writes_no_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "must-not-exist.json"
            environment = dict(os.environ)
            environment.pop("MH_LIVE_ACCEPTANCE", None)
            environment["MH_L1_EVIDENCE_PATH"] = str(evidence)
            output = StringIO()
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network must not be touched"),
                ),
                redirect_stdout(output),
            ):
                exit_code = self.module.main([])
            self.assertEqual(exit_code, 0)
            self.assertIn("[SKIP]", output.getvalue())
            self.assertIn("MH_LIVE_ACCEPTANCE=1", output.getvalue())
            self.assertFalse(evidence.exists())

    def test_rate_limit_contract_is_synthetic_and_retryable(self) -> None:
        result = self.module.verify_synthetic_rate_limit_contract()
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["synthetic"])
        self.assertTrue(result["retryable"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["provider_code"], "github_rate_limited")

    def test_evidence_scrubber_removes_raw_and_bearer_secrets(self) -> None:
        secret = "ghp_acceptance_secret_123"
        scrubbed = self.module._scrub(  # noqa: SLF001 - acceptance helper contract
            {
                "message": f"Bearer {secret}",
                "token": secret,
                "nested": [f"url?q={secret}"],
            },
            (secret,),
        )
        rendered = str(scrubbed)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("'token'", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_async_bind_polls_and_reloads_matching_terminal_evidence(self) -> None:
        task = {"task_id": "acceptance-task", "current_spec_revision": 3}
        resolution = {
            "resolution_id": "source-resolution-r3-abc123def456",
            "resolved_commit": "a" * 40,
        }
        attempt_id = "binding-analysis-attempt-r1-abc123def456"
        queued = {
            "attempt": {"task_id": task["task_id"], "attempt_id": attempt_id},
            "current_state": {"status": "queued"},
        }
        running = {
            "attempt": {"task_id": task["task_id"], "attempt_id": attempt_id},
            "current_state": {"status": "running"},
        }
        completed = {
            "attempt": {"task_id": task["task_id"], "attempt_id": attempt_id},
            "current_state": {
                "status": "completed",
                "result": {
                    "binding_revision_id": "binding-revision-r1-abc123def456",
                    "analysis_id": "repository-analysis-r1-abc123def456",
                },
            },
        }
        poll_url = f"/tasks/{task['task_id']}/model-binding-attempts/{attempt_id}"
        trace = ScriptedTrace(
            [
                FakeResponse(
                    202,
                    {"binding_attempt": queued, "poll_url": poll_url},
                ),
                FakeResponse(200, {"binding_attempt": running}),
                FakeResponse(200, {"binding_attempt": completed}),
                FakeResponse(
                    200,
                    {
                        "binding": {
                            "binding_revision_id": "binding-revision-r1-abc123def456",
                            "resolution_id": resolution["resolution_id"],
                        }
                    },
                ),
                FakeResponse(
                    200,
                    {
                        "analysis": {
                            "analysis_id": "repository-analysis-r1-abc123def456"
                        }
                    },
                ),
            ]
        )

        with patch.object(self.module, "BINDING_POLL_INTERVAL_SECONDS", 0):
            result = self.module._bind(  # noqa: SLF001 - acceptance helper contract
                trace,
                object(),
                task=task,
                resolution=resolution,
                provider="github",
                token=None,
            )

        self.assertEqual(
            result["binding"]["binding_revision_id"],
            "binding-revision-r1-abc123def456",
        )
        self.assertEqual(
            result["analysis"]["analysis_id"],
            "repository-analysis-r1-abc123def456",
        )
        self.assertEqual(trace.calls.count(("GET", poll_url)), 2)
        self.assertEqual(trace.responses, [])

    def test_async_bind_fails_closed_on_failed_or_cancelled_state(self) -> None:
        task = {"task_id": "acceptance-task", "current_spec_revision": 1}
        resolution = {
            "resolution_id": "source-resolution-r1-abc123def456",
            "resolved_commit": "a" * 40,
        }
        attempt_id = "binding-analysis-attempt-r1-abc123def456"
        poll_url = f"/tasks/{task['task_id']}/model-binding-attempts/{attempt_id}"
        for terminal_status in ("failed", "cancelled"):
            with self.subTest(status=terminal_status):
                queued = {
                    "attempt": {
                        "task_id": task["task_id"],
                        "attempt_id": attempt_id,
                    },
                    "current_state": {"status": "queued"},
                }
                terminal = {
                    "attempt": queued["attempt"],
                    "current_state": {
                        "status": terminal_status,
                        "failure": {"code": "provider_failed"},
                    },
                }
                trace = ScriptedTrace(
                    [
                        FakeResponse(
                            202,
                            {"binding_attempt": queued, "poll_url": poll_url},
                        ),
                        FakeResponse(200, {"binding_attempt": terminal}),
                    ]
                )
                with (
                    patch.object(self.module, "BINDING_POLL_INTERVAL_SECONDS", 0),
                    self.assertRaises(self.module.LiveAcceptanceFailure),
                ):
                    self.module._bind(  # noqa: SLF001
                        trace,
                        object(),
                        task=task,
                        resolution=resolution,
                        provider="github",
                        token=None,
                    )

    def test_async_bind_fails_closed_on_timeout(self) -> None:
        task = {"task_id": "acceptance-task", "current_spec_revision": 1}
        resolution = {
            "resolution_id": "source-resolution-r1-abc123def456",
            "resolved_commit": "a" * 40,
        }
        attempt_id = "binding-analysis-attempt-r1-abc123def456"
        queued = {
            "attempt": {"task_id": task["task_id"], "attempt_id": attempt_id},
            "current_state": {"status": "queued"},
        }
        poll_url = f"/tasks/{task['task_id']}/model-binding-attempts/{attempt_id}"
        trace = ScriptedTrace(
            [FakeResponse(202, {"binding_attempt": queued, "poll_url": poll_url})]
        )

        with (
            patch.object(self.module, "BINDING_POLL_TIMEOUT_SECONDS", 0),
            patch.object(self.module, "BINDING_POLL_INTERVAL_SECONDS", 0),
            self.assertRaisesRegex(
                self.module.LiveAcceptanceFailure,
                "timed out",
            ),
        ):
            self.module._bind(  # noqa: SLF001
                trace,
                object(),
                task=task,
                resolution=resolution,
                provider="github",
                token=None,
            )

    def _complete_evidence(self) -> dict:
        public_sources = [
            {
                "provider": provider,
                "resolved_commit": character * 40,
                "restart_recovery": {"status": "verified"},
            }
            for provider, character in (("huggingface", "a"), ("github", "b"))
        ]
        safe_negatives = []
        for case_id in (
            "repository-does-not-exist",
            "invalid-revision-no-fallback",
            "unknown-license-blocks-training-plan",
        ):
            task_id = f"task-{case_id}"
            is_license = case_id == "unknown-license-blocks-training-plan"
            safe_negatives.append(
                {
                    "case_id": case_id,
                    "status": "verified",
                    "verified": True,
                    "formal_evidence": True,
                    "task_id": task_id,
                    "blocker": self._blocker(
                        task_id,
                        stage="training_plan" if is_license else "source_resolution",
                        code="blocked_license" if is_license else "blocked_repository",
                        retry_action=(
                            "review_model_source_license"
                            if is_license
                            else "edit_or_retry_model_source"
                        ),
                    ),
                }
            )
        safe_negatives.append(
            {
                "case_id": "github-rate-limit-transport-contract",
                "status": "verified",
                "verified": True,
                "synthetic": True,
                "formal_evidence": False,
            }
        )
        return {
            "status": "running",
            "verified": False,
            "source_commit": "c" * 40,
            "public_sources": public_sources,
            "safe_negatives": safe_negatives,
            "snapshot_integrity_negative": {
                "status": "verified",
                "formal_evidence": True,
                "integrity_read_failed": True,
                "product_api_read_http_status": 409,
                "mutated_bytes": 1,
                "record_restored": True,
                "run_count_before": 0,
                "run_count_after": 0,
                "run_created": False,
                "source_code_executed": False,
            },
            "private_fixture": {
                "status": "verified",
                "verified": True,
                "formal_evidence": True,
                "unauthenticated_access": {
                    "status": "verified",
                    "http_status": 502,
                    "no_resolution": True,
                    "no_binding": True,
                    "task_id": "task-private-unauthenticated",
                    "blocker": self._blocker(
                        "task-private-unauthenticated",
                        stage="source_resolution",
                        code="blocked_repository",
                        retry_action="retry_with_credentials",
                    ),
                },
                "authenticated_access": {"status": "verified"},
                "credential_persisted": False,
            },
            "owned_paths": list(self.module.OWNED_PATHS),
            "http_trace": [],
        }

    def test_finalizer_never_verifies_without_private_and_real_negatives(self) -> None:
        evidence = self._complete_evidence()
        evidence["safe_negatives"] = [
            self.module.verify_synthetic_rate_limit_contract()
        ]
        evidence["private_fixture"] = {
            "status": "not_run",
            "verified": False,
        }

        partial = self.module._finalize_evidence(  # noqa: SLF001
            deepcopy(evidence), formal=False
        )
        blocked = self.module._finalize_evidence(  # noqa: SLF001
            deepcopy(evidence), formal=True
        )

        self.assertEqual(partial["status"], "partial")
        self.assertFalse(partial["verified"])
        self.assertEqual(blocked["status"], "blocked")
        self.assertFalse(blocked["verified"])
        self.assertIn(
            "real_source_resolution_negatives",
            blocked["missing_requirements"],
        )
        self.assertIn(
            "real_unknown_license_plan_block_negative",
            blocked["missing_requirements"],
        )
        self.assertIn(
            "private_fixture_unauthenticated_and_authenticated",
            blocked["missing_requirements"],
        )

    def test_complete_formal_evidence_excludes_synthetic_rate_limit(self) -> None:
        evidence = self.module._finalize_evidence(  # noqa: SLF001
            self._complete_evidence(), formal=True
        )

        self.assertEqual(evidence["status"], "verified")
        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["missing_requirements"], [])
        self.assertEqual(evidence["summary"]["real_safe_negatives_verified"], 3)
        self.assertEqual(
            evidence["summary"]["synthetic_transport_contracts_observed"], 1
        )
        self.assertEqual(
            evidence["summary"][
                "synthetic_transport_contracts_counted_as_formal"
            ],
            0,
        )

    def test_formal_evidence_rejects_compact_or_tampered_blocker_projection(self) -> None:
        for mutation in ("compact", "tampered"):
            with self.subTest(mutation=mutation):
                evidence = self._complete_evidence()
                blocker = evidence["safe_negatives"][0]["blocker"]
                if mutation == "compact":
                    evidence["safe_negatives"][0]["blocker"] = {
                        "blocker_id": blocker["blocker_id"],
                        "stage": blocker["stage"],
                        "code": blocker["code"],
                        "retry_action": blocker["retry_action"],
                    }
                else:
                    blocker["facts"]["changed"] = True
                finalized = self.module._finalize_evidence(  # noqa: SLF001
                    evidence, formal=True
                )
                self.assertFalse(finalized["verified"])
                self.assertIn(
                    "real_source_resolution_blocker_evidence",
                    finalized["missing_requirements"],
                )

    def test_private_fixture_proves_unauthenticated_failure_before_token_use(self) -> None:
        task_id = "private-negative-task"
        blocker = self._blocker(
            task_id,
            stage="source_resolution",
            code="blocked_repository",
            retry_action="retry_with_credentials",
        )
        trace = ScriptedTrace(
            [
                FakeResponse(
                    201,
                    {
                        "task": {
                            "task_id": task_id,
                            "current_spec_revision": 1,
                            "capability_decision": {"status": "resolved"},
                        }
                    },
                ),
                FakeResponse(502, {"detail": "github_not_found"}),
                FakeResponse(200, {"resolutions": []}),
                FakeResponse(200, {"bindings": []}),
                FakeResponse(404, {"detail": "not found"}),
                FakeResponse(
                    200,
                    {
                        "blockers": [
                            {
                                **blocker,
                                "active": True,
                            }
                        ]
                    },
                ),
            ]
        )
        fixture = {
            "provider": "github",
            "repository": "owner/private-repo",
            "requested_revision": "main",
            "source_reference": "https://github.com/owner/private-repo",
            "token": "secret",
        }

        result = self.module._run_private_unauthenticated_negative(  # noqa: SLF001
            trace, object(), fixture
        )

        self.assertEqual(result["http_status"], 502)
        self.assertTrue(result["no_resolution"])
        self.assertTrue(result["no_binding"])
        self.assertFalse(result["token_sent"])
        self.assertEqual(trace.requests[1]["kwargs"]["headers"], {})
        self.assertEqual(trace.responses, [])

    def test_unknown_license_negative_blocks_plan_and_creates_no_run(self) -> None:
        task = {"task_id": "unknown-license-task", "current_spec_revision": 2}
        blocker = self._blocker(
            task["task_id"],
            stage="training_plan",
            code="blocked_license",
            retry_action="review_model_source_license",
        )
        resolution = {
            "resolution_id": "source-resolution-r1-abc123def456",
            "resolved_commit": "c" * 40,
        }
        bound = {
            "binding": {
                "binding_revision_id": "binding-revision-r1-abc123def456",
                "license": "unknown",
                "license_status": "unknown",
                "license_policy": {
                    "decision": "review",
                    "policy_version": "v1",
                },
            },
            "analysis": {
                "downstream_blockers": [
                    {"code": "blocked_license_unknown"}
                ]
            },
        }
        trace = ScriptedTrace(
            [
                FakeResponse(200, {"runs": []}),
                FakeResponse(409, {"detail": "license policy blocked"}),
                FakeResponse(404, {"detail": "no current plan"}),
                FakeResponse(
                    200,
                    {
                        "blockers": [
                            {
                                **blocker,
                                "active": True,
                            }
                        ]
                    },
                ),
                FakeResponse(200, {"runs": []}),
            ]
        )
        with (
            patch.object(self.module, "_create_task", return_value=task),
            patch.object(self.module, "_resolve_direct", return_value=resolution),
            patch.object(self.module, "_bind", return_value=bound),
            patch.object(
                self.module,
                "_binding_static_facts",
                return_value={"source_code_executed": False},
            ),
            patch.object(
                self.module,
                "_unknown_license_fixture",
                return_value={
                    "provider": "github",
                    "repository": "octocat/Hello-World",
                    "requested_revision": "master",
                    "source_reference": "https://github.com/octocat/Hello-World",
                },
            ),
        ):
            result = self.module._run_unknown_license_negative(  # noqa: SLF001
                trace, object(), object(), token=None
            )

        self.assertEqual(result["license"]["decision"], "review")
        self.assertEqual(result["training_plan_http_status"], 409)
        self.assertTrue(result["current_training_plan_absent"])
        self.assertFalse(result["run_created"])
        self.assertEqual(trace.responses, [])

    def test_snapshot_single_byte_tamper_fails_integrity_and_creates_no_run(self) -> None:
        from model_harness.model_source_store import ModelSourceIntegrityError

        with tempfile.TemporaryDirectory() as temporary:
            record_path = Path(temporary) / "snapshot.json"
            original = (
                b'{"documents":[{"content_base64":"'
                + b"a" * 64
                + b'"}],"content_digest":"'
                + b"b" * 64
                + b'","snapshot_id":"snapshot-one"}'
            )
            record_path.write_bytes(original)

            class FakeStore:
                def _record_path(self, _task_id, _collection, _snapshot_id):
                    return record_path

                def get_snapshot(self, _task_id, snapshot_id):
                    if record_path.read_bytes() != original:
                        raise ModelSourceIntegrityError("record digest mismatch")
                    return {"snapshot_id": snapshot_id}

            trace = ScriptedTrace(
                [
                    FakeResponse(200, {"runs": []}),
                    FakeResponse(409, {"detail": "snapshot integrity failed"}),
                    FakeResponse(200, {"runs": []}),
                ]
            )
            workspace = SimpleNamespace(model_source_store=FakeStore())

            result = self.module._verify_snapshot_tamper_fails_closed(  # noqa: SLF001
                trace,
                object(),
                workspace,
                task_id="task-one",
                snapshot_id="snapshot-one",
            )

            self.assertEqual(result["mutated_bytes"], 1)
            self.assertEqual(
                result["mutated_field"], "documents[0].content_base64"
            )
            self.assertTrue(result["integrity_read_failed"])
            self.assertEqual(result["product_api_read_http_status"], 409)
            self.assertTrue(result["record_restored"])
            self.assertFalse(result["run_created"])
            self.assertEqual(record_path.read_bytes(), original)

    def test_live_main_partial_and_formal_blocked_statuses_are_durable(self) -> None:
        for formal, expected_status, expected_exit, marker in (
            (False, "partial", 0, "[PARTIAL]"),
            (True, "blocked", 2, "[BLOCKED]"),
        ):
            with self.subTest(formal=formal), tempfile.TemporaryDirectory() as temporary:
                evidence_path = Path(temporary) / "evidence.json"
                evidence = self._complete_evidence()
                evidence["private_fixture"] = {
                    "status": "not_run",
                    "verified": False,
                }
                evidence = self.module._finalize_evidence(  # noqa: SLF001
                    evidence, formal=formal
                )
                environment = dict(os.environ)
                environment["MH_LIVE_ACCEPTANCE"] = "1"
                environment["MH_L1_EVIDENCE_PATH"] = str(evidence_path)
                argv = ["--formal"] if formal else []
                output = StringIO()
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(self.module, "_run_live", return_value=evidence) as run,
                    redirect_stdout(output),
                ):
                    exit_code = self.module.main(argv)

                self.assertEqual(exit_code, expected_exit)
                self.assertIn(marker, output.getvalue())
                persisted = json.loads(evidence_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted["status"], expected_status)
                self.assertFalse(persisted["verified"])
                self.assertTrue(persisted["missing_requirements"])
                self.assertEqual(persisted["owned_paths"], list(self.module.OWNED_PATHS))
                self.assertTrue(
                    all(
                        not Path(item).is_absolute() and ".." not in Path(item).parts
                        for item in persisted["owned_paths"]
                    )
                )
                run.assert_called_once_with(negatives=formal, formal=formal)


if __name__ == "__main__":
    unittest.main()
