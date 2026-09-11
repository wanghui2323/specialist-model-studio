from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_v07_acceptance_runtime import (
    FAMILIES,
    prepare_acceptance_runtime,
)


class PrepareV07AcceptanceRuntimeTests(unittest.TestCase):
    def test_skip_hf_prepares_three_real_restartable_journeys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "acceptance-runtime"
            with patch(
                "scripts.prepare_v07_acceptance_runtime._run_once",
                side_effect=AssertionError("skip-HF mode must remain offline"),
            ):
                report = prepare_acceptance_runtime(
                    runtime_dir,
                    skip_hf=True,
                    user_approval_checkpoint_id=(
                        "test-user-approved:v0.7-acceptance-runtime"
                    ),
                )

            stored = json.loads(
                (runtime_dir / "journeys.json").read_text(encoding="utf-8")
            )
            self.assertEqual(stored, report)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["mode"], "local_image_skip_hf")
            self.assertEqual(tuple(report["journey_families"]), FAMILIES)
            self.assertTrue(report["restart"]["passed"])
            self.assertTrue(report["huggingface"]["skipped"])

            persistent_ids = (
                "task_id",
                "run_id",
                "evaluation_report_id",
                "inference_check_id",
                "artifact_bundle_id",
            )
            for family in FAMILIES:
                with self.subTest(family=family):
                    journey = report["journey_families"][family]
                    self.assertEqual(journey["training_status"], "completed")
                    self.assertEqual(journey["evaluation_status"], "passed")
                    self.assertEqual(
                        journey["evaluation_conclusion"], "release_ready"
                    )
                    self.assertEqual(journey["inference_status"], "passed")
                    self.assertEqual(journey["bundle_status"], "completed")
                    for identifier in persistent_ids:
                        self.assertIsInstance(journey[identifier], str)
                        self.assertTrue(journey[identifier])

                    restart = report["restart"]["families"][family]
                    self.assertTrue(restart["passed"])
                    self.assertTrue(all(restart["assertions"].values()))

            image = report["journey_families"]["image"]
            self.assertIsNone(image["model_asset_id"])
            self.assertEqual(image["image_source"], "builtin_image_recipe_skip_hf")

            audio = report["journey_families"]["audio"]
            self.assertIsInstance(audio["build_attempt_id"], str)
            self.assertTrue(audio["build_attempt_id"])
            self.assertIsInstance(audio["recipe_version_id"], str)
            self.assertTrue(audio["recipe_version_id"])

    def test_nonempty_runtime_is_rejected_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "acceptance-runtime"
            runtime_dir.mkdir()
            sentinel = runtime_dir / "keep.txt"
            sentinel.write_text("user-owned", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must be empty"):
                prepare_acceptance_runtime(runtime_dir, skip_hf=True)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned")
            self.assertFalse((runtime_dir / "journeys.json").exists())

    def test_user_approval_checkpoint_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "acceptance-runtime"

            with self.assertRaisesRegex(
                ValueError,
                "user_approval_checkpoint_id is required",
            ):
                prepare_acceptance_runtime(runtime_dir, skip_hf=True)

            self.assertTrue(runtime_dir.is_dir())
            self.assertFalse(any(runtime_dir.iterdir()))

    def test_official_mode_requires_an_immutable_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "acceptance-runtime"

            with self.assertRaisesRegex(ValueError, "immutable 40-character SHA"):
                prepare_acceptance_runtime(
                    runtime_dir,
                    skip_hf=False,
                    commit="main",
                )

            self.assertTrue(runtime_dir.is_dir())
            self.assertFalse(any(runtime_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
