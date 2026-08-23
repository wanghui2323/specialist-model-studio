from __future__ import annotations

import json
import platform
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from model_harness.resource_feasibility import (
    EnvironmentLock,
    ResourceFeasibilityError,
    ResourceFitReport,
    ResourceProbe,
    canonical_sha256,
    evaluate_resource_fit,
)


SHA = "a" * 64
IMAGE_DIGEST = f"sha256:{'b' * 64}"
PACKAGE_DIGEST = f"sha256:{'c' * 64}"


def probe_observations(
    *,
    os_name: str = "linux",
    arch: str = "x86_64",
    ram_bytes: int | None = 16_000_000_000,
    disk_bytes: int | None = 100_000_000_000,
    container_available: bool = True,
    detected: tuple[str, ...] = (),
) -> dict:
    return {
        "schema_version": "0.1",
        "object_type": "ResourceProbe",
        "resource_probe_id": "probe_fixture",
        "captured_at": "2026-08-23T00:00:00+00:00",
        "os": {
            "available": True,
            "name": os_name,
            "release": "fixture",
            "reason": None,
        },
        "arch": {"available": True, "name": arch, "reason": None},
        "cpu": {
            "available": True,
            "logical_count": 8,
            "model": "fixture",
            "reason": None,
        },
        "ram": {
            "available": ram_bytes is not None,
            "total_bytes": 32_000_000_000 if ram_bytes is not None else None,
            "available_bytes": ram_bytes,
            "reason": None if ram_bytes is not None else "RAM probe failed",
        },
        "disk": {
            "available": disk_bytes is not None,
            "path": "/fixture",
            "total_bytes": 200_000_000_000 if disk_bytes is not None else None,
            "used_bytes": 100_000_000_000 if disk_bytes is not None else None,
            "free_bytes": disk_bytes,
            "reason": None if disk_bytes is not None else "disk probe failed",
        },
        "python": {
            "available": True,
            "version": "3.11.0",
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
            "available": container_available,
            "runtime": "docker" if container_available else None,
            "version": "fixture" if container_available else None,
            "executable": "/docker" if container_available else None,
            "reason": None if container_available else "runtime unavailable",
        },
        "sandbox_worker": {
            "available": False,
            "reason": "v0.9 sandbox worker is not verified",
        },
        "accelerators": [
            {
                "kind": kind,
                "detected": True,
                "available": False,
                "reason": "detected but v0.9 is CPU-only",
            }
            for kind in detected
        ],
        "accelerator_policy": {
            "mode": "cpu_only",
            "detected": list(detected),
            "unusable_reason": "v0.9 is CPU-only",
        },
    }


def environment_lock(
    *,
    os_name: str = "linux",
    arch: str = "x86_64",
    backend: str = "oci",
) -> EnvironmentLock:
    return EnvironmentLock.create(
        environment_lock_id="envlock_fixture",
        source_snapshot_id="snapshot_fixture",
        platform_os=os_name,
        platform_arch=arch,
        execution_backend=backend,
        base_image_digest=IMAGE_DIGEST,
        packages=(
            {
                "name": "torch",
                "version": "2.5.1",
                "hashes": [PACKAGE_DIGEST],
            },
        ),
        system_dependencies=("libgomp1=12.2",),
        network_allowlist=("pypi.org", "files.pythonhosted.org"),
    )


class CanonicalDigestTests(unittest.TestCase):
    def test_object_key_order_does_not_change_digest(self) -> None:
        left = {"outer": {"z": 2, "a": 1}, "name": "模型"}
        right = {"name": "模型", "outer": {"a": 1, "z": 2}}
        self.assertEqual(canonical_sha256(left), canonical_sha256(right))

    def test_non_finite_float_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            canonical_sha256({"unsafe": float("nan")})


