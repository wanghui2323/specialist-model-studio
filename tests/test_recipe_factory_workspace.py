from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.runner import verify_run
from model_harness.blockers import verify_recipe_unavailable_evidence
from model_harness.server import create_app
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import AGENT_BRIDGE_HEADERS, start_authorized_task_run
from tests.test_audio_keyword_engine import _dataset_zip


@unittest.skipIf(TestClient is None, "server extra is not installed")
class RecipeFactoryWorkspaceTests(unittest.TestCase):
    def test_audio_gap_build_register_resume_and_real_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "本地设备关键词识别",
                        "business_goal": "用分段WAV识别 yes 和 no 两个本地控制词",
                        "capability_request": {"family": "audio_classification"},
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task = created.json()["task"]
                task_id = task["task_id"]
                self.assertEqual(task["status"], "needs_recipe")
                self.assertEqual(
                    [item["code"] for item in task["blockers"]],
                    ["recipe_unavailable"],
                )
                capability_blocker = task["blockers"][0]
                verify_recipe_unavailable_evidence(
                    capability_blocker,
                    allow_active_projection=True,
                )
                historical_request_digest = capability_blocker["facts"][
                    "recipe_build_request_digest"
                ]
                historical_spec_digest = capability_blocker["facts"][
                    "task_spec_revision_digest"
                ]
                self.assertNotIn(
                    "audio-keyword-classification",
                    app.state.run_service.registry.recipe_ids(),
                )

                payload = _dataset_zip()
                staged = client.post(
                    f"/tasks/{task_id}/staged-assets",
                    content=payload,
                    headers={"X-Filename": "recipe-samples.zip"},
                )
                self.assertEqual(staged.status_code, 201, staged.text)

                built = client.post(f"/tasks/{task_id}/recipe-builds", json={})
                self.assertEqual(built.status_code, 201, built.text)
                build = built.json()["build_attempt"]
                self.assertEqual(build["status"], "awaiting_registration")
                self.assertTrue(built.json()["validation_report"]["valid"])
                self.assertEqual(
                    built.json()["task"]["control"]["next_action"]["id"],
                    "approve_recipe_registration",
                )
                self.assertNotIn(
                    "audio-keyword-classification",
                    app.state.run_service.registry.recipe_ids(),
                )

                actor_only = client.post(
                    f"/tasks/{task_id}/recipe-builds/{build['attempt_id']}/register",
                    json={
                        "decision": "approved",
                        "actor": "local-user",
                        "candidate_digest": build["candidate_digest"],
                        "validation_digest": build["validation_digest"],
                    },
                    headers=AGENT_BRIDGE_HEADERS,
                )
                self.assertEqual(actor_only.status_code, 422, actor_only.text)
                self.assertNotIn(
                    "audio-keyword-classification",
                    app.state.run_service.registry.recipe_ids(),
                )

                approval_payload = {
                    "decision": "approved",
                    "approval": {
                        "actor": "user",
                        "checkpoint_id": "test-recipe-registration-checkpoint",
                    },
                    "reason": "reviewed declarative spec and validation digests",
                    "candidate_digest": build["candidate_digest"],
                    "validation_digest": build["validation_digest"],
                }
                no_token = client.post(
                    f"/tasks/{task_id}/recipe-builds/{build['attempt_id']}/register",
                    json=approval_payload,
                )
                self.assertEqual(no_token.status_code, 403, no_token.text)

                forged_actor = client.post(
                    f"/tasks/{task_id}/recipe-builds/{build['attempt_id']}/register",
                    json={
                        **approval_payload,
                        "approval": {
                            "actor": "acceptance-preparer",
                            "checkpoint_id": "test-forged-actor-checkpoint",
                        },
                    },
                    headers=AGENT_BRIDGE_HEADERS,
                )
                self.assertEqual(forged_actor.status_code, 422, forged_actor.text)

                missing_checkpoint = client.post(
                    f"/tasks/{task_id}/recipe-builds/{build['attempt_id']}/register",
                    json={
                        **approval_payload,
                        "approval": {"actor": "user", "checkpoint_id": ""},
                    },
                    headers=AGENT_BRIDGE_HEADERS,
                )
                self.assertEqual(
                    missing_checkpoint.status_code,
                    422,
                    missing_checkpoint.text,
                )

                registered = client.post(
                    f"/tasks/{task_id}/recipe-builds/{build['attempt_id']}/register",
                    json=approval_payload,
                    headers=AGENT_BRIDGE_HEADERS,
                )
                self.assertEqual(registered.status_code, 200, registered.text)
                registration_intent = registered.json()["registration_intent"]
                self.assertEqual(
                    registration_intent["approval"]["checkpoint_id"],
                    "test-recipe-registration-checkpoint",
                )
                self.assertEqual(
                    registration_intent["approval"]["verified_by"],
                    "agent_bridge_token",
                )
                self.assertEqual(
                    len(registration_intent["approval"]["approval_sha256"]),
                    64,
                )
                task = registered.json()["task"]
                self.assertEqual(task["task_id"], task_id)
                self.assertEqual(task["status"], "awaiting_data")
                self.assertEqual(task["recipe_id"], "audio-keyword-classification")
                self.assertEqual(task["blockers"], [])
                self.assertEqual(task["recipe_request"]["status"], "resolved")
                historical = client.get(
                    f"/tasks/{task_id}/blockers/"
                    f"{capability_blocker['blocker_id']}"
                )
                self.assertEqual(historical.status_code, 200, historical.text)
                historical_blocker = historical.json()["blocker"]
                verify_recipe_unavailable_evidence(historical_blocker)
                self.assertEqual(
                    historical_blocker["facts"]["recipe_build_request_digest"],
                    historical_request_digest,
                )
                self.assertEqual(
                    historical_blocker["facts"]["task_spec_revision_digest"],
                    historical_spec_digest,
                )
                self.assertEqual(
                    historical_blocker["facts"]["recipe_build_request_snapshot"][
                        "status"
                    ],
                    "needs_implementation",
                )
                self.assertTrue(task["recipe_version_id"].startswith("recipe-version-"))
                self.assertIn(
                    "audio-keyword-classification",
                    app.state.run_service.registry.recipe_ids(),
                )
                self.assertIn(
                    "audio-keyword-class-folder-zip",
                    app.state.training_workspace.data_adapters.adapter_ids(),
                )

                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=payload,
                    headers={"X-Filename": "formal-keywords.zip"},
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                task = uploaded.json()["task"]
                self.assertEqual(
                    task["data_adapter_id"], "audio-keyword-class-folder-zip"
                )
                self.assertEqual(task["dataset_report"]["total_audio"], 16)
                self.assertEqual(
                    task["contract"]["recipe_options"]["n_mfcc"], 13
                )

                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json=contract_confirmation_payload(client, task_id),
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                started = start_authorized_task_run(client, task_id)
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["task"]["current_run_id"]
                app.state.run_service.wait(run_id, timeout=30)

                completed = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(completed["status"], "completed")
                self.assertGreaterEqual(
                    completed["current_result"]["metrics"]["clean_test"]["macro_f1"],
                    0.95,
                )
                verified = verify_run(
                    runs_dir / run_id,
                    deep=True,
                    registry=app.state.run_service.registry,
                )
                self.assertTrue(verified["ok"], verified["errors"])

            restarted = create_app(runs_dir)
            with TestClient(restarted) as client:  # type: ignore[misc]
                restored = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(restored["recipe_id"], "audio-keyword-classification")
                self.assertEqual(restored["status"], "completed")
                self.assertIn(
                    "audio-keyword-classification",
                    restarted.state.run_service.registry.recipe_ids(),
                )

    def test_python_recipe_request_is_blocked_and_never_registers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task = client.post(
                    "/tasks",
                    json={
                        "name": "危险代码构建",
                        "business_goal": "用WAV做关键词分类",
                        "capability_request": {"family": "audio_classification"},
                    },
                ).json()["task"]
                task_id = task["task_id"]
                client.post(
                    f"/tasks/{task_id}/staged-assets",
                    content=_dataset_zip(),
                    headers={"X-Filename": "samples.zip"},
                )
                blocked = client.post(
                    f"/tasks/{task_id}/recipe-builds",
                    json={
                        "build_type": "python",
                        "python_source": "import os; os.system('echo unsafe')",
                    },
                )
                self.assertEqual(blocked.status_code, 201, blocked.text)
                attempt = blocked.json()["build_attempt"]
                self.assertEqual(attempt["status"], "failed")
                self.assertEqual(attempt["failure"]["code"], "blocked_environment")
                attempt_dir = (
                    Path(temp_dir)
                    / "runs"
                    / "_workspace"
                    / "recipe_factory"
                    / "build_attempts"
                    / attempt["attempt_id"]
                )
                persisted = " ".join(
                    path.read_text(encoding="utf-8", errors="ignore")
                    for path in attempt_dir.rglob("*")
                    if path.is_file()
                )
                self.assertNotIn("os.system", persisted)
                self.assertNotIn(
                    "audio-keyword-classification",
                    app.state.run_service.registry.recipe_ids(),
                )


if __name__ == "__main__":
    unittest.main()
