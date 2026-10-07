from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from model_harness.local_resources import capture_local_resource_inventory
from model_harness.server import create_app


def observations():
    private = "PRIVATE_MARKER_DO_NOT_EXPOSE"
    return {
        "captured_at": "2026-10-04T04:00:00+00:00",
        "hostname": private, "credentials": {"token": private},
        "probe_sha256": private, "resource_probe_id": private,
        "cpu": {"available": True, "logical_count": 12, "model": "Example CPU", "reason": private},
        "ram": {"available": True, "total_bytes": 32 * 1024**3, "available_bytes": 20 * 1024**3},
        "disk": {"available": True, "total_bytes": 1000 * 1024**3, "free_bytes": 300 * 1024**3, "path": "/Users/" + private},
        "os": {"name": "darwin", "release": "25.0.0", "hostname": private},
        "arch": {"name": "arm64"},
        "python": {"available": True, "version": "3.12.13", "executable": "/Users/" + private + "/python"},
        "node": {"available": True, "version": "v24.11.0", "executable": "/opt/" + private + "/node"},
        "container_runtime": {"runtime": "docker", "available": False, "version": "Docker version 28.0.4", "executable": "/opt/" + private, "installed_candidates": [{"secret": private}], "reason": private},
        "accelerators": [
            {"kind": "mps", "detected": True, "available": True, "memory_bytes": None, "reason": private},
            {"kind": "cuda", "detected": True, "available": True, "devices": [{"name": "Example GPU", "memory_bytes": 24 * 1024**3, "uuid": private, "host": private}]},
        ],
    }


class LocalResourcesTests(unittest.TestCase):
    def test_binary_gib_fields_are_calculated_from_bytes_and_preserve_unknown(self):
        for size, expected in [(19327352832, 18.0), (1000000000, 0.93), (0, 0.0), (None, None)]:
            with self.subTest(size_bytes=size):
                raw = observations()
                raw["ram"].update(total_bytes=size, available_bytes=size)
                raw["disk"].update(total_bytes=size, free_bytes=size)
                raw["accelerators"][0]["memory_bytes"] = size
                raw["accelerators"][1]["devices"][0]["memory_bytes"] = size
                with patch("model_harness.local_resources.ResourceProbe.capture", return_value=SimpleNamespace(to_dict=lambda: raw)):
                    inventory = capture_local_resource_inventory(Path("."))
                for record, byte_field, gib_field in [
                    (inventory["ram"], "total_bytes", "total_gib"),
                    (inventory["ram"], "available_bytes", "available_gib"),
                    (inventory["disk"], "total_bytes", "total_gib"),
                    (inventory["disk"], "free_bytes", "free_gib"),
                    (inventory["accelerators"][0], "memory_bytes", "memory_gib"),
                    (inventory["accelerators"][1]["devices"][0], "memory_bytes", "memory_gib"),
                ]:
                    self.assertEqual(record[byte_field], size)
                    self.assertEqual(record[gib_field], expected)

    def test_inventory_allowlist_redacts_internal_probe_fields_and_seals_public_facts(self):
        raw = observations()
        with patch("model_harness.local_resources.ResourceProbe.capture", return_value=SimpleNamespace(to_dict=lambda: deepcopy(raw))):
            inventory = capture_local_resource_inventory(Path("/server/configured/runs"))
        text = json.dumps(inventory)
        self.assertNotIn("PRIVATE_MARKER", text)
        self.assertNotIn("/Users/", text)
        self.assertNotIn("executable", text)
        self.assertNotIn("hostname", text)
        self.assertNotIn("credentials", text)
        self.assertEqual(inventory["object_type"], "LocalResourceInventory")
        self.assertTrue(inventory["observation_only"])
        self.assertFalse(inventory["model_fit_assessed"])
        self.assertFalse(inventory["execution_authorized"])
        self.assertEqual(inventory["cpu"]["logical_count"], 12)
        self.assertEqual(inventory["accelerators"][1]["devices"][0]["memory_bytes"], 24 * 1024**3)
        self.assertTrue(all(gpu["detected"] for gpu in inventory["accelerators"]))
        self.assertTrue(all(gpu["available"] is False for gpu in inventory["accelerators"]))
        self.assertEqual(inventory["executor_policy"], {"mode": "cpu_only", "accelerators_enabled": False})
        self.assertFalse(inventory["runtime"]["container"]["daemon_reachable"])
        digest = inventory.pop("observation_sha256")
        canonical = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(digest, hashlib.sha256(canonical.encode()).hexdigest())

    def test_unknown_readings_are_not_zero_and_labels_cannot_leak_paths_or_environment(self):
        raw = observations()
        raw["cpu"] = {"available": False, "logical_count": None, "model": "/private/host-info"}
        raw["ram"] = {"available": False, "total_bytes": None, "available_bytes": None}
        raw["node"]["version"] = "TOKEN=secret\nHOME=/private/location"
        with patch("model_harness.local_resources.ResourceProbe.capture", return_value=SimpleNamespace(to_dict=lambda: raw)):
            inventory = capture_local_resource_inventory(Path("."))
        self.assertFalse(inventory["cpu"]["detected"])
        self.assertIsNone(inventory["cpu"]["logical_count"])
        self.assertIsNone(inventory["cpu"]["model"])
        self.assertIsNone(inventory["ram"]["available_bytes"])
        self.assertIsNone(inventory["runtime"]["node"]["version"])
        self.assertNotIn("secret", json.dumps(inventory))

    def test_endpoint_needs_no_task_plan_or_approval_and_does_not_mutate_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = Path(temporary) / "runs"
            app = create_app(runs)
            runtime = app.state.conversation_runtime
            workspace = app.state.training_workspace
            def snapshot():
                return {path.relative_to(runs).as_posix(): path.read_bytes() for path in runs.rglob("*") if path.is_file()}
            with (
                patch.object(runtime, "start"), patch.object(runtime, "stop"),
                patch.object(workspace, "create_task", side_effect=AssertionError("must not create a task")),
                patch.object(workspace, "create_training_plan", side_effect=AssertionError("must not create a plan")),
                patch.object(workspace, "check_resource_feasibility", side_effect=AssertionError("must not invoke an approved-plan check")),
                patch.object(app.state.run_service, "submit", side_effect=AssertionError("must not start a Run")),
                patch("model_harness.local_resources.ResourceProbe.capture", return_value=SimpleNamespace(to_dict=observations)) as capture,
                TestClient(app) as client,
            ):
                before = snapshot()
                response = client.get("/resources/local")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["local_resources"]["cpu"]["logical_count"], 12)
                self.assertEqual(snapshot(), before)
                capture.assert_called_once_with(app.state.run_service.runs_dir)
                self.assertEqual(client.get("/tasks").json()["tasks"], [])
                capture.reset_mock()
                self.assertEqual(client.get("/resources/local", params={"path": "/private/secret"}).status_code, 422)
                capture.assert_not_called()
                with patch("model_harness.server.capture_local_resource_inventory", side_effect=RuntimeError("SECRET /Users/private")):
                    failed = client.get("/resources/local")
                self.assertEqual(failed.status_code, 503)
                self.assertNotIn("SECRET", failed.text)
                self.assertNotIn("/Users/", failed.text)
                self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