class ResourceProbeTests(unittest.TestCase):
    def test_real_probe_reports_host_facts_without_claiming_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe = ResourceProbe.capture(temp_dir)
        record = probe.to_dict()

        self.assertTrue(record["os"]["available"])
        self.assertTrue(record["arch"]["available"])
        self.assertTrue(record["cpu"]["available"])
        self.assertTrue(record["ram"]["available"])
        self.assertTrue(record["disk"]["available"])
        self.assertTrue(record["python"]["available"])
        self.assertIsInstance(record["node"]["available"], bool)
        self.assertIsInstance(record["container_runtime"]["available"], bool)
        self.assertEqual(record["accelerator_policy"]["mode"], "cpu_only")
        for accelerator in record["accelerators"]:
            self.assertFalse(accelerator["available"])
            self.assertTrue(accelerator["reason"])
        unsigned = {key: value for key, value in record.items() if key != "probe_sha256"}
        self.assertEqual(record["probe_sha256"], canonical_sha256(unsigned))

    def test_unavailable_capability_requires_reason(self) -> None:
        record = probe_observations()
        record["node"]["reason"] = None
        with self.assertRaisesRegex(
            ResourceFeasibilityError, "unavailable ResourceProbe node requires reason"
        ):
            ResourceProbe.from_observations(record)

    def test_detected_accelerator_cannot_be_marked_available(self) -> None:
        record = probe_observations(detected=("mps",))
        record["accelerators"][0]["available"] = True
        with self.assertRaisesRegex(ResourceFeasibilityError, "must be unavailable"):
            ResourceProbe.from_observations(record)

    def test_policy_detection_must_match_accelerator_facts(self) -> None:
        record = probe_observations(detected=("mps",))
        record["accelerator_policy"]["detected"] = []
        with self.assertRaisesRegex(ResourceFeasibilityError, "does not match probe facts"):
            ResourceProbe.from_observations(record)

    def test_unverified_isolation_capabilities_cannot_be_claimed_available(self) -> None:
        unsupported_runtime = probe_observations()
        unsupported_runtime["container_runtime"].update(
            {"runtime": None, "executable": None}
        )
        with self.assertRaisesRegex(
            ResourceFeasibilityError, "supported runtime and executable"
        ):
            ResourceProbe.from_observations(unsupported_runtime)

        unverified_worker = probe_observations()
        unverified_worker["sandbox_worker"].update(
            {"available": True, "reason": None}
        )
        with self.assertRaisesRegex(
            ResourceFeasibilityError, "sandbox worker must remain unavailable"
        ):
            ResourceProbe.from_observations(unverified_worker)

    def test_tampered_probe_digest_is_rejected(self) -> None:
        probe = ResourceProbe.from_observations(probe_observations())
        tampered = probe.to_dict()
        tampered["cpu"]["logical_count"] = 999
        with self.assertRaisesRegex(ResourceFeasibilityError, "probe_sha256 mismatch"):
            ResourceProbe.from_dict(tampered)

    def test_returned_dict_cannot_mutate_sealed_probe(self) -> None:
        probe = ResourceProbe.from_observations(probe_observations())
        first_digest = probe.probe_sha256
        copy = probe.to_dict()
        copy["cpu"]["logical_count"] = 1
        self.assertEqual(probe.probe_sha256, first_digest)
        self.assertEqual(probe.to_dict()["cpu"]["logical_count"], 8)


