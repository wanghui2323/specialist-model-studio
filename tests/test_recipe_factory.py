from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from model_harness.errors import ContractError
from model_harness.io_utils import read_json, write_json
from model_harness.recipe_factory import RecipeFactory, RecipeSpec
from model_harness.recipe_versions import (
    RegistrationRecoveryRequired,
    StaleSpecRevisionError,
    VersionIntegrityError,
)
from model_harness.recipes.audio_keyword_plugin import (
    AUDIO_KEYWORD_TEMPLATE,
    SUPPORTED_CANDIDATES,
)


VALID_SPEC = {
    "schema_version": "0.1",
    "engine": "sklearn_audio_keyword_v1",
    "recipe_id": "audio-keyword-classification",
    "adapter_id": "audio-keyword-class-folder-zip",
    "features": {
        "kind": "mfcc_log_mel",
        "sample_rate_hz": 16_000,
        "clip_seconds": 1.0,
        "n_mels": 24,
        "n_mfcc": 13,
    },
    "candidates": [
        {"kind": "most_frequent_baseline"},
        {"kind": "logistic_regression"},
        {"kind": "extra_trees", "n_estimators": 160},
    ],
    "resources": {
        "device": "cpu",
        "max_candidate_models": 3,
        "max_audio_files": 20_000,
    },
    "evaluation": {
        "primary_metric": "validation_macro_f1",
        "metrics": ["accuracy", "macro_f1", "worst_class_recall"],
        "validation_fraction": 0.2,
        "test_fraction": 0.2,
        "seed": 42,
        "group_by": "speaker_id",
    },
}


def verified_registration_approval(
    checkpoint_id: str = "test-recipe-registration-checkpoint",
) -> dict[str, str]:
    return {
        "decision": "approved",
        "actor": "user",
        "checkpoint_id": checkpoint_id,
        "verified_by": "agent_bridge_token",
        "bridge_token_sha256": "a" * 64,
        "reason": "reviewed exact candidate and validation digests",
    }


def build_ready(factory: RecipeFactory, task_id: str = "task-a") -> dict:
    started = factory.start_build(
        task_id=task_id,
        base_spec_revision=3,
        spec=deepcopy(VALID_SPEC),
    )
    return factory.validate(started["attempt_id"])


