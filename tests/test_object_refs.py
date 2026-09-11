from __future__ import annotations

import unittest

from model_harness.object_refs import (
    OBJECT_REF_DESCRIPTORS,
    ObjectRefValidationError,
    exact_object_ref_endpoint,
    normalize_object_ref,
    normalize_object_refs,
)


SHA = "a" * 64
COMMIT = "b" * 40


class ObjectRefRegistryTests(unittest.TestCase):
    def test_registry_covers_the_l2_matrix(self) -> None:
        self.assertEqual(
            set(OBJECT_REF_DESCRIPTORS),
            {
                "model_source_search",
                "model_source_resolution",
                "model_binding",
                "model_binding_attempt",
                "repository_analysis",
                "training_plan",
                "resource_feasibility",
                "staged_asset",
                "recipe_build",
                "evaluation_report",
                "inference_input",
                "artifact_bundle",
                "blocker",
            },
        )
        for descriptor in OBJECT_REF_DESCRIPTORS.values():
            self.assertEqual(descriptor.task_scope_rule, "exact_task")
            self.assertEqual(descriptor.redaction_policy, "canonical_fields_only")
            self.assertIsNotNone(descriptor.endpoint_template)

    def test_search_preserves_revision_and_builds_exact_endpoint(self) -> None:
        ref = normalize_object_ref(
            {
                "type": "model_source_search",
                "id": "search-1",
                "task_id": "task-1",
                "base_spec_revision": 3,
                "label": "公开候选",
                "ignored": "must not leak",
            },
            expected_task_id="task-1",
        )
        self.assertEqual(ref.base_spec_revision, 3)
        self.assertNotIn("ignored", ref.as_dict())
        self.assertEqual(
            exact_object_ref_endpoint(ref),
            "/tasks/task-1/model-source-searches/search-1",
        )

    def test_versioned_and_run_objects_keep_full_identity(self) -> None:
        plan = normalize_object_ref(
            {
                "type": "training_plan",
                "id": "plan-r2",
                "task_id": "task-1",
                "digest": SHA,
                "revision": 2,
            },
            expected_task_id="task-1",
        )
        self.assertEqual(plan.revision, 2)
        self.assertEqual(plan.digest, SHA)
        report = normalize_object_ref(
            {
                "type": "evaluation_report",
                "id": "evaluation-1",
                "task_id": "task-1",
                "run_id": "run-1",
                "digest": SHA,
            },
            expected_task_id="task-1",
            expected_run_id="run-1",
            require_producer_ready=False,
        )
        self.assertEqual(report.run_id, "run-1")
        self.assertEqual(
            exact_object_ref_endpoint(report),
            "/tasks/task-1/runs/run-1/evaluation-report",
        )

    def test_resolution_requires_digest_and_immutable_commit(self) -> None:
        canonical = {
            "type": "model_source_resolution",
            "id": "resolution-1",
            "task_id": "task-1",
            "digest": SHA,
            "resolved_commit": COMMIT,
        }
        self.assertEqual(
            normalize_object_ref(canonical, expected_task_id="task-1").resolved_commit,
            COMMIT,
        )
        for patch in ({"digest": None}, {"resolved_commit": "main"}):
            with self.subTest(patch=patch), self.assertRaises(ObjectRefValidationError):
                normalize_object_ref(
                    {**canonical, **patch}, expected_task_id="task-1"
                )

    def test_resource_kind_selects_one_exact_record_endpoint(self) -> None:
        for kind, segment in (
            ("resource_probe", "resource-probes"),
            ("environment_lock", "environment-locks"),
            ("resource_fit_report", "resource-fit-reports"),
        ):
            with self.subTest(kind=kind):
                ref = normalize_object_ref(
                    {
                        "type": "resource_feasibility",
                        "id": f"{kind}-1",
                        "task_id": "task-1",
                        "digest": SHA,
                        "record_kind": kind,
                    },
                    expected_task_id="task-1",
                )
                self.assertEqual(
                    exact_object_ref_endpoint(ref),
                    f"/tasks/task-1/{segment}/{kind}-1",
                )

    def test_unknown_missing_and_cross_scope_refs_fail_closed(self) -> None:
        invalid = (
            {"type": "made_up", "id": "x", "task_id": "task-1"},
            {"type": "model_source_search", "id": "x", "task_id": "task-1"},
            {
                "type": "model_source_search",
                "id": "x",
                "task_id": "task-2",
                "base_spec_revision": 1,
            },
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ObjectRefValidationError):
                normalize_object_ref(value, expected_task_id="task-1")
        with self.assertRaises(ObjectRefValidationError):
            normalize_object_refs(
                [
                    {
                        "type": "evaluation_report",
                        "id": "evaluation-1",
                        "task_id": "task-1",
                        "run_id": "run-2",
                        "digest": SHA,
                    }
                ],
                expected_task_id="task-1",
                expected_run_id="run-1",
                require_producer_ready=False,
            )

    def test_digest_sealed_run_producers_are_evidence_ready(self) -> None:
        for ref_type in ("evaluation_report", "artifact_bundle"):
            with self.subTest(ref_type=ref_type):
                ref = normalize_object_ref(
                    {
                        "type": ref_type,
                        "id": "object-1",
                        "task_id": "task-1",
                        "run_id": "run-1",
                        "digest": SHA,
                    },
                    expected_task_id="task-1",
                    expected_run_id="run-1",
                )
                self.assertEqual(ref.run_id, "run-1")

    def test_labels_redact_paths_and_credentials(self) -> None:
        for label in (
            "/Users/example/private/data.zip",
            "Authorization: Bearer secret-token",
            "hf_abcdefghijk private model",
        ):
            ref = normalize_object_ref(
                {
                    "type": "model_source_search",
                    "id": "search-1",
                    "task_id": "task-1",
                    "base_spec_revision": 1,
                    "label": label,
                },
                expected_task_id="task-1",
            )
            self.assertEqual(ref.label, "model source search")


if __name__ == "__main__":
    unittest.main()