class EnvironmentLockTests(unittest.TestCase):
    def test_valid_lock_is_canonical_and_immutable(self) -> None:
        lock = environment_lock()
        record = lock.to_dict()
        unsigned = {key: value for key, value in record.items() if key != "lock_sha256"}
        self.assertEqual(record["lock_sha256"], canonical_sha256(unsigned))
        self.assertEqual(record["accelerator_policy"]["mode"], "cpu_only")
        record["packages"][0]["version"] = "tampered"
        self.assertEqual(lock.to_dict()["packages"][0]["version"], "2.5.1")

    def test_lock_survives_verified_round_trip(self) -> None:
        lock = environment_lock()
        restored = EnvironmentLock.from_dict(
            json.loads(json.dumps(lock.to_dict(), ensure_ascii=False))
        )
        self.assertEqual(restored.lock_sha256, lock.lock_sha256)

    def test_tampered_lock_digest_is_rejected(self) -> None:
        record = environment_lock().to_dict()
        record["network_allowlist"].append("example.com")
        with self.assertRaisesRegex(ResourceFeasibilityError, "lock_sha256 mismatch"):
            EnvironmentLock.from_dict(record)

    def test_rejects_drifting_or_unsafe_environment_inputs(self) -> None:
        valid = {
            "source_snapshot_id": "snapshot_fixture",
            "platform_os": "linux",
            "platform_arch": "x86_64",
            "execution_backend": "oci",
            "base_image_digest": IMAGE_DIGEST,
            "packages": (
                {"name": "torch", "version": "2.5.1", "hashes": [PACKAGE_DIGEST]},
            ),
        }
        cases = {
            "image tag": {"base_image_digest": "python:3.11"},
            "unhashed package": {
                "packages": ({"name": "torch", "version": "2.5.1", "hashes": []},)
            },
            "unversioned package": {
                "packages": ({"name": "torch", "version": "*", "hashes": [PACKAGE_DIGEST]},)
            },
            "wildcard network": {"network_allowlist": ("*.example.com",)},
            "gpu package": {
                "packages": (
                    {"name": "torch", "version": "2.5.1+cu121", "hashes": [PACKAGE_DIGEST]},
                )
            },
            "gpu system dependency": {"system_dependencies": ("cuda-toolkit=12",)},
            "unversioned system dependency": {
                "system_dependencies": ("libgomp1",)
            },
        }
        for label, replacement in cases.items():
            with self.subTest(label=label):
                arguments = {**valid, **replacement}
                with self.assertRaises(ResourceFeasibilityError):
                    EnvironmentLock.create(**arguments)

    def test_rejects_non_cpu_policy_on_deserialization(self) -> None:
        record = environment_lock().to_dict()
        record["accelerator_policy"]["mode"] = "cuda"
        unsigned = {key: value for key, value in record.items() if key != "lock_sha256"}
        record["lock_sha256"] = canonical_sha256(unsigned)
        with self.assertRaisesRegex(ResourceFeasibilityError, "must be cpu_only"):
            EnvironmentLock.from_dict(record)

    def test_rejects_hidden_gpu_availability_flag(self) -> None:
        record = environment_lock().to_dict()
        record["accelerator_policy"]["available"] = True
        unsigned = {key: value for key, value in record.items() if key != "lock_sha256"}
        record["lock_sha256"] = canonical_sha256(unsigned)
        with self.assertRaisesRegex(ResourceFeasibilityError, "cannot make a GPU available"):
            EnvironmentLock.from_dict(record)


