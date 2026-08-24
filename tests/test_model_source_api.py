from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.blockers import verify_blocker_evidence
from model_harness.errors import HarnessError
from model_harness.resource_feasibility import ResourceProbe
from model_harness.server import create_app
from tests.test_model_binding_workspace import (
    COMMIT_A,
    FakeProvider,
    disk_bytes,
)
from tests.test_resource_feasibility import probe_observations


@unittest.skipIf(TestClient is None, "server extra is not installed")
class ModelSourceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.temporary.name) / "runs"
        self.app = create_app(self.runs_dir)
        self.github = FakeProvider("github")
        self.huggingface = FakeProvider("huggingface")
        self.app.state.training_workspace.model_source_providers = {
            "github": self.github,
            "huggingface": self.huggingface,
        }
        self.client_context = TestClient(self.app)  # type: ignore[misc]
        self.client = self.client_context.__enter__()
        created = self.client.post(
            "/tasks",
            json={
                "name": "API BYOM",
                "business_goal": "用文本和标签训练一个本地分类模型",
                "capability_request": {
                    "modality": "text",
                    "objective": "classification",
                    "target_kind": "multiclass",
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.task_id = created.json()["task"]["task_id"]

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def resolve(
        self,
        *,
        provider: str = "github",
        revision: str = "r1",
        base_spec_revision: int = 1,
        token: str | None = None,
    ):
        headers = {}
        if token is not None:
            header = "X-HF-Token" if provider == "huggingface" else "X-GitHub-Token"
            headers[header] = token
        repository = (
            "fixture-org/offline-trainer"
            if provider == "github"
            else "fixture-org/offline-model"
        )
        return self.client.post(
            f"/tasks/{self.task_id}/model-source-resolutions",
            json={
                "provider": provider,
                "repository": repository,
                "requested_revision": revision,
                "base_spec_revision": base_spec_revision,
            },
            headers=headers,
        )

    def bind(
        self,
        resolution_id: str,
        *,
        approval_confirmed: bool = True,
        expected_commit: str = COMMIT_A,
        base_spec_revision: int = 1,
        token: str | None = None,
        provider: str = "github",
    ):
        headers = {}
        if token is not None:
            header = "X-HF-Token" if provider == "huggingface" else "X-GitHub-Token"
            headers[header] = token
        return self.client.post(
            f"/tasks/{self.task_id}/model-source-resolutions/{resolution_id}/bind",
            json={
                "approval_confirmed": approval_confirmed,
                "expected_resolved_commit": expected_commit,
                "base_spec_revision": base_spec_revision,
            },
            headers=headers,
        )

    def wait_binding_attempt(
        self,
        attempt_id: str,
        *,
        expected_status: str = "completed",
        timeout: float = 5.0,
    ) -> dict:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            response = self.client.get(
                f"/tasks/{self.task_id}/model-binding-attempts/{attempt_id}"
            )
            self.assertEqual(response.status_code, 200, response.text)
            last = response.json()["binding_attempt"]
            if last["current_state"]["status"] in {
                "completed",
                "failed",
                "cancelled",
            }:
                break
            time.sleep(0.01)
        self.assertIsNotNone(last)
        self.assertEqual(last["current_state"]["status"], expected_status, last)
        return last

    def bind_and_wait(self, resolution_id: str, **kwargs) -> dict:
        queued = self.bind(resolution_id, **kwargs)
        self.assertEqual(queued.status_code, 202, queued.text)
        attempt = queued.json()["binding_attempt"]
        completed = self.wait_binding_attempt(
            attempt["attempt"]["attempt_id"]
        )
        result = completed["current_state"]["result"]
        current = self.client.get(
            f"/tasks/{self.task_id}/model-bindings/current"
        )
        self.assertEqual(current.status_code, 200, current.text)
        analysis = self.client.get(
            f"/tasks/{self.task_id}/repository-analyses/{result['analysis_id']}"
        )
        self.assertEqual(analysis.status_code, 200, analysis.text)
        return {
            "task": self.client.get(f"/tasks/{self.task_id}").json()["task"],
            "binding": current.json()["binding"],
            "analysis": analysis.json()["analysis"],
            "binding_attempt": completed,
        }

    def test_two_step_api_provider_lists_and_read_routes_close_the_loop(self) -> None:
        providers = self.client.get("/model-sources/providers")
        self.assertEqual(providers.status_code, 200, providers.text)
        self.assertEqual(
            {item["provider"] for item in providers.json()["providers"]},
            {"github", "huggingface"},
        )

        github_secret = "github_api_secret_never_persist"
        resolved = self.resolve(token=github_secret)
        self.assertEqual(resolved.status_code, 201, resolved.text)
        resolution = resolved.json()["resolution"]
        self.assertEqual(resolution["task_id"], self.task_id)
        self.assertEqual(resolution["resolved_commit"], COMMIT_A)
        self.assertEqual(self.github.count("resolve"), 1)
        self.assertEqual(self.github.count("list_tree"), 0)

        listed = self.client.get(
            f"/tasks/{self.task_id}/model-source-resolutions"
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(
            [item["resolution_id"] for item in listed.json()["resolutions"]],
            [resolution["resolution_id"]],
        )

        rejected = self.bind(
            resolution["resolution_id"],
            approval_confirmed=False,
            token=github_secret,
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(self.github.count("list_tree"), 0)
        self.assertEqual(
            self.client.get(f"/tasks/{self.task_id}/model-bindings").json()[
                "bindings"
            ],
            [],
        )

        queued = self.bind(
            resolution["resolution_id"],
            token=github_secret,
        )
        self.assertEqual(queued.status_code, 202, queued.text)
        queued_value = queued.json()
        self.assertTrue(queued_value["poll_url"].endswith(
            queued_value["binding_attempt"]["attempt"]["attempt_id"]
        ))
        value = self.bind_and_wait(
            resolution["resolution_id"],
            token=github_secret,
        )
        self.assertEqual(value["task"]["task_id"], self.task_id)
        self.assertEqual(value["binding"]["resolution_id"], resolution["resolution_id"])
        self.assertEqual(value["binding"]["status"], "active")
        self.assertEqual(value["binding"]["license_policy"]["decision"], "allow")
        self.assertEqual(value["binding"]["snapshot_summary"]["file_count"], 3)
        self.assertGreater(value["binding"]["snapshot_summary"]["known_size_bytes"], 0)
        self.assertTrue(
            value["binding"]["snapshot_summary"]["remote_code"]["declared"]
        )
        self.assertGreater(self.github.count("read_document"), 0)

        bindings = self.client.get(f"/tasks/{self.task_id}/model-bindings")
        self.assertEqual(bindings.status_code, 200, bindings.text)
        self.assertEqual(len(bindings.json()["bindings"]), 1)
        current = self.client.get(
            f"/tasks/{self.task_id}/model-bindings/current"
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(
            current.json()["binding"]["binding_revision_id"],
            value["binding"]["binding_revision_id"],
        )
        analysis_id = value["analysis"]["analysis_id"]
        analysis = self.client.get(
            f"/tasks/{self.task_id}/repository-analyses/{analysis_id}"
        )
        self.assertEqual(analysis.status_code, 200, analysis.text)
        self.assertEqual(analysis.json()["analysis"]["analysis_id"], analysis_id)

        workspace_root = self.app.state.training_workspace.root
        self.assertNotIn(github_secret.encode("utf-8"), disk_bytes(workspace_root))

    def test_repository_evidence_endpoint_returns_exact_commit_line_excerpt(self) -> None:
        resolution = self.resolve().json()["resolution"]
        result = self.bind_and_wait(resolution["resolution_id"])
        analysis = result["analysis"]
        entrypoint = analysis["training_entrypoints"][0]
        text_evidence = next(
            item
            for item in entrypoint["evidence"]
            if item["kind"] == "text_line"
        )
        response = self.client.get(
            f"/tasks/{self.task_id}/repository-analyses/{analysis['analysis_id']}/evidence",
            params={
                "path": text_evidence["path"],
                "line": text_evidence["line"],
                "context_lines": 1,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        evidence = response.json()["evidence"]
        self.assertEqual(evidence["resolved_commit"], COMMIT_A)
        self.assertEqual(evidence["path"], "train.py")
        self.assertEqual(
            evidence["document_sha256"], text_evidence["document_sha256"]
        )
        self.assertTrue(
            any("trainer.train" in item["text"] for item in evidence["lines"])
        )

        missing = self.client.get(
            f"/tasks/{self.task_id}/repository-analyses/{analysis['analysis_id']}/evidence",
            params={"path": "not-captured.py", "line": 1},
        )
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_needs_input_analysis_can_be_retried_with_traceable_manual_mapping(self) -> None:
        self.github.contents = {
            "README.md": (
                b"# Manual fixture\n\nNo conventional entrypoint is declared.\n"
                b"Evaluation uses accuracy_score(labels, predictions).\n"
            ),
            "scripts/custom_job.py": (
                b"print('user-mapped training job')\n"
                b"score = accuracy_score(labels, predictions)\n"
            ),
        }
        resolution = self.resolve().json()["resolution"]
        first = self.bind_and_wait(resolution["resolution_id"])
        first_analysis = first["analysis"]
        first_binding = first["binding"]
        self.assertEqual(first_analysis["status"], "needs_input")
        self.assertEqual(first_analysis["training_entrypoints"], [])

        rejected = self.client.post(
            f"/tasks/{self.task_id}/repository-analyses/{first_analysis['analysis_id']}/manual-mappings",
            json={"training_entrypoint": "scripts/missing.py"},
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        rejected_readme = self.client.post(
            f"/tasks/{self.task_id}/repository-analyses/{first_analysis['analysis_id']}/manual-mappings",
            json={"training_entrypoint": "README.md"},
        )
        self.assertEqual(rejected_readme.status_code, 409, rejected_readme.text)
        self.assertEqual(
            self.app.state.training_workspace.repository_analysis_store.list_manual_mapping_revisions(
                self.task_id,
                first_analysis["source_snapshot_id"],
            ),
            [],
        )
        self.assertEqual(
            self.client.get(
                f"/tasks/{self.task_id}/model-bindings/current"
            ).json()["binding"]["binding_revision_id"],
            first_binding["binding_revision_id"],
        )

        mapped = self.client.post(
            f"/tasks/{self.task_id}/repository-analyses/{first_analysis['analysis_id']}/manual-mappings",
            json={
                "training_entrypoint": "scripts/custom_job.py",
                "dataset_argument": "--dataset-dir",
            },
        )
        self.assertEqual(mapped.status_code, 201, mapped.text)
        value = mapped.json()
        analysis = value["analysis"]
        self.assertEqual(analysis["status"], "complete")
        self.assertNotEqual(analysis["analysis_id"], first_analysis["analysis_id"])
        self.assertEqual(
            analysis["source_snapshot_id"], first_analysis["source_snapshot_id"]
        )
        self.assertEqual(analysis["resolved_commit"], COMMIT_A)
        self.assertEqual(
            analysis["training_entrypoints"][0]["path"],
            "scripts/custom_job.py",
        )
        self.assertEqual(
            analysis["training_entrypoints"][0]["evidence"][0]["kind"],
            "manual_mapping",
        )
        self.assertEqual(
            analysis["manual_mapping"]["mapping"]["dataset_argument"],
            "--dataset-dir",
        )
        self.assertNotEqual(
            value["binding"]["binding_revision_id"],
            first_binding["binding_revision_id"],
        )
        self.assertEqual(
            value["analysis_attempt"]["attempt"]["retry_of_attempt_id"],
            first["task"]["repository_analysis_attempt"]["attempt"][
                "attempt_id"
            ],
        )

        reentered = self.client.get(f"/tasks/{self.task_id}")
        self.assertEqual(reentered.status_code, 200, reentered.text)
        self.assertEqual(
            reentered.json()["task"]["repository_analysis"]["analysis_id"],
            analysis["analysis_id"],
        )
        historical = self.client.get(
            f"/tasks/{self.task_id}/repository-analyses/{first_analysis['analysis_id']}"
        )
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(historical.json()["analysis"]["status"], "needs_input")

        plan = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={"base_spec_revision": 1},
        )
        self.assertEqual(plan.status_code, 201, plan.text)
        self.assertEqual(
            plan.json()["training_plan"]["plan"]["entrypoint"]["argv"],
            ["python", "scripts/custom_job.py"],
        )
        self.assertEqual(
            plan.json()["training_plan"]["plan"]["dataset_mapping"][
                "entrypoint_argument"
            ],
            "--dataset-dir",
        )

    def test_bound_source_can_generate_and_digest_approve_training_plan(self) -> None:
        resolved = self.resolve()
        self.assertEqual(resolved.status_code, 201, resolved.text)
        resolution = resolved.json()["resolution"]
        self.bind_and_wait(resolution["resolution_id"])
        ready_task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertEqual(ready_task["repository_analysis"]["status"], "complete")
        self.assertEqual(ready_task["control"]["current_stage"], "training_plan")
        self.assertEqual(
            ready_task["control"]["next_action"]["id"],
            "create_training_plan",
        )

        created = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={"base_spec_revision": 1},
        )
        self.assertEqual(created.status_code, 201, created.text)
        plan_view = created.json()["training_plan"]
        self.assertEqual(plan_view["effective_status"], "awaiting_approval")
        plan = plan_view["plan"]
        self.assertEqual(plan["entrypoint"]["argv"], ["python", "train.py"])
        self.assertEqual(plan["execution_policy"]["backend"], "oci")

        wrong_digest = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{plan['training_plan_revision_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_sha256": "0" * 64,
            },
        )
        self.assertEqual(wrong_digest.status_code, 409, wrong_digest.text)

        approved = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{plan['training_plan_revision_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_sha256": plan["plan_sha256"],
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(
            approved.json()["training_plan"]["effective_status"], "approved"
        )

        task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertEqual(task["control"]["current_stage"], "resource_probe")

        invalid_packages = self.client.post(
            f"/tasks/{self.task_id}/resource-feasibility-checks",
            json={
                "training_plan_revision_id": plan[
                    "training_plan_revision_id"
                ],
                "expected_plan_sha256": plan["plan_sha256"],
                "packages": ["not-an-object"],
            },
        )
        self.assertEqual(invalid_packages.status_code, 422)

        unavailable_probe = ResourceProbe.from_observations(
            probe_observations(container_available=False)
        )
        with patch(
            "model_harness.workspace.ResourceProbe.capture",
            return_value=unavailable_probe,
        ):
            checked = self.client.post(
                f"/tasks/{self.task_id}/resource-feasibility-checks",
                json={
                    "training_plan_revision_id": plan[
                        "training_plan_revision_id"
                    ],
                    "expected_plan_sha256": plan["plan_sha256"],
                },
            )
        self.assertEqual(checked.status_code, 201, checked.text)
        feasibility = checked.json()["resource_feasibility"]
        self.assertEqual(feasibility["decision"], "blocked_environment")
        self.assertIsNone(feasibility["environment_lock"])
        self.assertIsNone(feasibility["resource_fit_report"])
        self.assertEqual(
            feasibility["resource_probe"]["container_runtime"]["available"],
            False,
        )
        task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertEqual(task["control"]["current_stage"], "environment_lock")

        revised = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{plan['training_plan_revision_id']}/revisions",
            json={
                "base_spec_revision": 1,
                "expected_parent_sha256": plan["plan_sha256"],
                "resource_budget": {"ram_bytes": 3 * 1024**3},
            },
        )
        self.assertEqual(revised.status_code, 201, revised.text)
        feasibility_after_revision = self.client.get(
            f"/tasks/{self.task_id}/resource-feasibility"
        ).json()["resource_feasibility"]
        self.assertEqual(feasibility_after_revision["decision"], "not_checked")
        self.assertEqual(feasibility_after_revision["blockers"], [])
        task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertEqual(task["control"]["current_stage"], "training_plan")

    def test_blocked_repository_analysis_cannot_create_training_plan(self) -> None:
        self.github.contents["train.py"] = (
            b"import subprocess\n"
            b"subprocess.run(['echo', 'unsafe'])\n"
            b"loss.backward()\noptimizer.step()\n"
        )
        resolution = self.resolve().json()["resolution"]
        bound = self.bind_and_wait(resolution["resolution_id"])
        self.assertEqual(bound["analysis"]["status"], "blocked")

        task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertEqual(task["control"]["current_stage"], "repository_analysis")
        self.assertEqual(
            task["control"]["next_action"]["id"],
            "review_repository_risks",
        )
        self.assertEqual(
            task["control"]["blocked_by"][0]["code"],
            "blocked_security",
        )
        blocker = next(
            item
            for item in task["blockers"]
            if item["stage"] == "repository_analysis"
        )
        self.assertEqual(blocker["code"], "blocked_security")
        self.assertEqual(blocker["related_object_type"], "RepositoryAnalysis")
        verify_blocker_evidence(blocker, allow_active_projection=True)

        rejected = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={"base_spec_revision": 1},
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("未解决的风险", rejected.text)
        self.assertEqual(
            self.client.get(
                f"/tasks/{self.task_id}/training-plans/current"
            ).status_code,
            404,
        )
        reentered = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertIsNone(reentered["current_run_id"])
        self.assertEqual(
            reentered["control"]["current_stage"],
            "repository_analysis",
        )

    def test_blocked_current_analysis_cannot_revise_or_authorize_old_plan(self) -> None:
        first_resolution = self.resolve().json()["resolution"]
        self.bind_and_wait(first_resolution["resolution_id"])
        created = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={"base_spec_revision": 1},
        )
        self.assertEqual(created.status_code, 201, created.text)
        parent = created.json()["training_plan"]["plan"]

        self.github.contents["train.py"] = (
            b"import subprocess\nsubprocess.run(['echo', 'unsafe'])\n"
            b"loss.backward()\noptimizer.step()\n"
        )
        second_resolution = self.resolve(revision="r2").json()["resolution"]
        rebound = self.bind_and_wait(
            second_resolution["resolution_id"],
            expected_commit="b" * 40,
        )
        self.assertEqual(rebound["analysis"]["status"], "blocked")

        before_revisions = len(
            self.app.state.training_workspace.training_plan_store.list_revisions(
                self.task_id
            )
        )
        rejected = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{parent['training_plan_revision_id']}/revisions",
            json={
                "base_spec_revision": 1,
                "expected_parent_sha256": parent["plan_sha256"],
                "resource_budget": {"ram_bytes": 1},
            },
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("未解决的风险", rejected.json()["detail"])
        self.assertEqual(
            len(
                self.app.state.training_workspace.training_plan_store.list_revisions(
                    self.task_id
                )
            ),
            before_revisions,
        )
        with self.assertRaisesRegex(HarnessError, "仓库分析"):
            self.app.state.training_workspace.authorize_v09_execution(
                self.task_id
            )

    def test_hashed_dependencies_still_require_model_and_dataset_size_evidence(self) -> None:
        self.github.contents["requirements.txt"] = (
            b"torch==2.5.1 --hash=sha256:"
            + (b"c" * 64)
            + b"\n"
        )
        self.github.contents.pop("pyproject.toml")
        resolution = self.resolve().json()["resolution"]
        self.bind_and_wait(resolution["resolution_id"])
        created = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={"base_spec_revision": 1},
        )
        self.assertEqual(created.status_code, 201, created.text)
        plan = created.json()["training_plan"]["plan"]
        approved = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{plan['training_plan_revision_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_sha256": plan["plan_sha256"],
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)

        available_probe = ResourceProbe.from_observations(probe_observations())
        with patch(
            "model_harness.workspace.ResourceProbe.capture",
            return_value=available_probe,
        ):
            checked = self.client.post(
                f"/tasks/{self.task_id}/resource-feasibility-checks",
                json={
                    "training_plan_revision_id": plan[
                        "training_plan_revision_id"
                    ],
                    "expected_plan_sha256": plan["plan_sha256"],
                    "base_image_digest": f"sha256:{'d' * 64}",
                },
            )
        self.assertEqual(checked.status_code, 201, checked.text)
        feasibility = checked.json()["resource_feasibility"]
        self.assertEqual(feasibility["decision"], "blocked_resources")
        self.assertEqual(
            feasibility["environment_lock"]["packages"],
            [
                {
                    "name": "torch",
                    "version": "2.5.1",
                    "hashes": [f"sha256:{'c' * 64}"],
                }
            ],
        )
        self.assertIsNone(feasibility["resource_fit_report"])
        self.assertEqual(feasibility["blockers"][0]["code"], "blocked_resources")
        self.assertEqual(
            feasibility["blockers"][0]["retry_action"],
            "continue_to_l3_qualification",
        )
        self.assertFalse(feasibility["blockers"][0]["details"]["retryable"])
        with self.assertRaisesRegex(HarnessError, "资源资格证据"):
            self.app.state.training_workspace.authorize_v09_execution(
                self.task_id
            )

    def test_provisional_budget_never_creates_fit_report_or_run(self) -> None:
        self.github.contents["requirements.txt"] = (
            b"torch==2.5.1 --hash=sha256:" + (b"c" * 64) + b"\n"
        )
        self.github.contents.pop("pyproject.toml")
        resolution = self.resolve().json()["resolution"]
        self.bind_and_wait(resolution["resolution_id"])
        created = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={
                "base_spec_revision": 1,
                "resource_budget": {"vram_bytes": 1},
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        plan = created.json()["training_plan"]["plan"]
        approved = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{plan['training_plan_revision_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_sha256": plan["plan_sha256"],
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)

        before_runs = self.app.state.run_service.list_runs()
        available_probe = ResourceProbe.from_observations(
            probe_observations(detected=("cuda",))
        )
        with patch(
            "model_harness.workspace.ResourceProbe.capture",
            return_value=available_probe,
        ):
            checked = self.client.post(
                f"/tasks/{self.task_id}/resource-feasibility-checks",
                json={
                    "training_plan_revision_id": plan[
                        "training_plan_revision_id"
                    ],
                    "expected_plan_sha256": plan["plan_sha256"],
                    "base_image_digest": f"sha256:{'d' * 64}",
                },
            )
        self.assertEqual(checked.status_code, 201, checked.text)
        feasibility = checked.json()["resource_feasibility"]
        self.assertEqual(feasibility["decision"], "blocked_resources")
        self.assertIsNone(feasibility["resource_fit_report"])
        self.assertEqual(feasibility["blockers"][0]["code"], "blocked_resources")
        self.assertEqual(
            feasibility["blockers"][0]["retry_action"],
            "continue_to_l3_qualification",
        )
        self.assertFalse(feasibility["blockers"][0]["details"]["retryable"])
        self.assertEqual(self.app.state.run_service.list_runs(), before_runs)
        with self.assertRaisesRegex(HarnessError, "资源资格证据"):
            self.app.state.training_workspace.authorize_v09_execution(
                self.task_id
            )

    def test_training_plan_revision_requires_exact_parent_digest(self) -> None:
        resolution = self.resolve().json()["resolution"]
        self.bind_and_wait(resolution["resolution_id"])
        created = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={"base_spec_revision": 1},
        )
        self.assertEqual(created.status_code, 201, created.text)
        parent = created.json()["training_plan"]["plan"]

        rejected = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{parent['training_plan_revision_id']}/revisions",
            json={
                "base_spec_revision": 1,
                "expected_parent_sha256": "0" * 64,
                "resource_budget": {"ram_bytes": 5 * 1024**3},
            },
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)

        revised = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{parent['training_plan_revision_id']}/revisions",
            json={
                "base_spec_revision": 1,
                "expected_parent_sha256": parent["plan_sha256"],
                "resource_budget": {"ram_bytes": 5 * 1024**3},
            },
        )
        self.assertEqual(revised.status_code, 201, revised.text)
        child_view = revised.json()["training_plan"]
        child = child_view["plan"]
        self.assertEqual(child["revision"], 2)
        self.assertEqual(
            child["parent_revision_id"], parent["training_plan_revision_id"]
        )
        self.assertEqual(child["parent_plan_sha256"], parent["plan_sha256"])
        self.assertEqual(child["resource_budget"]["ram_bytes"], 5 * 1024**3)
        self.assertEqual(child_view["effective_status"], "awaiting_approval")

        stale_parent_decision = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{parent['training_plan_revision_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_sha256": parent["plan_sha256"],
            },
        )
        self.assertEqual(stale_parent_decision.status_code, 409)

    def test_byom_plan_without_fit_evidence_fails_execution_authorization(self) -> None:
        resolution = self.resolve().json()["resolution"]
        self.bind_and_wait(resolution["resolution_id"])
        created_plan = self.client.post(
            f"/tasks/{self.task_id}/training-plans",
            json={"base_spec_revision": 1},
        )
        self.assertEqual(created_plan.status_code, 201, created_plan.text)
        plan = created_plan.json()["training_plan"]["plan"]
        approved = self.client.post(
            f"/tasks/{self.task_id}/training-plans/{plan['training_plan_revision_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_sha256": plan["plan_sha256"],
                "reason": "guard fixture",
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)

        before = set(self.runs_dir.glob("*"))
        with self.assertRaisesRegex(HarnessError, "资源资格证据"):
            self.app.state.training_workspace.authorize_v09_execution(
                self.task_id
            )
        self.assertEqual(set(self.runs_dir.glob("*")), before)
        task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertEqual(task["run_ids"], [])

    def test_official_catalog_search_requires_confirmed_spec_and_user_selection(self) -> None:
        workspace = self.app.state.training_workspace
        revision = workspace.get_task(self.task_id)["current_spec_revision"]
        search = self.client.post(
            f"/tasks/{self.task_id}/model-source-searches",
            json={
                "query": "text classification",
                "providers": ["huggingface", "github"],
                "limit_per_provider": 2,
                "base_spec_revision": revision,
            },
            headers={
                "X-HF-Token": "hf_search_secret",
                "X-GitHub-Token": "gh_search_secret",
            },
        )
        self.assertEqual(search.status_code, 200, search.text)
        payload = search.json()
        self.assertEqual(len(payload["candidates"]), 2)
        self.assertEqual(
            {item["selection_state"] for item in payload["candidates"]},
            {"needs_user_confirmation"},
        )
        restored = self.client.get(
            f"/tasks/{self.task_id}/model-source-searches"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(len(restored.json()["searches"]), 1)
        self.assertEqual(
            restored.json()["searches"][0]["search_id"], payload["search_id"]
        )
        self.assertEqual(
            restored.json()["searches"][0]["candidates"], payload["candidates"]
        )
        selected = next(
            item for item in payload["candidates"] if item["provider"] == "github"
        )
        rejected = self.client.post(
            f"/tasks/{self.task_id}/model-source-selections",
            json={
                "search_id": payload["search_id"],
                "candidate_id": selected["candidate_id"],
                "approval_confirmed": False,
                "base_spec_revision": revision,
            },
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(self.github.count("resolve"), 0)

        confirmed_selection = self.client.post(
            f"/tasks/{self.task_id}/model-source-selections",
            json={
                "search_id": payload["search_id"],
                "candidate_id": selected["candidate_id"],
                "approval_confirmed": True,
                "base_spec_revision": revision,
            },
            headers={"X-GitHub-Token": "gh_selection_secret"},
        )
        self.assertEqual(confirmed_selection.status_code, 201, confirmed_selection.text)
        resolution = confirmed_selection.json()["resolution"]
        self.assertEqual(resolution["repository"], selected["repository"])
        self.assertEqual(
            resolution["details"]["selection_context"]["candidate_id"],
            selected["candidate_id"],
        )
        self.assertEqual(self.github.count("resolve"), 1)
        self.assertEqual(self.github.count("list_tree"), 0)
        disk = disk_bytes(workspace.root)
        self.assertNotIn(b"hf_search_secret", disk)
        self.assertNotIn(b"gh_search_secret", disk)
        self.assertNotIn(b"gh_selection_secret", disk)

        invalid = self.client.post(
            f"/tasks/{self.task_id}/model-source-selections",
            json={
                "search_id": payload["search_id"],
                "candidate_id": "candidate_000000000000000000000000",
                "approval_confirmed": True,
                "base_spec_revision": revision,
            },
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)

    def test_search_rejects_credentials_before_calls_or_persistence(self) -> None:
        workspace = self.app.state.training_workspace
        revision = workspace.get_task(self.task_id)["current_spec_revision"]
        cases = (
            (
                "catalog_password_never_persist",
                "https://catalog-user:catalog_password_never_persist@github.com/fixture/model",
            ),
            (
                "catalog_url_token_never_persist",
                "https://github.com/fixture/model?access_token=catalog_url_token_never_persist",
            ),
            (
                "github_pat_" + "A" * 40,
                "vision model github_pat_" + "A" * 40,
            ),
            (
                "hf_" + "B" * 40,
                "audio model hf_" + "B" * 40,
            ),
        )

        for secret, query in cases:
            with self.subTest(query_kind=query.split(" ", 1)[0]):
                rejected = self.client.post(
                    f"/tasks/{self.task_id}/model-source-searches",
                    json={
                        "query": query,
                        "providers": ["huggingface", "github"],
                        "limit_per_provider": 2,
                        "base_spec_revision": revision,
                    },
                )
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.assertNotIn(secret, rejected.text)

        self.assertEqual(self.huggingface.count("search"), 0)
        self.assertEqual(self.github.count("search"), 0)
        self.assertEqual(
            self.client.get(
                f"/tasks/{self.task_id}/model-source-searches"
            ).json()["searches"],
            [],
        )
        disk = disk_bytes(workspace.root)
        for secret, _query in cases:
            self.assertNotIn(secret.encode("utf-8"), disk)

        ordinary_token_term = self.client.post(
            f"/tasks/{self.task_id}/model-source-searches",
            json={
                "query": "token classification",
                "providers": ["huggingface", "github"],
                "limit_per_provider": 2,
                "base_spec_revision": revision,
            },
        )
        self.assertEqual(
            ordinary_token_term.status_code, 200, ordinary_token_term.text
        )
        self.assertEqual(self.huggingface.count("search"), 1)
        self.assertEqual(self.github.count("search"), 1)

    def test_all_provider_failures_persist_the_failed_search_timeline(self) -> None:
        def fail_search(*_args, **_kwargs):
            raise ModelSourceUpstreamError("fixture_catalog_unavailable")

        self.github.search = fail_search  # type: ignore[method-assign]
        self.huggingface.search = fail_search  # type: ignore[method-assign]
        revision = self.app.state.training_workspace.get_task(self.task_id)[
            "current_spec_revision"
        ]

        failed = self.client.post(
            f"/tasks/{self.task_id}/model-source-searches",
            json={
                "query": "text classification",
                "providers": ["huggingface", "github"],
                "limit_per_provider": 2,
                "base_spec_revision": revision,
            },
        )

        self.assertEqual(failed.status_code, 502, failed.text)
        restored = self.client.get(
            f"/tasks/{self.task_id}/model-source-searches"
        ).json()["searches"]
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["candidates"], [])
        self.assertEqual(
            {item["provider"] for item in restored[0]["provider_errors"]},
            {"huggingface", "github"},
        )
        task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        blocker = next(
            item
            for item in task["blockers"]
            if item["stage"] == "source_discovery" and item["active"] is True
        )
        self.assertEqual(blocker["details"]["search_id"], restored[0]["search_id"])
        self.assertEqual(blocker["code"], "blocked_repository")
        self.assertIn("model_source_search_failed", blocker["details"]["reason_code"])
        verify_blocker_evidence(blocker, allow_active_projection=True)

    def test_expected_commit_and_spec_conflicts_create_zero_bindings(self) -> None:
        stale_resolution = self.resolve(base_spec_revision=99)
        self.assertEqual(stale_resolution.status_code, 409, stale_resolution.text)
        self.assertEqual(
            self.client.get(
                f"/tasks/{self.task_id}/model-source-resolutions"
            ).json()["resolutions"],
            [],
        )

        resolution = self.resolve().json()["resolution"]
        cases = (
            {
                "expected_commit": "b" * 40,
                "base_spec_revision": 1,
                "approval_confirmed": True,
            },
            {
                "expected_commit": COMMIT_A,
                "base_spec_revision": 99,
                "approval_confirmed": True,
            },
            {
                "expected_commit": COMMIT_A,
                "base_spec_revision": 1,
                "approval_confirmed": False,
            },
        )
        for case in cases:
            with self.subTest(case=case):
                response = self.bind(resolution["resolution_id"], **case)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    self.client.get(
                        f"/tasks/{self.task_id}/model-bindings"
                    ).json()["bindings"],
                    [],
                )
                self.assertEqual(self.github.count("list_tree"), 0)

        unknown_provider = self.resolve(provider="not-a-provider")
        self.assertEqual(unknown_provider.status_code, 422, unknown_provider.text)

    def test_provider_headers_are_not_mixed_and_tokens_are_ephemeral(self) -> None:
        github_secret = "github_only_secret"
        hf_secret = "hf_only_secret"
        response = self.client.post(
            f"/tasks/{self.task_id}/model-source-resolutions",
            json={
                "provider": "github",
                "repository": "fixture-org/offline-trainer",
                "requested_revision": "r1",
                "base_spec_revision": 1,
            },
            headers={
                "X-GitHub-Token": github_secret,
                "X-HF-Token": hf_secret,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.github.calls[0], ("resolve", github_secret))
        self.assertNotIn(hf_secret, [token for _operation, token in self.github.calls])
        disk = disk_bytes(self.app.state.training_workspace.root)
        self.assertNotIn(github_secret.encode("utf-8"), disk)
        self.assertNotIn(hf_secret.encode("utf-8"), disk)

    def test_tree_failure_is_persisted_async_and_resolution_error_remains_502(self) -> None:
        self.github.fail_on = "tree"
        resolution = self.resolve().json()["resolution"]
        truncated = self.bind(resolution["resolution_id"])
        self.assertEqual(truncated.status_code, 202, truncated.text)
        failed = self.wait_binding_attempt(
            truncated.json()["binding_attempt"]["attempt"]["attempt_id"],
            expected_status="failed",
        )
        self.assertIn(
            "source_tree_truncated",
            failed["current_state"]["failure"]["message"],
        )
        self.assertEqual(
            self.client.get(f"/tasks/{self.task_id}/model-bindings").json()[
                "bindings"
            ],
            [],
        )
        current = self.client.get(
            f"/tasks/{self.task_id}/model-bindings/current"
        )
        self.assertEqual(current.status_code, 404, current.text)
        blockers = self.client.get(
            f"/tasks/{self.task_id}/blockers?active_only=true"
        )
        self.assertEqual(blockers.status_code, 200, blockers.text)
        self.assertEqual(len(blockers.json()["blockers"]), 1)
        self.assertEqual(
            blockers.json()["blockers"][0]["stage"], "source_snapshot"
        )
        projected = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertEqual(
            projected["blockers"][0]["blocker_id"],
            blockers.json()["blockers"][0]["blocker_id"],
        )

        other = self.client.post(
            "/tasks",
            json={"name": "provider error", "business_goal": "offline fixture"},
        ).json()["task"]
        self.github.fail_on = "resolve"
        failed = self.client.post(
            f"/tasks/{other['task_id']}/model-source-resolutions",
            json={
                "provider": "github",
                "repository": "fixture-org/offline-trainer",
                "requested_revision": "r1",
                "base_spec_revision": 1,
            },
        )
        self.assertEqual(failed.status_code, 502, failed.text)
        self.assertIn("fixture_provider_unavailable", failed.json()["detail"])
        persisted = self.client.get(
            f"/tasks/{other['task_id']}/blockers?active_only=true"
        ).json()["blockers"]
        self.assertEqual(persisted[0]["stage"], "source_resolution")
        self.assertEqual(persisted[0]["code"], "blocked_repository")
        self.assertEqual(
            persisted[0]["details"]["reason_code"],
            "fixture_provider_unavailable",
        )
        verify_blocker_evidence(persisted[0], allow_active_projection=True)

    def test_binding_request_returns_before_remote_read_and_projects_attempt(self) -> None:
        resolution = self.resolve().json()["resolution"]
        entered = threading.Event()
        release = threading.Event()
        original = self.github.list_tree

        def blocked_tree(source, *, token=None):
            entered.set()
            self.assertTrue(release.wait(5.0))
            return original(source, token=token)

        with patch.object(self.github, "list_tree", side_effect=blocked_tree):
            started_at = time.monotonic()
            queued = self.bind(resolution["resolution_id"])
            elapsed = time.monotonic() - started_at
            self.assertEqual(queued.status_code, 202, queued.text)
            self.assertLess(elapsed, 0.5)
            self.assertTrue(entered.wait(1.0))
            attempt_id = queued.json()["binding_attempt"]["attempt"]["attempt_id"]
            task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
            self.assertIsNone(task["model_binding"])
            self.assertEqual(
                task["model_binding_attempt"]["attempt"]["attempt_id"],
                attempt_id,
            )
            self.assertEqual(
                task["repository_analysis_attempt"]["attempt"]["attempt_id"],
                attempt_id,
            )
            self.assertIn(
                task["model_binding_attempt"]["current_state"]["status"],
                {"queued", "running"},
            )
            release.set()
            completed = self.wait_binding_attempt(attempt_id)
            self.assertEqual(
                completed["current_state"]["result"]["resolution_id"],
                resolution["resolution_id"],
            )

    def test_running_binding_can_be_cancelled_without_binding_or_analysis(self) -> None:
        resolution = self.resolve().json()["resolution"]
        entered = threading.Event()
        release = threading.Event()
        original = self.github.list_tree

        def blocked_tree(source, *, token=None):
            entered.set()
            self.assertTrue(release.wait(5.0))
            return original(source, token=token)

        with patch.object(self.github, "list_tree", side_effect=blocked_tree):
            queued = self.bind(resolution["resolution_id"])
            self.assertEqual(queued.status_code, 202, queued.text)
            attempt_id = queued.json()["binding_attempt"]["attempt"]["attempt_id"]
            self.assertTrue(entered.wait(1.0))
            cancelled = self.client.post(
                f"/tasks/{self.task_id}/model-binding-attempts/{attempt_id}/cancel",
                json={"reason": "用户改变了模型选择"},
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            self.assertTrue(cancelled.json()["cancelled"])
            self.assertEqual(
                cancelled.json()["binding_attempt"]["current_state"]["status"],
                "cancelled",
            )
            release.set()
            terminal = self.wait_binding_attempt(
                attempt_id,
                expected_status="cancelled",
            )
            self.assertEqual(
                terminal["current_state"]["cancellation"]["reason"],
                "用户改变了模型选择",
            )

        self.assertEqual(
            self.client.get(f"/tasks/{self.task_id}/model-bindings").json()[
                "bindings"
            ],
            [],
        )
        self.assertEqual(
            self.client.get(
                f"/tasks/{self.task_id}/model-bindings/current"
            ).status_code,
            404,
        )
        task = self.client.get(f"/tasks/{self.task_id}").json()["task"]
        self.assertIsNone(task["model_binding"])
        self.assertIsNone(task["repository_analysis"])


if __name__ == "__main__":
    unittest.main()
