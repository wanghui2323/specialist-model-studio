from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.acceptance_evidence import (
    SchemaValidationError,
    sha256_file,
    validate_json_schema,
)
from scripts import verify_v07_beta as runner
from scripts import collect_v07_external_evidence as producer


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
CHALLENGE = "b" * 32
RUN_ID = "evidence-20260822T000000Z-deadbeef"
REQUIRED_CHECKS = ["python-full-suite", "deepseek-harness-suite"]
COMMAND = [
    str(ROOT / ".venv" / "bin" / "python"),
    str(ROOT / "scripts" / "collect_v07_external_evidence.py"),
    "--fixture",
]
TEST_TOOL_PATH = str(Path(sys.executable).absolute())
TEST_TOOLS = {
    name: TEST_TOOL_PATH
    for name in ("python", "git", "node", "npm", "uv", "chrome")
}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reference(root: Path, path: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _family_ids(family: str) -> dict:
    return {
        "task_id": f"task-{family}",
        "run_id": f"run-{family}",
        "evaluation_report_id": f"evaluation-{family}",
        "inference_check_id": f"inference-{family}",
        "artifact_bundle_id": f"bundle-{family}",
    }


def _snapshot(family: str) -> dict:
    selected = {
        **_family_ids(family),
        "training_status": "completed",
        "evaluation_conclusion": "release_ready",
        "inference_status": "passed",
        "bundle_status": "completed",
        "bundle_sha256": "c" * 64,
        "bundle_download_sha256": "c" * 64,
        "event_count": 4,
        "event_last_seq": 4,
    }
    if family == "image":
        selected["model_asset_id"] = "asset-image"
    if family == "audio":
        selected["build_attempt_id"] = "build-audio"
        selected["recipe_version_id"] = "recipe-version-audio"
    return selected


def _browser_run(width: int, height: int) -> dict:
    name = "desktop" if width == 1440 else "mobile"
    return {
        "viewport": {"width": width, "height": height},
        "start_url": "http://127.0.0.1:9999/app?task=task-image",
        "end_url": "http://127.0.0.1:9999/app?task=task-audio",
        "drafts": {
            "first_task_id": "task-image",
            "second_task_id": "task-tabular",
            "first_value_sha256": runner.hashlib.sha256(f"controlled-first-{RUN_ID}-{name}".encode()).hexdigest(),
            "second_value_sha256": runner.hashlib.sha256(f"controlled-second-{RUN_ID}-{name}".encode()).hexdigest(),
            "first_restored": True,
            "first_survived_reload": True,
            "second_restored": True,
        },
        "families": {
            family: {
                **_family_ids(family),
                "evaluation_text": "release_ready",
                "bundle_text": f"bundle-{family}",
            }
            for family in ("image", "tabular", "audio")
        },
        "measurements": {
            "horizontal_overflow_px": 0,
            "primary_targets": [
                {"selector": "#one", "width": 44, "height": 44},
                {"selector": "#two", "width": 44, "height": 44},
                {"selector": "#three", "width": 44, "height": 44},
            ],
            "context_reachable": True,
            "results_reachable": True,
        },
        "console_error_count": 0,
        "request_failure_count": 0,
        "http_error_count": 0,
    }


def build_evidence(root: Path) -> Path:
    artifacts = root / "artifacts"
    journeys = {
        "schema_version": "0.1",
        "status": "passed",
        "mode": "official_hf_fixed_commit",
        "journey_families": {
            "image": {**_snapshot("image")},
            "tabular": {**_snapshot("tabular")},
            "audio": {**_snapshot("audio")},
        },
    }
    browser_report = {
        "schema_version": "0.1",
        "source_commit": COMMIT,
        "producer_run_id": RUN_ID,
        "runs": [_browser_run(1440, 900), _browser_run(390, 844)],
    }
    process_report = {
        "schema_version": "0.1",
        "source_commit": COMMIT,
        "producer_run_id": RUN_ID,
        "base_url": "http://127.0.0.1:9999",
        "before_pid": 111,
        "after_pid": 222,
        "before_exit_code": 0,
        "old_port_closed": True,
        "health_status_after": 200,
        "openapi_status_after": 200,
        "before": {family: _snapshot(family) for family in ("image", "tabular", "audio")},
        "after": {family: _snapshot(family) for family in ("image", "tabular", "audio")},
    }
    command_ids = ["clone", "checkout", "uv_sync", "python_tests", "node_ci", "node_tests", "node_check", "browser_ci", "minimal_loop"]
    cold_commands = [
        {"id": item, "argv": [item], "exit_code": 0, "duration_seconds": 0.1}
        for item in command_ids
    ]
    cold_report = {
        "schema_version": "0.1",
        "source_commit": COMMIT,
        "producer_run_id": RUN_ID,
        "clone_method": "git_clone_no_local_no_hardlinks",
        "resolved_commit": COMMIT,
        "worktree_clean_before_run": True,
        "preexisting_runs": False,
        "preexisting_model_cache": False,
        "commands": cold_commands,
        "minimal_family_ids": {family: _family_ids(family) for family in ("image", "tabular", "audio")},
    }
    minimal = {
        "status": "passed",
        "mode": "local_image_skip_hf",
        "journey_families": {family: _family_ids(family) for family in ("image", "tabular", "audio")},
    }
    files = {
        "journeys": artifacts / "runtime" / "journeys.json",
        "hf": artifacts / "runtime" / "hf-report.json",
        "browser": artifacts / "browser" / "browser-report.json",
        "process": artifacts / "process" / "process-restart-report.json",
        "cold": artifacts / "cold-clone" / "cold-clone-report.json",
        "minimal": artifacts / "cold-clone" / "minimal-journeys.json",
    }
    for path, value in ((files["journeys"], journeys), (files["hf"], {"status": "passed"}), (files["browser"], browser_report), (files["process"], process_report), (files["cold"], cold_report), (files["minimal"], minimal)):
        _write_json(path, value)
    (artifacts / "process" / "before.log").write_text("before\n", encoding="utf-8")
    (artifacts / "process" / "after.log").write_text("after\n", encoding="utf-8")
    command_log = artifacts / "cold-clone" / "commands.ndjson"
    command_log.write_text("\n".join(json.dumps({**item, "cwd": "/tmp", "output": "ok"}) for item in cold_commands) + "\n", encoding="utf-8")
    for viewport in ("desktop", "mobile"):
        directory = artifacts / "browser" / viewport
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "final.png").write_bytes(b"not-inspected-by-loader")
        (directory / "network.ndjson").write_text('{"kind":"producer"}\n', encoding="utf-8")
        (directory / "console.ndjson").write_text('{"kind":"producer"}\n', encoding="utf-8")
        (directory / "trace.zip").write_bytes(b"trace")
    source_files = {
        key: {"path": relative, "sha256": sha256_file(ROOT / relative)}
        for key, relative in runner.CONTROLLED_SOURCE_FILES.items()
    }
    manifest = {
        "schema_version": "0.3",
        "source_commit": COMMIT,
        "generated_at_utc": "2026-08-22T00:00:00+00:00",
        "producer": {
            "id": "model-harness-v07-controlled-producer",
            "version": "0.3.0",
            "status": "completed",
            "run_id": RUN_ID,
            "verifier_challenge": CHALLENGE,
            "python_version": "3.12.0",
            "node_version": "v24.0.0",
            "playwright_core_version": "1.62.1",
            "command": COMMAND,
            "source_files": source_files,
            "tools": {
                name: {
                    "path": path,
                    "resolved_path": str(Path(path).resolve(strict=True)),
                    "sha256": sha256_file(Path(path).resolve(strict=True)),
                }
                for name, path in TEST_TOOLS.items()
            },
        },
        "runtime": {"mode": "official_hf_fixed_commit", "base_url": "http://127.0.0.1:9999", "after_pid": 222, "journeys": _reference(root, files["journeys"]), "hf_report": _reference(root, files["hf"])},
        "browser": {
            "report": _reference(root, files["browser"]),
            **{
                viewport: {
                    key: _reference(root, artifacts / "browser" / viewport / filename)
                    for key, filename in {"screenshot": "final.png", "network_log": "network.ndjson", "console_log": "console.ndjson", "trace": "trace.zip"}.items()
                }
                for viewport in ("desktop", "mobile")
            },
        },
        "process_restart": {"report": _reference(root, files["process"]), "before_log": _reference(root, artifacts / "process" / "before.log"), "after_log": _reference(root, artifacts / "process" / "after.log")},
        "cold_clone": {"report": _reference(root, files["cold"]), "command_log": _reference(root, command_log), "minimal_journeys": _reference(root, files["minimal"])},
    }
    manifest_path = root / "external-evidence.json"
    _write_json(manifest_path, manifest)
    return manifest_path