class ResourceFitReportTests(unittest.TestCase):
    def evaluate(
        self,
        probe: ResourceProbe,
        *,
        lock: EnvironmentLock | None = None,
        ram_bytes: int = 8_000_000_000,
        disk_bytes: int = 10_000_000_000,
        vram_bytes: int = 0,
    ) -> ResourceFitReport:
        return evaluate_resource_fit(
            training_plan_revision_id="plan_fixture",
            training_plan_sha256=SHA,
            resource_budget={
                "max_seconds": 300,
                "ram_bytes": ram_bytes,
                "disk_bytes": disk_bytes,
                "vram_bytes": vram_bytes,
            },
            environment_lock=lock or environment_lock(),
            resource_probe=probe,
            estimator_version="fixture-estimator/1",
        )

    def test_fit_binds_all_three_digests_and_quantifies_reasons(self) -> None:
        probe = ResourceProbe.from_observations(probe_observations())
        lock = environment_lock()
        report = self.evaluate(probe, lock=lock).to_dict()

        self.assertEqual(report["decision"], "fit")
        self.assertEqual(report["training_plan_sha256"], SHA)
        self.assertEqual(report["environment_lock_sha256"], lock.lock_sha256)
        self.assertEqual(report["resource_probe_sha256"], probe.probe_sha256)
        self.assertEqual(report["alternatives"], [])
        for reason in report["reasons"]:
            self.assertEqual(
                set(("required", "observed", "unit", "evidence_ref", "estimator_version"))
                - set(reason),
                set(),
            )
            self.assertIn(probe.probe_sha256, reason["evidence_ref"])

    def test_insufficient_resources_block_with_new_plan_suggestion(self) -> None:
        probe = ResourceProbe.from_observations(
            probe_observations(ram_bytes=2_000, disk_bytes=3_000)
        )
        budget = {
            "max_seconds": 300,
            "ram_bytes": 4_000,
            "disk_bytes": 5_000,
            "vram_bytes": 0,
        }
        original = deepcopy(budget)
        report = evaluate_resource_fit(
            training_plan_revision_id="plan_fixture",
            training_plan_sha256=SHA,
            resource_budget=budget,
            environment_lock=environment_lock(),
            resource_probe=probe,
        ).to_dict()

        self.assertEqual(report["decision"], "blocked_resources")
        self.assertEqual(budget, original)
        self.assertTrue(report["alternatives"])
        self.assertTrue(report["alternatives"][0]["creates_new_plan"])
        codes = {reason["code"] for reason in report["reasons"]}
        self.assertIn("insufficient_ram", codes)
        self.assertIn("insufficient_disk", codes)

    def test_missing_container_runtime_blocks_environment(self) -> None:
        probe = ResourceProbe.from_observations(
            probe_observations(container_available=False)
        )
        report = self.evaluate(probe).to_dict()
        self.assertEqual(report["decision"], "blocked_environment")
        self.assertIn(
            "container_runtime_unavailable",
            {reason["code"] for reason in report["reasons"]},
        )

    def test_platform_mismatch_blocks_platform(self) -> None:
        probe = ResourceProbe.from_observations(
            probe_observations(os_name="darwin", arch="arm64")
        )
        report = self.evaluate(
            probe,
            lock=environment_lock(backend="os_sandbox_worker"),
        ).to_dict()
        self.assertEqual(report["decision"], "blocked_platform")
        codes = {reason["code"] for reason in report["reasons"]}
        self.assertIn("platform_os_mismatch", codes)
        self.assertIn("platform_arch_mismatch", codes)

    def test_unverified_os_sandbox_worker_blocks_environment(self) -> None:
        probe = ResourceProbe.from_observations(
            probe_observations(container_available=False)
        )
        report = self.evaluate(
            probe,
            lock=environment_lock(backend="os_sandbox_worker"),
        ).to_dict()
        self.assertEqual(report["decision"], "blocked_environment")
        self.assertIn(
            "sandbox_worker_unverified",
            {reason["code"] for reason in report["reasons"]},
        )

    def test_gpu_budget_is_blocked_even_when_accelerator_is_detected(self) -> None:
        probe = ResourceProbe.from_observations(
            probe_observations(detected=("cuda",))
        )
        report = self.evaluate(probe, vram_bytes=1_000_000).to_dict()
        self.assertEqual(report["decision"], "blocked_platform")
        self.assertIn(
            "accelerator_forbidden_by_cpu_only_policy",
            {reason["code"] for reason in report["reasons"]},
        )
        self.assertEqual(report["alternatives"][0]["changes"]["resource_budget"]["vram_bytes"], 0)

    def test_unavailable_measurement_blocks_instead_of_guessing(self) -> None:
        probe = ResourceProbe.from_observations(probe_observations(ram_bytes=None))
        report = self.evaluate(probe).to_dict()
        self.assertEqual(report["decision"], "blocked_environment")
        reason = next(
            item for item in report["reasons"] if item["code"] == "ram_observation_unavailable"
        )
        self.assertEqual(reason["observed"], "unavailable")

    def test_tampered_report_digest_is_rejected(self) -> None:
        probe = ResourceProbe.from_observations(probe_observations())
        record = self.evaluate(probe).to_dict()
        record["decision"] = "blocked_resources"
        with self.assertRaisesRegex(ResourceFeasibilityError, "report_sha256 mismatch"):
            ResourceFitReport.from_dict(record)

    def test_report_id_and_digest_are_deterministic_for_same_evidence(self) -> None:
        probe = ResourceProbe.from_observations(probe_observations())
        first = self.evaluate(probe).to_dict()
        second = self.evaluate(probe).to_dict()
        self.assertEqual(first["resource_fit_report_id"], second["resource_fit_report_id"])
        self.assertEqual(first["report_sha256"], second["report_sha256"])

    def test_actual_host_can_be_classified_without_execution_or_download(self) -> None:
        host_os = platform.system().lower()
        host_arch = platform.machine().lower()
        if host_arch == "aarch64":
            host_arch = "arm64"
        if host_arch == "amd64":
            host_arch = "x86_64"
        if host_os not in {"darwin", "linux"} or host_arch not in {"arm64", "x86_64"}:
            self.skipTest("fixture lock only covers the v0.9 platform contract")
        with tempfile.TemporaryDirectory() as temp_dir:
            probe = ResourceProbe.capture(Path(temp_dir))
        report = self.evaluate(
            probe,
            lock=environment_lock(os_name="linux", arch=host_arch),
            ram_bytes=0,
            disk_bytes=0,
        ).to_dict()
        self.assertIn(
            report["decision"],
            {"fit", "blocked_environment"},
        )
        self.assertNotIn("fit_with_changes", report["decision"])


if __name__ == "__main__":
    unittest.main()