class DeclarativeRecipeFactoryTests(unittest.TestCase):
    def test_build_attempt_persists_stages_candidate_report_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "factory"
            factory = RecipeFactory(root)
            self.assertEqual(factory.spec_template(), VALID_SPEC)
            self.assertEqual(RecipeSpec.parse(VALID_SPEC).to_dict(), VALID_SPEC)
            started = factory.start_build(
                task_id="task-a",
                base_spec_revision=3,
                spec=deepcopy(VALID_SPEC),
            )
            self.assertEqual(started["status"], "authoring")

            finished = factory.validate(started["attempt_id"])
            self.assertEqual(finished["status"], "awaiting_registration")
            self.assertEqual(len(finished["candidate_digest"]), 64)
            self.assertEqual(len(finished["validation_digest"]), 64)
            self.assertTrue(factory.validation_report(started["attempt_id"])["valid"])
            self.assertEqual(
                factory.validation_report(started["attempt_id"])[
                    "candidate_digest"
                ],
                finished["candidate_digest"],
            )
            self.assertEqual(
                [event["type"] for event in factory.events(started["attempt_id"])],
                [
                    "build.authoring_started",
                    "build.validation_started",
                    "build.validation_passed",
                ],
            )

            restarted = RecipeFactory(root)
            self.assertEqual(
                restarted.get_attempt(started["attempt_id"]),
                finished,
            )
            self.assertEqual(
                restarted.candidate(started["attempt_id"])["engine"],
                "sklearn_audio_keyword_v1",
            )
            candidate = restarted.candidate(started["attempt_id"])
            self.assertEqual(
                candidate["adapter_manifest"]["file_extensions"], [".zip"]
            )
            self.assertEqual(
                candidate["recipe_manifest"]["target_kinds"],
                ["multiclass", "binary"],
            )
            self.assertEqual(
                candidate["compiled_contract_overrides"]["model_selection"][
                    "candidates"
                ],
                [
                    "most_frequent_baseline",
                    "logistic_regression",
                    "extra_trees",
                ],
            )
            compiled = candidate["compiled_contract_overrides"]
            self.assertTrue(
                set(compiled["model_selection"]["candidates"])
                <= SUPPORTED_CANDIDATES
            )
            for section in (
                "model_selection",
                "recipe_options",
                "compute_budget",
                "dataset",
            ):
                self.assertTrue(
                    set(compiled[section]) <= set(AUDIO_KEYWORD_TEMPLATE[section])
                )

    def test_restart_resumes_a_persisted_validating_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "factory"
            factory = RecipeFactory(root, recover=False)
            started = factory.start_build(
                task_id="task-recover",
                base_spec_revision=1,
                spec=deepcopy(VALID_SPEC),
            )
            state_path = (
                root / "build_attempts" / started["attempt_id"] / "state.json"
            )
            interrupted = read_json(state_path)
            interrupted["status"] = "validating"
            write_json(state_path, interrupted)

            restarted = RecipeFactory(root, recover=True)
            self.assertEqual(len(restarted.recovered_attempts), 1)
            self.assertEqual(
                restarted.get_attempt(started["attempt_id"])["status"],
                "awaiting_registration",
            )

    def test_malicious_and_unknown_fields_never_create_a_candidate(self) -> None:
        mutations = {
            "code": lambda spec: spec.update({"code": "print('owned')"}),
            "shell": lambda spec: spec["resources"].update(
                {"shell": "rm -rf /tmp/example"}
            ),
            "url": lambda spec: spec.update(
                {"url": "https://example.invalid/plugin.py"}
            ),
            "dependencies": lambda spec: spec.update(
                {"dependencies": ["unsafe-package"]}
            ),
            "path": lambda spec: spec["features"].update(
                {"path": "../../private"}
            ),
            "dynamic_import": lambda spec: spec["candidates"][0].update(
                {"dynamic_import": "evil.module"}
            ),
            "unknown": lambda spec: spec.update({"mystery": True}),
            "untrusted_recipe_id": lambda spec: spec.update(
                {"recipe_id": "user-supplied-recipe"}
            ),
            "untrusted_adapter_id": lambda spec: spec.update(
                {"adapter_id": "user-supplied-adapter"}
            ),
            "unsupported_candidate": lambda spec: spec["candidates"].__setitem__(
                0, {"kind": "linear_svc"}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                spec = deepcopy(VALID_SPEC)
                mutate(spec)
                factory = RecipeFactory(Path(temp_dir) / "factory")
                started = factory.start_build(
                    task_id=f"task-{label}",
                    base_spec_revision=1,
                    spec=spec,
                )
                failed = factory.validate(started["attempt_id"])
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["failure"]["code"], "invalid_recipe_spec")
                self.assertFalse(
                    (
                        Path(temp_dir)
                        / "factory"
                        / "build_attempts"
                        / started["attempt_id"]
                        / "candidate.json"
                    ).exists()
                )

    def test_python_build_is_blocked_without_persisting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "factory"
            factory = RecipeFactory(root)
            attempt = factory.request_python_build(
                task_id="task-python",
                base_spec_revision=1,
                python_source="import os\nos.system('unsafe')",
            )
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(attempt["failure"]["code"], "blocked_environment")
            attempt_root = root / "build_attempts" / attempt["attempt_id"]
            self.assertFalse((attempt_root / "recipe_spec.json").exists())
            self.assertFalse((attempt_root / "candidate.json").exists())
            self.assertNotIn(
                "os.system",
                "".join(
                    path.read_text(encoding="utf-8")
                    for path in attempt_root.iterdir()
                    if path.is_file()
                ),
            )

    def test_cancel_and_reject_leave_no_active_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            factory = RecipeFactory(Path(temp_dir) / "factory")
            authoring = factory.start_build(
                task_id="task-cancel",
                base_spec_revision=1,
                spec=deepcopy(VALID_SPEC),
            )
            cancelled = factory.cancel(authoring["attempt_id"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertIsNone(factory.version_store.active_for_task("task-cancel"))

            ready = build_ready(factory, "task-reject")
            factory.prepare_registration(ready["attempt_id"])
            rejected = factory.reject_registration(
                ready["attempt_id"],
                actor="user-1",
                reason="not approved",
            )
            self.assertEqual(rejected["status"], "rejected")
            self.assertIsNone(factory.version_store.active_for_task("task-reject"))

    def test_stale_spec_revision_and_digest_change_cannot_activate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            factory = RecipeFactory(Path(temp_dir) / "factory")
            ready = build_ready(factory, "task-stale")
            intent = factory.prepare_registration(ready["attempt_id"])
            with self.assertRaises(ContractError):
                factory.register(
                    ready["attempt_id"],
                    approval={
                        **verified_registration_approval(),
                        "actor": "",
                    },
                    candidate_digest=ready["candidate_digest"],
                    validation_digest=ready["validation_digest"],
                    current_spec_revision=3,
                )
            self.assertIsNone(factory.version_store.active_for_task("task-stale"))
            with self.assertRaises(StaleSpecRevisionError):
                factory.register(
                    ready["attempt_id"],
                    approval=verified_registration_approval(),
                    candidate_digest=ready["candidate_digest"],
                    validation_digest=ready["validation_digest"],
                    current_spec_revision=4,
                )
            self.assertIsNone(factory.version_store.active_for_task("task-stale"))
            self.assertEqual(
                factory.version_store.get_intent(intent["intent_id"])["status"],
                "awaiting_approval",
            )

            with self.assertRaises(VersionIntegrityError):
                factory.register(
                    ready["attempt_id"],
                    approval=verified_registration_approval(),
                    candidate_digest="0" * 64,
                    validation_digest=ready["validation_digest"],
                    current_spec_revision=3,
                )
            self.assertIsNone(factory.version_store.active_for_task("task-stale"))

            tamper_ready = build_ready(factory, "task-tamper")
            tamper_intent = factory.prepare_registration(
                tamper_ready["attempt_id"]
            )
            candidate_path = (
                Path(temp_dir)
                / "factory"
                / "versions"
                / "registration_intents"
                / tamper_intent["intent_id"]
                / "candidate.json"
            )
            changed_candidate = read_json(candidate_path)
            changed_candidate["recipe_spec"]["resources"][
                "max_audio_files"
            ] = 19_999
            write_json(candidate_path, changed_candidate)
            with self.assertRaises(VersionIntegrityError):
                factory.register(
                    tamper_ready["attempt_id"],
                    approval=verified_registration_approval(
                        "test-tamper-registration-checkpoint"
                    ),
                    candidate_digest=tamper_ready["candidate_digest"],
                    validation_digest=tamper_ready["validation_digest"],
                    current_spec_revision=3,
                )
            self.assertIsNone(factory.version_store.active_for_task("task-tamper"))

    def test_approved_registration_calls_binding_and_activates_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            factory = RecipeFactory(Path(temp_dir) / "factory")
            ready = build_ready(factory, "task-register")
            factory.prepare_registration(ready["attempt_id"])
            calls: list[tuple[str, str, str]] = []

            def activate(recipe, adapter, candidate, intent) -> None:
                calls.append(
                    (
                        recipe["version_id"],
                        adapter["version_id"],
                        intent["intent_id"],
                    )
                )
                self.assertEqual(
                    candidate["engine"], "sklearn_audio_keyword_v1"
                )

            registered = factory.register(
                ready["attempt_id"],
                approval=verified_registration_approval(
                    "test-approved-registration-checkpoint"
                ),
                candidate_digest=ready["candidate_digest"],
                validation_digest=ready["validation_digest"],
                current_spec_revision=3,
                activate=activate,
            )
            self.assertEqual(registered["status"], "registered")
            self.assertEqual(
                registered["approval"]["checkpoint_id"],
                "test-approved-registration-checkpoint",
            )
            self.assertEqual(
                registered["approval"]["verified_by"],
                "agent_bridge_token",
            )
            self.assertEqual(len(registered["approval"]["approval_sha256"]), 64)
            self.assertEqual(len(calls), 1)
            active = factory.version_store.active_for_task("task-register")
            self.assertEqual(active["intent_id"], registered["intent_id"])
            self.assertEqual(
                factory.get_attempt(ready["attempt_id"])["status"],
                "registered",
            )

    def test_failed_binding_is_replayed_by_transaction_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "factory"
            factory = RecipeFactory(root)
            ready = build_ready(factory, "task-recovery")
            intent = factory.prepare_registration(ready["attempt_id"])

            def fail_once(_recipe, _adapter, _candidate, _intent) -> None:
                raise RuntimeError("simulated crash during binding")

            with self.assertRaises(RegistrationRecoveryRequired):
                factory.register(
                    ready["attempt_id"],
                    approval=verified_registration_approval(
                        "test-recovery-registration-checkpoint"
                    ),
                    candidate_digest=ready["candidate_digest"],
                    validation_digest=ready["validation_digest"],
                    current_spec_revision=3,
                    activate=fail_once,
                )
            self.assertIsNone(factory.version_store.active_for_task("task-recovery"))
            self.assertEqual(
                factory.version_store.get_intent(intent["intent_id"])["status"],
                "recovery_required",
            )

            replayed: list[str] = []

            def replay(_recipe, _adapter, _candidate, selected_intent) -> None:
                replayed.append(selected_intent["intent_id"])

            restarted_factory = RecipeFactory(root)
            recovered = restarted_factory.recover_registrations(
                resolve_spec_revision=lambda task_id: 3,
                activate=replay,
            )
            self.assertEqual(recovered[0]["status"], "registered")
            self.assertEqual(replayed, [intent["intent_id"]])
            self.assertIsNotNone(
                restarted_factory.version_store.active_for_task("task-recovery")
            )
            self.assertEqual(
                restarted_factory.get_attempt(ready["attempt_id"])["status"],
                "registered",
            )


if __name__ == "__main__":
    unittest.main()
