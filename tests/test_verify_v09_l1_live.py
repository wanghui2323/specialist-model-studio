from __future__ import annotations

import importlib.util
import json
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
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

    def request(self, _client, method: str, path: str, **_kwargs):
        self.calls.append((method, path))
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


if __name__ == "__main__":
    unittest.main()
