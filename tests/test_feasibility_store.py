from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from model_harness.errors import ContractError
from model_harness.feasibility_store import (
    FeasibilityStore,
    FeasibilityStoreIntegrityError,
    StaleFeasibilityReferenceError,
)
from model_harness.io_utils import read_json, write_json
from model_harness.resource_feasibility import (
    EnvironmentLock,
    ResourceFitReport,
    ResourceProbe,
    canonical_sha256,
    evaluate_resource_fit,
)


PLAN_SHA256 = "a" * 64
IMAGE_DIGEST = f"sha256:{'b' * 64}"
PACKAGE_DIGEST = f"sha256:{'c' * 64}"


def _probe(probe_id: str = "probe_fixture") -> ResourceProbe:
    return ResourceProbe.from_observations(
        {
            "schema_version": "0.1",
            "object_type": "ResourceProbe",
            "resource_probe_id": probe_id,
            "captured_at": "2026-08-23T00:00:00+00:00",
            "os": {
                "available": True,
                "name": "linux",
                "release": "fixture",
                "reason": None,
            },
            "arch": {"available": True, "name": "x86_64", "reason": None},
            "cpu": {
                "available": True,
                "logical_count": 8,
                "model": "fixture",
                "reason": None,
            },
            "ram": {
                "available": True,
                "total_bytes": 32_000_000_000,
                "available_bytes": 16_000_000_000,
                "reason": None,
            },
            "disk": {
                "available": True,
                "path": "/fixture",
                "total_bytes": 200_000_000_000,
                "used_bytes": 100_000_000_000,
                "free_bytes": 100_000_000_000,
                "reason": None,
            },
            "python": {
                "available": True,
                "version": "3.12.0",
                "executable": "/python",
                "reason": None,
            },
            "node": {
                "available": False,
                "version": None,
                "executable": None,
                "reason": "node was not found",
            },
            "container_runtime": {
                "available": True,
                "runtime": "docker",
                "version": "fixture",
                "executable": "/docker",
                "reason": None,
            },
            "sandbox_worker": {
                "available": False,
                "reason": "v0.9 sandbox worker is not verified",
            },
            "accelerators": [],
            "accelerator_policy": {
                "mode": "cpu_only",
                "detected": [],
                "unusable_reason": "v0.9 is CPU-only",
            },
        }
    )


def _lock(lock_id: str = "envlock_fixture") -> EnvironmentLock:
    return EnvironmentLock.create(
        environment_lock_id=lock_id,
        source_snapshot_id="snapshot_fixture",
        platform_os="linux",
        platform_arch="x86_64",
        execution_backend="oci",
        base_image_digest=IMAGE_DIGEST,
        packages=(
            {
                "name": "torch",
                "version": "2.5.1",
                "hashes": [PACKAGE_DIGEST],
            },
        ),
        system_dependencies=("libgomp1=12.2",),
        network_allowlist=("pypi.org",),
    )


def _report(
    probe: ResourceProbe,
    lock: EnvironmentLock,
) -> ResourceFitReport:
    return evaluate_resource_fit(
        training_plan_revision_id="plan_fixture",
        training_plan_sha256=PLAN_SHA256,
        resource_budget={
            "max_seconds": 300,
            "ram_bytes": 4_000_000_000,
            "vram_bytes": 0,
            "disk_bytes": 5_000_000_000,
        },
        environment_lock=lock,
        resource_probe=probe,
        estimator_version="store-test/1",
    )


class FeasibilityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "workspace"
        self.task_id = "task_feasibility_fixture"
        write_json(
            self.root / "tasks" / self.task_id / "task.json",
            {"schema_version": "0.2", "task_id": self.task_id},
        )
        self.store = FeasibilityStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _append_chain(
        self,
    ) -> tuple[dict, dict, dict]:
        probe = _probe()
        lock = _lock()
        report = _report(probe, lock)
        return (
            self.store.append_resource_probe(self.task_id, probe),
            self.store.append_environment_lock(self.task_id, lock),
            self.store.append_resource_fit_report(self.task_id, report),
        )

    def _feasibility_root(self) -> Path:
        return self.root / "tasks" / self.task_id / "feasibility"

    def test_append_current_and_restart_round_trip(self) -> None:
        probe, lock, report = self._append_chain()
        self.assertEqual(
            self.store.current_bundle(self.task_id),
            {
                "resource_probe": probe,
                "environment_lock": lock,
                "resource_fit_report": report,
            },
        )
        self.assertEqual(self.store.list_resource_probes(self.task_id), [probe])
        self.assertEqual(self.store.list_environment_locks(self.task_id), [lock])
        self.assertEqual(
            self.store.list_resource_fit_reports(self.task_id), [report]
        )

        reopened = FeasibilityStore(self.root)
        self.assertEqual(reopened.current_resource_probe(self.task_id), probe)
        self.assertEqual(reopened.current_environment_lock(self.task_id), lock)
        self.assertEqual(reopened.current_resource_fit_report(self.task_id), report)
        self.assertEqual(
            reopened.get_resource_fit_report(
                self.task_id, report["resource_fit_report_id"]
            ),
            report,
        )

    def test_new_probe_invalidates_only_current_report_and_preserves_history(self) -> None:
        _old_probe, lock, report = self._append_chain()
        newer = self.store.append_resource_probe(
            self.task_id, _probe("probe_fixture_new")
        )
        self.assertEqual(self.store.current_resource_probe(self.task_id), newer)
        self.assertEqual(self.store.current_environment_lock(self.task_id), lock)
        self.assertIsNone(self.store.current_resource_fit_report(self.task_id))
        self.assertEqual(
            self.store.list_resource_fit_reports(self.task_id), [report]
        )

        with self.assertRaisesRegex(
            StaleFeasibilityReferenceError, "current probe"
        ):
            self.store.append_resource_fit_report(self.task_id, report)

    def test_fit_report_requires_current_probe_and_environment_lock(self) -> None:
        probe = _probe()
        lock = _lock()
        report = _report(probe, lock)
        with self.assertRaisesRegex(
            StaleFeasibilityReferenceError, "current probe and environment lock"
        ):
            self.store.append_resource_fit_report(self.task_id, report)

        self.store.append_resource_probe(self.task_id, probe)
        with self.assertRaisesRegex(
            StaleFeasibilityReferenceError, "current probe and environment lock"
        ):
            self.store.append_resource_fit_report(self.task_id, report)

        self.store.append_environment_lock(self.task_id, _lock("envlock_other"))
        with self.assertRaisesRegex(
            StaleFeasibilityReferenceError, "current environment lock"
        ):
            self.store.append_resource_fit_report(self.task_id, report)

    def test_resealed_contradictory_fit_decision_is_recomputed_and_rejected(self) -> None:
        observations = _probe().to_dict()
        observations.pop("probe_sha256")
        observations["resource_probe_id"] = "probe_insufficient"
        observations["ram"]["available_bytes"] = 1_000
        probe = ResourceProbe.from_observations(observations)
        lock = _lock()
        report = _report(probe, lock).to_dict()
        self.assertEqual(report["decision"], "blocked_resources")

        forged = dict(report)
        forged["decision"] = "fit"
        forged["alternatives"] = []
        semantic = {
            key: value
            for key, value in forged.items()
            if key not in {"resource_fit_report_id", "report_sha256"}
        }
        forged["resource_fit_report_id"] = (
            f"fit_{canonical_sha256(semantic)[:24]}"
        )
        unsigned = {
            key: value for key, value in forged.items() if key != "report_sha256"
        }
        forged["report_sha256"] = canonical_sha256(unsigned)
        forged_report = ResourceFitReport.from_dict(forged)

        self.store.append_resource_probe(self.task_id, probe)
        self.store.append_environment_lock(self.task_id, lock)
        with self.assertRaisesRegex(
            FeasibilityStoreIntegrityError, "deterministic evaluation"
        ):
            self.store.append_resource_fit_report(self.task_id, forged_report)

    def test_identical_append_is_idempotent_and_does_not_duplicate_event(self) -> None:
        probe = _probe()
        first = self.store.append_resource_probe(self.task_id, probe)
        second = self.store.append_resource_probe(self.task_id, probe.to_dict())
        self.assertEqual(first, second)
        events = list((self._feasibility_root() / "current_events").glob("*.json"))
        self.assertEqual(len(events), 1)
        self.assertEqual(self.store.list_resource_probes(self.task_id), [first])

    def test_resealed_record_tamper_fails_against_append_event(self) -> None:
        probe = self.store.append_resource_probe(self.task_id, _probe())
        path = (
            self._feasibility_root()
            / "resource_probes"
            / f"{probe['resource_probe_id']}.json"
        )
        changed = read_json(path)
        changed["cpu"]["logical_count"] = 999
        unsigned = {key: value for key, value in changed.items() if key != "probe_sha256"}
        changed["probe_sha256"] = canonical_sha256(unsigned)
        write_json(path, changed)

        with self.assertRaisesRegex(
            FeasibilityStoreIntegrityError, "changed record digest"
        ):
            self.store.get_resource_probe(self.task_id, probe["resource_probe_id"])

    def test_each_domain_record_digest_is_verified_on_read(self) -> None:
        probe, lock, report = self._append_chain()
        cases = [
            (
                self._feasibility_root()
                / "resource_probes"
                / f"{probe['resource_probe_id']}.json",
                "cpu",
                lambda value: value["cpu"].update({"logical_count": 999}),
            ),
            (
                self._feasibility_root()
                / "environment_locks"
                / f"{lock['environment_lock_id']}.json",
                "lock",
                lambda value: value["network_allowlist"].append("example.com"),
            ),
            (
                self._feasibility_root()
                / "resource_fit_reports"
                / f"{report['resource_fit_report_id']}.json",
                "report",
                lambda value: value.update({"decision": "blocked_resources"}),
            ),
        ]
        for path, label, mutate in cases:
            with self.subTest(label=label):
                original = path.read_bytes()
                value = read_json(path)
                mutate(value)
                write_json(path, value)
                with self.assertRaises(FeasibilityStoreIntegrityError):
                    self.store.current_bundle(self.task_id)
                path.write_bytes(original)

    def test_pointer_missing_or_stale_recovers_from_immutable_events(self) -> None:
        probe = self.store.append_resource_probe(self.task_id, _probe())
        pointer_path = self._feasibility_root() / "current.json"
        pointer_path.unlink()
        reopened = FeasibilityStore(self.root)
        self.assertEqual(reopened.current_resource_probe(self.task_id), probe)
        first_pointer = pointer_path.read_bytes()

        lock = reopened.append_environment_lock(self.task_id, _lock())
        pointer_path.write_bytes(first_pointer)
        after_interruption = FeasibilityStore(self.root)
        self.assertEqual(after_interruption.current_environment_lock(self.task_id), lock)
        self.assertEqual(read_json(pointer_path)["sequence"], 2)

    def test_pointer_and_event_tampering_fail_closed(self) -> None:
        self.store.append_resource_probe(self.task_id, _probe())
        pointer_path = self._feasibility_root() / "current.json"
        pointer = read_json(pointer_path)
        pointer["sequence"] = 999
        unsigned_pointer = {
            key: value for key, value in pointer.items() if key != "pointer_sha256"
        }
        pointer["pointer_sha256"] = canonical_sha256(unsigned_pointer)
        write_json(pointer_path, pointer)
        with self.assertRaisesRegex(
            FeasibilityStoreIntegrityError, "pointer"
        ):
            self.store.current_resource_probe(self.task_id)

        # Restore a verified pointer, then mutate and re-seal the immutable head.
        pointer_path.unlink()
        self.store.current_resource_probe(self.task_id)
        event_path = next(
            (self._feasibility_root() / "current_events").glob("*.json")
        )
        event = read_json(event_path)
        event["created_at"] = "tampered"
        unsigned = {key: value for key, value in event.items() if key != "event_sha256"}
        event["event_sha256"] = canonical_sha256(unsigned)
        write_json(event_path, event)
        with self.assertRaisesRegex(
            FeasibilityStoreIntegrityError, "pointer|chain"
        ):
            self.store.current_resource_probe(self.task_id)

    def test_task_scope_and_unsafe_paths_are_rejected(self) -> None:
        probe = self.store.append_resource_probe(self.task_id, _probe())
        other_task = "task_feasibility_other"
        write_json(
            self.root / "tasks" / other_task / "task.json",
            {"schema_version": "0.2", "task_id": other_task},
        )
        with self.assertRaises(FileNotFoundError):
            self.store.get_resource_probe(other_task, probe["resource_probe_id"])

        for unsafe in ("", ".", "..", "../escape", "/tmp/escape", "task\\escape"):
            with self.subTest(task_id=unsafe), self.assertRaises(ContractError):
                self.store.current_bundle(unsafe)

        linked_task = "task_feasibility_linked"
        linked_root = self.root / "tasks" / linked_task
        write_json(
            linked_root / "task.json",
            {"schema_version": "0.2", "task_id": linked_task},
        )
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (linked_root / "feasibility").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FeasibilityStoreIntegrityError):
            self.store.append_resource_probe(linked_task, _probe("probe_linked"))
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
