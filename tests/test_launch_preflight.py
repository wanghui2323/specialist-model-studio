from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from model_harness.errors import ContractError
from model_harness.io_utils import read_json
from model_harness.launch_preflight import (
    evaluate_launch_resource_preflight,
    validate_launch_resource_policy,
)


def runnable_contract() -> dict[str, object]:
    return {
        "task_id": "launch-preflight-fixture",
        "business_goal": "verify the launch resource gate",
        "recipe": "fixture-recipe",
        "interaction": {"mode": "guided"},
        "human_gates": ["confirm_launch"],
        "optimization": {
            "mode": "recommend",
            "require_approval": True,
        },
    }


class _FixtureManifest:
    plugin_id = "fixture-recipe"
    version = "test"


class _FixturePlugin:
    manifest = _FixtureManifest()

    def validate_contract(self, contract: dict[str, object]) -> None:
        del contract

    def train(self, contract: dict[str, object]) -> object:
        del contract
        raise AssertionError("training must not start after a blocked preflight")


class _FixtureRegistry:
    def __init__(self) -> None:
        self.plugin = _FixturePlugin()

    def get_recipe(self, plugin_id: str) -> _FixturePlugin:
        if plugin_id != self.plugin.manifest.plugin_id:
            raise AssertionError(f"unexpected fixture plugin: {plugin_id}")
        return self.plugin


def _load_runner_without_training_dependencies():
    """Load runner for a gate-only test without importing local ML wheels."""

    numpy = types.ModuleType("numpy")
    numpy.__version__ = "test"  # type: ignore[attr-defined]
    numpy.ndarray = type("ndarray", (), {})  # type: ignore[attr-defined]
    numpy.generic = type("generic", (), {})  # type: ignore[attr-defined]
    joblib = types.ModuleType("joblib")
    joblib.__version__ = "test"  # type: ignore[attr-defined]
    sklearn = types.ModuleType("sklearn")
    sklearn.__version__ = "test"  # type: ignore[attr-defined]
    sample_inference = types.ModuleType("model_harness.sample_inference")
    sample_inference.SampleInference = type(  # type: ignore[attr-defined]
        "SampleInference",
        (),
        {},
    )
    with patch.dict(
        sys.modules,
        {
            "joblib": joblib,
            "numpy": numpy,
            "sklearn": sklearn,
            "model_harness.sample_inference": sample_inference,
        },
    ):
        from model_harness import runner

    return runner


def launch_policy() -> dict[str, int]:
    return {
        "checkpoint_size_bytes": 100,
        "retained_checkpoint_copies": 2,
        "peak_checkpoint_copies": 3,
        "artifact_reserve_bytes": 50,
        "minimum_free_disk_bytes_after_peak": 100,
        "minimum_available_ram_bytes": 500,
        "maximum_swap_used_bytes": 200,
    }


def observation(
    *,
    disk_free: int = 1_000,
    ram_available: int = 1_000,
    swap_used: int = 0,
) -> dict[str, int | str]:
    return {
        "captured_at_utc": "2026-08-26T00:00:00+00:00",
        "disk_path": "/fixture",
        "disk_free_bytes": disk_free,
        "available_ram_bytes": ram_available,
        "swap_used_bytes": swap_used,
    }


class LaunchResourcePreflightTests(unittest.TestCase):
    def test_peak_checkpoint_copies_drive_disk_gate_not_retained_count(self) -> None:
        contract = {"launch_resource_policy": launch_policy()}

        report = evaluate_launch_resource_preflight(
            contract,
            disk_path=".",
            observation=observation(disk_free=449),
        )

        self.assertEqual(report["decision"], "blocked")
        self.assertEqual(
            report["requirements"]["peak_checkpoint_bytes"],
            300,
        )
        self.assertEqual(
            report["requirements"]["required_free_disk_bytes_at_launch"],
            450,
        )
        disk_check = next(
            item
            for item in report["checks"]
            if item["code"] == "checkpoint_peak_disk_reserve"
        )
        self.assertFalse(disk_check["passed"])

    def test_swap_ceiling_and_ram_floor_are_launch_blockers(self) -> None:
        contract = {"launch_resource_policy": launch_policy()}

        report = evaluate_launch_resource_preflight(
            contract,
            disk_path=".",
            observation=observation(ram_available=499, swap_used=201),
        )

        self.assertEqual(report["decision"], "blocked")
        failed = {
            item["code"]
            for item in report["checks"]
            if item["passed"] is not True
        }
        self.assertEqual(failed, {"available_ram_floor", "swap_used_ceiling"})

    def test_policy_must_model_new_checkpoint_before_pruning(self) -> None:
        policy = launch_policy()
        policy["peak_checkpoint_copies"] = policy[
            "retained_checkpoint_copies"
        ]

        with self.assertRaisesRegex(ContractError, "before retained checkpoints"):
            validate_launch_resource_policy(policy)

    def test_runner_blocks_before_plugin_train_and_persists_preflight_event(self) -> None:
        runner = _load_runner_without_training_dependencies()
        contract = deepcopy(runnable_contract())
        contract["launch_resource_policy"] = launch_policy()
        blocked_report = evaluate_launch_resource_preflight(
            contract,
            disk_path=".",
            observation=observation(disk_free=449),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = _FixtureRegistry()
            run_dir = runner.prepare_run(
                contract,
                temp_dir,
                run_id="blocked-launch",
                registry=registry,
            )
            plugin = registry.get_recipe(str(contract["recipe"]))
            with patch(
                "model_harness.runner.evaluate_launch_resource_preflight",
                return_value=blocked_report,
            ), patch.object(plugin, "train") as train:
                with self.assertRaisesRegex(
                    ContractError,
                    "launch resource preflight blocked training",
                ):
                    runner.execute_run(run_dir, registry=registry)

            train.assert_not_called()
            self.assertEqual(
                read_json(run_dir / "run_state.json")["status"],
                "failed",
            )
            events = [
                json.loads(line)
                for line in (run_dir / "events.ndjson").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            resource_event = next(
                item
                for item in events
                if item["type"] == "preflight.launch_resources_checked"
            )
            self.assertEqual(resource_event["payload"]["decision"], "blocked")


if __name__ == "__main__":
    unittest.main()