class AcceptanceEvidenceTests(unittest.TestCase):
    def test_controlled_family_requests_percent_encode_unicode_ids(self) -> None:
        journey = {
            "task_id": "中文任务-1234",
            "run_id": "运行-5678",
            "inference_check_id": "试跑-9012",
            "artifact_bundle_id": "产物-3456",
        }
        requested: list[str] = []

        def fake_json(url: str) -> tuple[int, dict]:
            requested.append(url)
            if url.endswith("/result"):
                return 200, {"run_id": journey["run_id"], "status": "completed"}
            if url.endswith("/evaluation-report"):
                return 200, {"evaluation_report": {"report_id": "evaluation-1", "conclusion": "release_ready"}}
            if "/sample-inferences/" in url:
                return 200, {"sample_inference": {"check_id": journey["inference_check_id"], "status": "passed"}}
            if "/artifact-bundles/" in url:
                return 200, {"artifact_bundle": {"bundle_id": journey["artifact_bundle_id"], "status": "completed", "archive": {"sha256": "c" * 64}}}
            if url.endswith("/events"):
                return 200, {"events": [{"seq": 1}]}
            if url.endswith("/model-assets/current/verify"):
                return 200, {"ok": True}
            return 200, {"task": {"task_id": journey["task_id"], "selected_model_asset_id": "asset-1"}}

        def fake_bytes(url: str, *, timeout: float = 5.0) -> tuple[int, bytes, str]:
            del timeout
            requested.append(url)
            return 200, b"bundle", "application/zip"

        with patch.object(producer, "_http_json", side_effect=fake_json), patch.object(
            producer,
            "_http_bytes",
            side_effect=fake_bytes,
        ):
            snapshot = producer._collect_family("http://127.0.0.1:8765", "image", journey)

        self.assertEqual(snapshot["task_id"], journey["task_id"])
        self.assertTrue(all(url.isascii() for url in requested))
        self.assertTrue(any("%E4%B8%AD%E6%96%87" in url for url in requested))

    def test_controlled_environment_drops_execution_injection_variables(self) -> None:
        poisoned = {
            "PATH": "/tmp/attacker-bin",
            "PYTHONPATH": "/tmp/python-hook",
            "PYTHONHOME": "/tmp/python-home",
            "NODE_OPTIONS": "--require=/tmp/node-hook.js",
            "NODE_PATH": "/tmp/node-modules",
            "NPM_CONFIG_SCRIPT_SHELL": "/tmp/fake-shell",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "/tmp/git-hook",
            "DYLD_INSERT_LIBRARIES": "/tmp/inject.dylib",
            "BASH_ENV": "/tmp/bash-hook",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            poisoned,
            clear=False,
        ):
            environment = runner._redacted_environment(
                Path(temporary),
                TEST_TOOLS,
            )
        self.assertNotIn("/tmp/attacker-bin", environment["PATH"])
        for key in poisoned:
            if key != "PATH":
                self.assertNotIn(key, environment)
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(environment["NPM_CONFIG_USERCONFIG"], "/dev/null")
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertEqual(environment["HF_HUB_DISABLE_XET"], "1")
        self.assertTrue(
            environment["HF_HUB_CACHE"].startswith(str(Path(temporary)))
        )

    def test_strict_schema_validator_covers_nested_unknown_const_and_pattern(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["nested"],
            "properties": {
                "nested": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "sha"],
                    "properties": {"kind": {"const": "trusted"}, "sha": {"type": "string", "pattern": "^[a-f0-9]{4}$"}},
                }
            },
        }
        validate_json_schema({"nested": {"kind": "trusted", "sha": "abcd"}}, schema)
        for invalid in (
            {"nested": {"kind": "trusted", "sha": "abcd", "extra": True}},
            {"nested": {"kind": "untrusted", "sha": "abcd"}},
            {"nested": {"kind": "trusted", "sha": "XYZ"}},
        ):
            with self.assertRaises(SchemaValidationError):
                validate_json_schema(invalid, schema)

    def test_controlled_manifest_is_bound_to_challenge_command_sources_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = build_evidence(root)
            loaded, blockers = runner._read_external_evidence(
                path,
                source_commit=COMMIT,
                expected_challenge=CHALLENGE,
                expected_command=COMMAND,
                expected_tools=TEST_TOOLS,
                producer_status="passed",
            )
            self.assertEqual(blockers, [])
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.manifest_sha256, sha256_file(path))

            stale, stale_blockers = runner._read_external_evidence(
                path,
                source_commit=COMMIT,
                expected_challenge="d" * 32,
                expected_command=COMMAND,
                expected_tools=TEST_TOOLS,
                producer_status="passed",
            )
            self.assertIsNone(stale)
            self.assertIn("external_evidence_challenge_mismatch", stale_blockers)

    def test_nested_unknown_field_and_artifact_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = build_evidence(root)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["browser"]["desktop"]["untrusted"] = True
            _write_json(path, manifest)
            loaded, blockers = runner._read_external_evidence(path, source_commit=COMMIT, expected_challenge=CHALLENGE, expected_command=COMMAND, expected_tools=TEST_TOOLS, producer_status="passed")
            self.assertIsNone(loaded)
            self.assertIn("external_evidence_schema_or_read_failure", blockers)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = build_evidence(root)
            (root / "artifacts" / "browser" / "desktop" / "network.ndjson").write_text('{"kind":"forged"}\n', encoding="utf-8")
            loaded, blockers = runner._read_external_evidence(path, source_commit=COMMIT, expected_challenge=CHALLENGE, expected_command=COMMAND, expected_tools=TEST_TOOLS, producer_status="passed")
            self.assertIsNone(loaded)
            self.assertIn("external_artifact_invalid:browser.desktop.network_log", blockers)

    def test_tool_provenance_tamper_and_lease_identity_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = build_evidence(root)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["producer"]["tools"]["node"]["sha256"] = "f" * 64
            _write_json(path, manifest)
            loaded, blockers = runner._read_external_evidence(
                path,
                source_commit=COMMIT,
                expected_challenge=CHALLENGE,
                expected_command=COMMAND,
                expected_tools=TEST_TOOLS,
                producer_status="passed",
            )
            self.assertIsNone(loaded)
            self.assertIn("trusted_tool_provenance_mismatch:node", blockers)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            base_url = "http://127.0.0.1:9999"
            command = [
                TEST_TOOLS["python"],
                "-m",
                "model_harness.cli",
                "serve",
                "--runs-dir",
                str(runtime),
                "--host",
                "127.0.0.1",
                "--port",
                "9999",
            ]
            lease = {
                "schema_version": "0.2",
                "source_commit": COMMIT,
                "verifier_challenge": CHALLENGE,
                "producer_run_id": RUN_ID,
                "pid": 222,
                "base_url": base_url,
                "start_token": "1" * 64,
                "observed_command_sha256": "2" * 64,
                "expected_argv_sha256": runner.hashlib.sha256(
                    json.dumps(command, separators=(",", ":")).encode()
                ).hexdigest(),
            }
            lease_path = root / "service-lease.json"
            _write_json(lease_path, lease)
            with patch.object(runner, "pid_is_alive", return_value=True), patch.object(
                runner,
                "_terminate_controlled_pid",
            ) as terminate:
                stopped, pid = runner._cleanup_controlled_service_lease(
                    lease_path,
                    expected_challenge=CHALLENGE,
                    expected_source_commit=COMMIT,
                    expected_run_id="evidence-20260822T000000Z-bad0bad0",
                    expected_pid=222,
                    expected_base_url=base_url,
                    expected_runtime_dir=runtime,
                    trusted_tools=TEST_TOOLS,
                    environment=runner._redacted_environment(root / "env", TEST_TOOLS),
                )
            self.assertFalse(stopped)
            self.assertIsNone(pid)
            terminate.assert_not_called()

    def test_release_gate_uses_api_objects_and_blocks_when_api_unavailable(self) -> None:
        first_page = [
            {
                "id": index,
                "name": (
                    REQUIRED_CHECKS[0]
                    if index == 1
                    else f"informational-{index}"
                ),
                "status": "completed",
                "conclusion": "success",
                "head_sha": COMMIT,
                "html_url": f"https://github.test/check/{index}",
            }
            for index in range(1, 101)
        ]
        second_page = [
            {
                "id": 101,
                "name": REQUIRED_CHECKS[1],
                "status": "completed",
                "conclusion": "success",
                "head_sha": COMMIT,
                "html_url": "https://github.test/check/101",
            }
        ]

        def fake_api(path: str):
            if path.endswith(f"commits/{COMMIT}"):
                return "passed", {"sha": COMMIT, "html_url": "https://github.test/commit"}, ""
            if path.endswith("/pulls"):
                return "passed", [{"merged_at": "2026-08-22T00:00:00Z", "merge_commit_sha": COMMIT, "head": {"sha": "d" * 40}, "html_url": "https://github.test/pr"}], ""
            if "/check-runs?" in path and "&page=1" in path:
                return "passed", {"total_count": 101, "check_runs": first_page}, ""
            if "/check-runs?" in path and "&page=2" in path:
                return "passed", {"total_count": 101, "check_runs": second_page}, ""
            if "/git/ref/tags/" in path:
                return "passed", {"object": {"type": "commit", "sha": COMMIT}}, ""
            if "/releases/tags/" in path:
                return "passed", {"tag_name": "v0.7.0-beta.1", "draft": False, "prerelease": True, "html_url": "https://github.test/release"}, ""
            raise AssertionError(path)

        with patch.object(runner, "_gh_api", side_effect=fake_api):
            passed = runner.probe_release_evidence(source_commit=COMMIT, repository="owner/repo", tag="v0.7.0-beta.1", required_check_names=REQUIRED_CHECKS)
        self.assertEqual(passed[0], "passed")
        self.assertEqual(passed[1]["required_check_names"], REQUIRED_CHECKS)
        self.assertTrue(passed[1]["assertions"]["check_run_collection_complete"])
        with patch.object(runner, "_gh_api", return_value=("blocked", None, "github_api_unavailable")):
            blocked = runner.probe_release_evidence(source_commit=COMMIT, repository="owner/repo", tag="v0.7.0-beta.1", required_check_names=REQUIRED_CHECKS)
        self.assertEqual(blocked[0], "blocked")

        def wrong_sha_api(path: str):
            status, value, reason = fake_api(path)
            if "/check-runs?" in path and "&page=2" in path:
                value = {"total_count": 101, "check_runs": [{**second_page[0], "head_sha": "e" * 40}]}
            return status, value, reason

        with patch.object(runner, "_gh_api", side_effect=wrong_sha_api):
            wrong_sha = runner.probe_release_evidence(source_commit=COMMIT, repository="owner/repo", tag="v0.7.0-beta.1", required_check_names=REQUIRED_CHECKS)
        self.assertEqual(wrong_sha[0], "failed")
        self.assertFalse(wrong_sha[1]["assertions"]["required_checks_successful_on_source"])

    def test_release_gate_fails_closed_on_incomplete_check_run_pages(self) -> None:
        page = [
            {"id": index, "name": f"check-{index}", "status": "completed", "conclusion": "success", "head_sha": COMMIT}
            for index in range(1, 101)
        ]

        def fake_api(path: str):
            if path.endswith(f"commits/{COMMIT}"):
                return "passed", {"sha": COMMIT}, ""
            if path.endswith("/pulls"):
                return "passed", [], ""
            if "/check-runs?" in path and "&page=1" in path:
                return "passed", {"total_count": 101, "check_runs": page}, ""
            if "/check-runs?" in path and "&page=2" in path:
                return "passed", {"total_count": 101, "check_runs": []}, ""
            if "/git/ref/tags/" in path:
                return "passed", {"object": {"type": "commit", "sha": COMMIT}}, ""
            if "/releases/tags/" in path:
                return "passed", {"tag_name": "v0.7.0-beta.1", "draft": False, "prerelease": True}, ""
            raise AssertionError(path)

        with patch.object(runner, "_gh_api", side_effect=fake_api):
            result = runner.probe_release_evidence(source_commit=COMMIT, repository="owner/repo", tag="v0.7.0-beta.1", required_check_names=REQUIRED_CHECKS)
        self.assertEqual(result[0], "failed")
        self.assertIn("checks:github_check_runs_incomplete", result[2])


if __name__ == "__main__":
    unittest.main()
