from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from model_harness.blockers import (
    BLOCKER_EVIDENCE_STAGES,
    CANONICAL_BLOCKER_CODES,
    BlockerStore,
    verify_blocker_evidence,
)
from model_harness.errors import ContractError
from model_harness.io_utils import read_json, write_json


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_v01_blocker(
    root: str | Path,
    *,
    task_id: str,
    stage: str,
    marker: str,
) -> tuple[dict, Path]:
    semantic = {
        "task_id": task_id,
        "stage": stage,
        "code": f"legacy_{marker}",
        "retry_action": "retry_resource_probe",
        "related_object_type": None,
        "related_object_id": None,
        "related_object_digest": None,
        "details": {"marker": marker},
    }
    semantic_digest = _digest(semantic)
    blocker_id = f"blocker_{semantic_digest[:24]}"
    unsigned = {
        "schema_version": "0.1",
        "object_type": "BlockerEvidence",
        "blocker_id": blocker_id,
        **semantic,
        "message": f"legacy {marker}",
        "semantic_digest": semantic_digest,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
    }
    record = {**unsigned, "content_digest": _digest(unsigned)}
    path = (
        Path(root)
        / "tasks"
        / task_id
        / "blockers"
        / "evidence"
        / f"{blocker_id}.json"
    )
    write_json(path, record)
    return record, path


def _write_v02_blocker(
    root: str | Path,
    *,
    task_id: str,
    stage: str,
    code: str,
    marker: str,
) -> tuple[dict, Path]:
    with tempfile.TemporaryDirectory() as source_root:
        record = BlockerStore(source_root).append(
            task_id,
            stage=stage,
            code=code,
            message=f"v0.2 {marker}",
            retry_action="retry_resource_probe",
            details={"marker": marker},
        )
    record["schema_version"] = "0.2"
    record.pop("content_digest")
    record["content_digest"] = _digest(record)
    path = (
        Path(root)
        / "tasks"
        / task_id
        / "blockers"
        / "evidence"
        / f"{record['blocker_id']}.json"
    )
    write_json(path, record)
    return record, path


class BlockerStoreTests(unittest.TestCase):
    def test_resolved_recurrence_is_atomic_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            first = store.append(
                "task-process-race",
                stage="environment_lock",
                code="blocked_environment",
                message="runtime unavailable",
                retry_action="retry_resource_probe",
                details={"runtime": "missing"},
            )
            store.resolve(
                "task-process-race",
                first["blocker_id"],
                action="runtime_started",
            )
            script = (
                "from model_harness.blockers import BlockerStore; import sys; "
                "r=BlockerStore(sys.argv[1]).append("
                "'task-process-race',stage='environment_lock',"
                "code='blocked_environment',message='retry',"
                "retry_action='retry_resource_probe',"
                "details={'runtime':'missing'}); print(r['blocker_id'])"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script, temporary],
                    cwd=Path(__file__).resolve().parent.parent,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(4)
            ]
            outputs: list[str] = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(stdout.strip())
            self.assertEqual(len(set(outputs)), 1)
            records = BlockerStore(temporary).list("task-process-race")
            self.assertEqual(len(records), 2)
            self.assertEqual(
                [item["blocker_id"] for item in records if item["active"]],
                [outputs[0]],
            )

    def test_new_v02_supersedes_all_active_same_stage_and_code_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            old_one, old_one_path = _write_v02_blocker(
                temporary,
                task_id="task-v02-upgrade",
                stage="environment_lock",
                code="blocked_environment",
                marker="probe-one",
            )
            old_two, old_two_path = _write_v02_blocker(
                temporary,
                task_id="task-v02-upgrade",
                stage="environment_lock",
                code="blocked_environment",
                marker="probe-two",
            )
            other_code, _ = _write_v02_blocker(
                temporary,
                task_id="task-v02-upgrade",
                stage="environment_lock",
                code="blocked_platform",
                marker="platform",
            )
            old_bytes = {
                old_one["blocker_id"]: old_one_path.read_bytes(),
                old_two["blocker_id"]: old_two_path.read_bytes(),
            }

            store = BlockerStore(temporary)
            current = store.append(
                "task-v02-upgrade",
                stage="environment_lock",
                code="blocked_environment",
                message="new resource probe",
                retry_action="retry_resource_probe",
                details={"marker": "probe-three"},
            )
            records = {
                item["blocker_id"]: item
                for item in store.list("task-v02-upgrade")
            }
            self.assertFalse(records[old_one["blocker_id"]]["active"])
            self.assertFalse(records[old_two["blocker_id"]]["active"])
            self.assertTrue(records[other_code["blocker_id"]]["active"])
            self.assertTrue(records[current["blocker_id"]]["active"])
            self.assertEqual(
                old_one_path.read_bytes(), old_bytes[old_one["blocker_id"]]
            )
            self.assertEqual(
                old_two_path.read_bytes(), old_bytes[old_two["blocker_id"]]
            )

            duplicate = store.append(
                "task-v02-upgrade",
                stage="environment_lock",
                code="blocked_environment",
                message="same blocker, different display text",
                retry_action="retry_resource_probe",
                details={"marker": "probe-three"},
            )
            self.assertEqual(duplicate, current)
            restarted = BlockerStore(temporary)
            self.assertEqual(
                restarted.append(
                    "task-v02-upgrade",
                    stage="environment_lock",
                    code="blocked_environment",
                    message="same blocker after restart",
                    retry_action="retry_resource_probe",
                    details={"marker": "probe-three"},
                ),
                current,
            )
            active_ids = {
                item["blocker_id"]
                for item in restarted.list("task-v02-upgrade", active_only=True)
            }
            self.assertEqual(
                active_ids, {other_code["blocker_id"], current["blocker_id"]}
            )
            resolution_paths = list(
                (
                    Path(temporary)
                    / "tasks"
                    / "task-v02-upgrade"
                    / "blockers"
                    / "resolutions"
                ).glob("*.json")
            )
            self.assertEqual(len(resolution_paths), 2)
            resolutions = [read_json(path) for path in resolution_paths]
            self.assertEqual(
                {item["action"] for item in resolutions},
                {"superseded_by_newer_v0.2_blocker"},
            )
            self.assertEqual(
                {item["blocker_id"] for item in resolutions},
                {old_one["blocker_id"], old_two["blocker_id"]},
            )
            self.assertEqual(
                {item["related_object_id"] for item in resolutions},
                {current["blocker_id"]},
            )

    def test_v02_append_supersedes_only_same_stage_active_v01_after_restart(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            legacy, legacy_path = _write_v01_blocker(
                temporary,
                task_id="task-upgrade",
                stage="environment_lock",
                marker="environment",
            )
            other_stage, _ = _write_v01_blocker(
                temporary,
                task_id="task-upgrade",
                stage="source_resolution",
                marker="source",
            )
            legacy_bytes = legacy_path.read_bytes()

            restarted = BlockerStore(temporary)
            current = restarted.append(
                "task-upgrade",
                stage="environment_lock",
                code="blocked_environment",
                message="容器运行时仍不可用",
                retry_action="retry_resource_probe",
                details={"attempt": 2},
            )

            records = {
                item["blocker_id"]: item for item in restarted.list("task-upgrade")
            }
            self.assertFalse(records[legacy["blocker_id"]]["active"])
            self.assertTrue(records[other_stage["blocker_id"]]["active"])
            self.assertTrue(records[current["blocker_id"]]["active"])
            self.assertEqual(legacy_path.read_bytes(), legacy_bytes)
            resolution_paths = list(
                (
                    Path(temporary)
                    / "tasks"
                    / "task-upgrade"
                    / "blockers"
                    / "resolutions"
                ).glob("*.json")
            )
            self.assertEqual(len(resolution_paths), 1)
            resolution = read_json(resolution_paths[0])
            self.assertEqual(resolution["blocker_id"], legacy["blocker_id"])
            self.assertEqual(resolution["action"], "superseded_by_v0.2_blocker")
            self.assertEqual(resolution["related_object_id"], current["blocker_id"])
            after_restart = {
                item["blocker_id"]: item
                for item in BlockerStore(temporary).list("task-upgrade")
            }
            self.assertFalse(after_restart[legacy["blocker_id"]]["active"])

    def test_v02_retry_is_idempotent_across_restart(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            first = store.append(
                "task-retry",
                stage="environment_lock",
                code="blocked_environment",
                message="first",
                retry_action="retry_resource_probe",
                details={"attempt": 1},
            )
            legacy, _ = _write_v01_blocker(
                temporary,
                task_id="task-retry",
                stage="environment_lock",
                marker="late-legacy",
            )
            duplicate = store.append(
                "task-retry",
                stage="environment_lock",
                code="blocked_environment",
                message="display text changed",
                retry_action="retry_resource_probe",
                details={"attempt": 1},
            )
            self.assertEqual(duplicate, first)
            second = store.append(
                "task-retry",
                stage="environment_lock",
                code="blocked_environment",
                message="second",
                retry_action="retry_resource_probe",
                details={"attempt": 2},
            )

            restarted = BlockerStore(temporary)
            self.assertEqual(
                restarted.append(
                    "task-retry",
                    stage="environment_lock",
                    code="blocked_environment",
                    message="second retry",
                    retry_action="retry_resource_probe",
                    details={"attempt": 2},
                ),
                second,
            )
            active_ids = {
                item["blocker_id"]
                for item in restarted.list("task-retry", active_only=True)
            }
            self.assertEqual(active_ids, {second["blocker_id"]})
            self.assertNotIn(first["blocker_id"], active_ids)
            self.assertNotIn(legacy["blocker_id"], active_ids)
            resolution_paths = list(
                (
                    Path(temporary)
                    / "tasks"
                    / "task-retry"
                    / "blockers"
                    / "resolutions"
                ).glob("*.json")
            )
            self.assertEqual(len(resolution_paths), 2)

    def test_acceptance_schema_matches_runtime_enums_and_record_shape(self) -> None:
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "acceptance"
            / "v0.9-blocker-evidence.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(schema["properties"]["stage"]["enum"]),
            set(BLOCKER_EVIDENCE_STAGES),
        )
        self.assertEqual(
            set(schema["properties"]["code"]["enum"]),
            set(CANONICAL_BLOCKER_CODES),
        )
        self.assertIn("recipe_unavailable", CANONICAL_BLOCKER_CODES)
        with tempfile.TemporaryDirectory() as temporary:
            blocker = BlockerStore(temporary).append(
                "task-schema",
                stage="source_resolution",
                code="blocked_repository",
                message="来源解析失败",
                retry_action="retry_source_resolution",
            )
        self.assertEqual(set(blocker), set(schema["required"]))
        self.assertEqual(
            blocker["schema_version"],
            schema["properties"]["schema_version"]["const"],
        )

    def test_blocker_and_resolution_are_append_only_and_restart_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            blocker = store.append(
                "task-1",
                stage="source_resolution",
                code="blocked_repository",
                message="仓库或版本不存在",
                retry_action="edit_source_reference",
                details={"provider": "github", "reason_code": "github_not_found"},
            )
            duplicate = store.append(
                "task-1",
                stage="source_resolution",
                code="blocked_repository",
                message="不同展示文本不会改写原始事实",
                retry_action="edit_source_reference",
                details={"provider": "github", "reason_code": "github_not_found"},
            )
            self.assertEqual(duplicate, blocker)
            self.assertEqual(blocker["blocker_evidence_id"], blocker["blocker_id"])
            self.assertEqual(blocker["created_at"], blocker["created_at_utc"])
            self.assertIsNone(blocker["resolved_by"])
            self.assertEqual(
                verify_blocker_evidence(
                    {**blocker, "active": True}, allow_active_projection=True
                ),
                blocker,
            )
            self.assertEqual(len(store.list("task-1", active_only=True)), 1)
            resolution = store.resolve(
                "task-1",
                blocker["blocker_id"],
                action="source_resolved",
                related_object_type="SourceResolution",
                related_object_id="resolution-1",
            )
            self.assertEqual(resolution["blocker_digest"], blocker["content_digest"])
            self.assertEqual(store.list("task-1", active_only=True), [])
            restarted = BlockerStore(temporary)
            restarted_record = restarted.list("task-1")[0]
            self.assertFalse(restarted_record["active"])
            sealed_after_resolution = dict(restarted_record)
            sealed_after_resolution.pop("active")
            self.assertEqual(sealed_after_resolution, blocker)

    def test_resolved_blocker_recurrence_creates_new_active_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            arguments = {
                "stage": "resource_fit",
                "code": "blocked_resources",
                "message": "RAM is below the approved plan requirement",
                "retry_action": "review_resource_alternatives",
                "details": {"required_gib": 16, "observed_gib": 8},
            }
            first = store.append("task-recurrence", **arguments)
            store.resolve(
                "task-recurrence",
                first["blocker_id"],
                action="resource_fit_rechecked",
            )

            second = store.append("task-recurrence", **arguments)
            self.assertNotEqual(second["blocker_id"], first["blocker_id"])
            self.assertEqual(
                second["details"]["__blocker_store_identity_digest"],
                first["semantic_digest"],
            )
            self.assertEqual(second["details"]["__blocker_store_occurrence"], 1)
            self.assertEqual(
                store.append("task-recurrence", **arguments),
                second,
            )
            active = store.list("task-recurrence", active_only=True)
            self.assertEqual(
                [item["blocker_id"] for item in active],
                [second["blocker_id"]],
            )

            restarted = BlockerStore(temporary)
            self.assertEqual(
                restarted.append("task-recurrence", **arguments),
                second,
            )
            restarted.resolve(
                "task-recurrence",
                second["blocker_id"],
                action="resource_fit_rechecked_again",
            )
            third = restarted.append("task-recurrence", **arguments)
            self.assertNotIn(
                third["blocker_id"],
                {first["blocker_id"], second["blocker_id"]},
            )
            self.assertEqual(third["details"]["__blocker_store_occurrence"], 2)
            self.assertEqual(
                [
                    item["blocker_id"]
                    for item in restarted.list(
                        "task-recurrence",
                        active_only=True,
                    )
                ],
                [third["blocker_id"]],
            )

    def test_caller_cannot_inject_blocker_occurrence_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ContractError, "store-owned"):
                BlockerStore(temporary).append(
                    "task-occurrence-injection",
                    stage="resource_fit",
                    code="blocked_resources",
                    message="fake recurrence",
                    retry_action="review_resource_alternatives",
                    details={"__blocker_store_occurrence": 99},
                )

    def test_restart_rejects_cross_task_copied_and_renamed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            blocker = store.append(
                "task-source",
                stage="resource_fit",
                code="blocked_resources",
                message="source task blocker",
                retry_action="review_alternatives",
            )
            source_path = (
                Path(temporary)
                / "tasks"
                / "task-source"
                / "blockers"
                / "evidence"
                / f"{blocker['blocker_id']}.json"
            )
            copied_path = (
                Path(temporary)
                / "tasks"
                / "task-target"
                / "blockers"
                / "evidence"
                / source_path.name
            )
            copied_path.parent.mkdir(parents=True, exist_ok=True)
            copied_path.write_bytes(source_path.read_bytes())

            restarted = BlockerStore(temporary)
            with self.assertRaisesRegex(ContractError, "task identity mismatch"):
                restarted.list("task-target")
            self.assertEqual(
                restarted.get("task-source", blocker["blocker_id"]),
                blocker,
            )

            renamed_path = source_path.with_name("blocker_renamed.json")
            source_path.rename(renamed_path)
            with self.assertRaisesRegex(ContractError, "file identity mismatch"):
                BlockerStore(temporary).list("task-source")

    def test_restart_rejects_cross_task_copied_and_renamed_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            blocker = store.append(
                "task-source",
                stage="source_resolution",
                code="blocked_repository",
                message="source resolution blocker",
                retry_action="edit_source_reference",
            )
            resolution = store.resolve(
                "task-source",
                blocker["blocker_id"],
                action="source_resolved",
            )
            source_path = (
                Path(temporary)
                / "tasks"
                / "task-source"
                / "blockers"
                / "resolutions"
                / f"{resolution['resolution_id']}.json"
            )
            copied_path = (
                Path(temporary)
                / "tasks"
                / "task-target"
                / "blockers"
                / "resolutions"
                / source_path.name
            )
            copied_path.parent.mkdir(parents=True, exist_ok=True)
            copied_path.write_bytes(source_path.read_bytes())

            with self.assertRaisesRegex(ContractError, "task identity mismatch"):
                BlockerStore(temporary).list("task-target")

            renamed_path = source_path.with_name("blocker_resolution_renamed.json")
            source_path.rename(renamed_path)
            with self.assertRaisesRegex(ContractError, "file identity mismatch"):
                BlockerStore(temporary).list("task-source")

    def test_resolution_blocker_must_belong_to_requested_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            blocker = store.append(
                "task-source",
                stage="environment_lock",
                code="blocked_environment",
                message="source blocker",
                retry_action="retry_resource_probe",
            )
            resolution = store.resolve(
                "task-source",
                blocker["blocker_id"],
                action="environment_ready",
            )
            copied = dict(resolution)
            copied["task_id"] = "task-target"
            copied.pop("content_digest")
            copied["content_digest"] = _digest(copied)
            target_path = (
                Path(temporary)
                / "tasks"
                / "task-target"
                / "blockers"
                / "resolutions"
                / f"{copied['resolution_id']}.json"
            )
            write_json(target_path, copied)

            with self.assertRaisesRegex(ContractError, "outside requested task"):
                BlockerStore(temporary).list("task-target")

    def test_legacy_v01_evidence_remains_readable_with_identity_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            legacy, legacy_path = _write_v01_blocker(
                temporary,
                task_id="task-legacy-readable",
                stage="resource_fit",
                marker="legacy-readable",
            )
            restarted = BlockerStore(temporary)
            listed = restarted.list("task-legacy-readable")
            self.assertEqual(listed[0]["blocker_id"], legacy["blocker_id"])
            self.assertTrue(listed[0]["active"])

            copied_path = (
                Path(temporary)
                / "tasks"
                / "task-legacy-target"
                / "blockers"
                / "evidence"
                / legacy_path.name
            )
            copied_path.parent.mkdir(parents=True, exist_ok=True)
            copied_path.write_bytes(legacy_path.read_bytes())
            with self.assertRaisesRegex(ContractError, "task identity mismatch"):
                BlockerStore(temporary).list("task-legacy-target")

    def test_tamper_and_unsafe_values_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BlockerStore(temporary)
            blocker = store.append(
                "task-1",
                stage="resource_fit",
                code="blocked_resources",
                message="内存不足",
                retry_action="review_alternatives",
            )
            path = (
                Path(temporary)
                / "tasks"
                / "task-1"
                / "blockers"
                / "evidence"
                / f"{blocker['blocker_id']}.json"
            )
            value = read_json(path)
            value["message"] = "tampered"
            write_json(path, value)
            with self.assertRaisesRegex(ContractError, "digest mismatch"):
                store.list("task-1")
            with self.assertRaises(ContractError):
                store.append(
                    "../escape",
                    stage="resource_fit",
                    code="bad",
                    message="bad",
                    retry_action="bad",
                )
            with self.assertRaisesRegex(ContractError, "non-canonical"):
                BlockerStore(temporary).append(
                    "task-2",
                    stage="resource_fit",
                    code="insufficient_ram",
                    message="内存不足",
                    retry_action="review_alternatives",
                )
            with self.assertRaises(ContractError):
                BlockerStore(temporary).append(
                    "task-nan",
                    stage="resource_fit",
                    code="blocked_resources",
                    message="invalid numeric evidence",
                    retry_action="review_alternatives",
                    details={"observed": float("nan")},
                )


if __name__ == "__main__":
    unittest.main()
