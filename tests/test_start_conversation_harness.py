from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPOSITORY_ROOT / "scripts" / "start_conversation_harness.sh"
DSH_RUNTIME_ROOT = REPOSITORY_ROOT / "acceptance" / "dsh-runtime"
FAKE_SOURCE_REVISION = "a" * 40
EXPECTED_DSH_VERSION = "0.1.0-rc.6"


class ConversationHarnessStartupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "checkout"
        self.bin_dir = Path(self.temporary.name) / "bin"
        self.home_dir = Path(self.temporary.name) / "home"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / ".venv" / "bin").mkdir(parents=True)
        (self.root / "integrations" / "deepseek-harness").mkdir(parents=True)
        (self.root / "acceptance" / "dsh-runtime" / "node_modules" / ".bin").mkdir(
            parents=True
        )
        self.bin_dir.mkdir()
        self.home_dir.mkdir()
        self.dsh_home_log = Path(self.temporary.name) / "dsh-home.log"
        self.dsh_credentials_log = Path(self.temporary.name) / "dsh-credentials.log"
        self.dsh_artifact_export_log = Path(self.temporary.name) / "dsh-artifact-export.log"
        shutil.copy2(START_SCRIPT, self.root / "scripts" / START_SCRIPT.name)
        (self.root / ".venv" / "bin" / "python").symlink_to(sys.executable)
        self._write_executable(
            self.root / "scripts" / "install_dsh_preset.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        self._write_executable(
            self.bin_dir / "dsh", self._fake_dsh("FAKE_SYSTEM_DSH_VERSION")
        )
        self._write_executable(
            self.root
            / "acceptance"
            / "dsh-runtime"
            / "node_modules"
            / ".bin"
            / "dsh",
            self._fake_dsh("FAKE_LOCKED_DSH_VERSION"),
        )
        self._write_executable(
            self.bin_dir / "git",
            f"""#!/usr/bin/env bash
set -eu
case " $* " in
  *" rev-parse "*)
    printf '%s\\n' '{FAKE_SOURCE_REVISION}'
    ;;
  *" status "*)
    if [[ "${{FAKE_SOURCE_DIRTY:-0}}" == "1" ]]; then
      printf '%s\\n' ' M model_harness/server.py'
    fi
    ;;
  *)
    exit 1
    ;;
esac
"""
        )
        self._write_executable(
            self.bin_dir / "curl",
            """#!/usr/bin/env bash
set -eu
url=""
for argument in "$@"; do
  case "$argument" in
    http://*|https://*) url="$argument" ;;
  esac
done
case "$url" in
  */health)
    count=0
    if [[ -f "$FAKE_HEALTH_COUNTER" ]]; then
      count="$(wc -l < "$FAKE_HEALTH_COUNTER" | tr -d ' ')"
    fi
    printf 'x\n' >> "$FAKE_HEALTH_COUNTER"
    if [[ "$count" -lt "${FAKE_HEALTH_SUCCESSES:-1}" ]]; then
      printf '%s\n' '{"ok":true}'
      exit 0
    fi
    exit 22
    ;;
  */runtime)
    printf '%s\n' "$FAKE_RUNTIME_JSON"
    ;;
  */api/session.list)
    if [[ "${FAKE_AGENT_PROBE_OK:-1}" != "1" ]]; then
      exit 22
    fi
    printf '%s\n' '{"type":"server-response","ok":true}'
    ;;
  *)
    exit 22
    ;;
esac
""",
        )

    def _fake_dsh(self, version_environment: str) -> str:
        return f"""#!/usr/bin/env bash
set -eu
if [[ -n "${{FAKE_DSH_HOME_LOG:-}}" ]]; then
  printf '%s\\n' "${{DSH_HOME:-<unset>}}" >> "$FAKE_DSH_HOME_LOG"
fi
if [[ -n "${{FAKE_DSH_CREDENTIALS_LOG:-}}" ]]; then
  printf '%s\\n' "${{MODEL_HARNESS_DSH_CREDENTIALS_FILE:-<unset>}}" >> "$FAKE_DSH_CREDENTIALS_LOG"
fi
if [[ -n "${{FAKE_DSH_ARTIFACT_EXPORT_LOG:-}}" ]]; then
  printf '%s\\n' "${{MODEL_HARNESS_ARTIFACT_EXPORT_DIR:-<unset>}}" >> "$FAKE_DSH_ARTIFACT_EXPORT_LOG"
fi
case " $* " in
  *" --version "*)
    printf '%s\\n' "${{{version_environment}:-{EXPECTED_DSH_VERSION}}}"
    ;;
  *" --dump-config "*)
    if [[ "${{FAKE_CONFIG_HANG:-0}}" == "1" ]]; then
      printf '%s\\n' 'secret-partial-provider-config'
      sleep 20
    fi
    printf '%s\n' 'plugins: [specialist-model-studio-dsh-plugin]'
    ;;
  *" plugin "*)
    ;;
  *" web "*)
    exit 0
    ;;
esac
"""

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _runtime(self, **agent_overrides: object) -> dict[str, object]:
        agent: dict[str, object] = {
            "available": True,
            "transport_ready": True,
            "ready": True,
            "real_agent": True,
            "implementation": "dsh_native_subagents",
            "conversation_schema_version": "2.0",
            "conversation_projector_revision": "3.3",
            "synthesis_verdict_version": "1.0",
            "conversation_action_schema_version": "1.0",
            "task_truth_source": "TrainingTask",
            "provider": {
                "provider": "deepseek-official",
                "active": True,
                "configured": True,
                "ready": True,
                "source": "env",
                "reason": None,
            },
        }
        agent.update(agent_overrides)
        return {
            "primary_experience": "conversation",
            "runtime_identity": {
                "source_root": str(self.root.resolve()),
                "source_revision": FAKE_SOURCE_REVISION,
                "source_dirty": False,
                "runs_dir": str((self.root / "runs").resolve()),
                "workspace_dir": str((self.root / "runs" / "_workspace").resolve()),
                "conversation_origin": "http://127.0.0.1:3080",
            },
            "agent": agent,
        }

    def _run(
        self,
        runtime: dict[str, object],
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}:{environment['PATH']}",
                "HOME": str(self.home_dir),
                "FAKE_HEALTH_COUNTER": str(
                    Path(self.temporary.name) / "health-counter"
                ),
                # Startup probes an existing backend once before and once after
                # the strict /runtime identity check. The third probe is the
                # reuse wait loop and deliberately ends this fixture process.
                "FAKE_HEALTH_SUCCESSES": "2",
                "FAKE_RUNTIME_JSON": json.dumps(runtime),
                "FAKE_DSH_HOME_LOG": str(self.dsh_home_log),
                "FAKE_DSH_CREDENTIALS_LOG": str(self.dsh_credentials_log),
                "FAKE_DSH_ARTIFACT_EXPORT_LOG": str(self.dsh_artifact_export_log),
                "MODEL_HARNESS_AGENT_BRIDGE_TOKEN": "startup-test-bridge-token",
            }
        )
        environment.update(extra_environment or {})
        return subprocess.run(
            ["bash", str(self.root / "scripts" / START_SCRIPT.name)],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def test_reuses_only_compatible_real_multi_agent_backend(self) -> None:
        completed = self._run(self._runtime())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Reusing the existing DSH runtime.", completed.stdout)

    def test_configuration_preflight_timeout_is_bounded_and_redacts_partial_output(self) -> None:
        completed = self._run(self._runtime(), {
            "MODEL_HARNESS_PREFLIGHT_TIMEOUT_SECONDS": "3", "FAKE_CONFIG_HANG": "1",
        })
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("configuration preflight timed out", completed.stderr)
        self.assertNotIn("secret-partial-provider-config", completed.stdout + completed.stderr)
        self.assertNotIn("Specialist Model Studio:", completed.stdout)

    def test_preflight_timeout_must_be_positive(self) -> None:
        completed = self._run(self._runtime(), {"MODEL_HARNESS_PREFLIGHT_TIMEOUT_SECONDS": "0"})
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must be a positive integer", completed.stderr)

    def test_repository_locks_the_exact_dsh_cli_release(self) -> None:
        package = json.loads(
            (DSH_RUNTIME_ROOT / "package.json").read_text(encoding="utf-8")
        )
        lock = json.loads(
            (DSH_RUNTIME_ROOT / "package-lock.json").read_text(encoding="utf-8")
        )

        self.assertEqual(package["dependencies"]["@deepseek-ai/dsh"], EXPECTED_DSH_VERSION)
        self.assertEqual(
            lock["packages"][""]["dependencies"]["@deepseek-ai/dsh"],
            EXPECTED_DSH_VERSION,
        )
        locked_package = lock["packages"]["node_modules/@deepseek-ai/dsh"]
        self.assertEqual(locked_package["version"], EXPECTED_DSH_VERSION)
        self.assertTrue(locked_package["integrity"].startswith("sha512-"))

    def test_prefers_repository_locked_dsh_over_path(self) -> None:
        completed = self._run(
            self._runtime(),
            {"FAKE_SYSTEM_DSH_VERSION": "9.9.9"},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_an_invalid_backend_start_attempt_budget(self) -> None:
        completed = self._run(
            self._runtime(),
            {"MODEL_HARNESS_BACKEND_START_ATTEMPTS": "not-a-number"},
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "MODEL_HARNESS_BACKEND_START_ATTEMPTS must be a positive integer",
            completed.stderr,
        )

    def test_rejects_a_wrong_locked_dsh_version(self) -> None:
        completed = self._run(
            self._runtime(),
            {"FAKE_LOCKED_DSH_VERSION": "0.1.0-rc.7"},
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected 0.1.0-rc.6, observed 0.1.0-rc.7", completed.stderr)

    def test_system_dsh_is_an_explicit_development_only_fallback(self) -> None:
        locked_bin = (
            self.root
            / "acceptance"
            / "dsh-runtime"
            / "node_modules"
            / ".bin"
            / "dsh"
        )
        locked_bin.unlink()

        refused = self._run(self._runtime())
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Missing the repository-locked", refused.stderr)

        counter = Path(self.temporary.name) / "health-counter"
        counter.unlink(missing_ok=True)
        allowed = self._run(
            self._runtime(),
            {"MODEL_HARNESS_ALLOW_SYSTEM_DSH": "1"},
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn("Development fallback", allowed.stdout)

    def test_public_and_l6_starts_refuse_the_system_dsh_fallback(self) -> None:
        locked_bin = (
            self.root
            / "acceptance"
            / "dsh-runtime"
            / "node_modules"
            / ".bin"
            / "dsh"
        )
        locked_bin.unlink()

        for mode in (
            {"SPECIALIST_MODEL_STUDIO_PUBLIC_START": "1"},
            {"SPECIALIST_MODEL_STUDIO_L6_ACCEPTANCE": "1"},
        ):
            with self.subTest(mode=mode):
                counter = Path(self.temporary.name) / "health-counter"
                counter.unlink(missing_ok=True)
                completed = self._run(
                    self._runtime(),
                    {"MODEL_HARNESS_ALLOW_SYSTEM_DSH": "1", **mode},
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("refuse an unlocked system DSH CLI", completed.stderr)

    def test_reused_backend_requires_the_preconfigured_bridge_token(self) -> None:
        completed = self._run(
            self._runtime(),
            {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": ""},
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "without the same MODEL_HARNESS_AGENT_BRIDGE_TOKEN",
            completed.stderr,
        )

    def test_rejects_health_only_backend_without_real_agent(self) -> None:
        completed = self._run(self._runtime(available=False, real_agent=False))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Refusing to reuse the running backend", completed.stderr)
        self.assertIn("agent.available expected True, observed False", completed.stderr)

    def test_rejects_wrong_implementation_and_projector(self) -> None:
        cases = (
            (
                {"implementation": "local_scripted_flow"},
                "agent.implementation expected 'dsh_native_subagents'",
            ),
            (
                {"conversation_projector_revision": "1.0"},
                "agent.conversation_projector_revision is incompatible",
            ),
            (
                {"synthesis_verdict_version": "0.0"},
                "agent.synthesis_verdict_version expected '1.0'",
            ),
            (
                {"conversation_action_schema_version": "0.0"},
                "agent.conversation_action_schema_version expected '1.0'",
            ),
        )
        for overrides, expected_error in cases:
            with self.subTest(overrides=overrides):
                counter = Path(self.temporary.name) / "health-counter"
                counter.unlink(missing_ok=True)
                completed = self._run(self._runtime(**overrides))
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected_error, completed.stderr)

    def test_rejects_explicit_identity_from_another_checkout(self) -> None:
        runtime = self._runtime()
        runtime["runtime_identity"] = {
            "runs_dir": "/tmp/another-checkout/runs",
            "source_root": "/tmp/another-checkout",
            "workspace_dir": "/tmp/another-checkout/runs/_workspace",
            "conversation_origin": "http://127.0.0.1:3080",
        }

        completed = self._run(runtime)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not identify this startup target", completed.stderr)

    def test_rejects_missing_runtime_identity_and_wrong_dsh_origin(self) -> None:
        missing_identity = self._runtime()
        missing_identity.pop("runtime_identity")
        missing = self._run(missing_identity)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("/runtime.runtime_identity must be a JSON object", missing.stderr)

        counter = Path(self.temporary.name) / "health-counter"
        counter.unlink(missing_ok=True)
        wrong_origin = self._runtime()
        identity = wrong_origin["runtime_identity"]
        assert isinstance(identity, dict)
        identity["conversation_origin"] = "http://127.0.0.1:3999"
        mismatched = self._run(wrong_origin)
        self.assertNotEqual(mismatched.returncode, 0)
        self.assertIn(
            "runtime_identity.conversation_origin does not identify the configured DSH endpoint",
            mismatched.stderr,
        )

    def test_rejects_runtime_without_the_exact_source_revision(self) -> None:
        missing_revision = self._runtime()
        identity = missing_revision["runtime_identity"]
        assert isinstance(identity, dict)
        identity.pop("source_revision")

        missing = self._run(missing_revision)

        self.assertNotEqual(missing.returncode, 0)
        self.assertIn(
            "runtime_identity.source_revision does not identify this checkout",
            missing.stderr,
        )

        counter = Path(self.temporary.name) / "health-counter"
        counter.unlink(missing_ok=True)
        wrong_revision = self._runtime()
        wrong_identity = wrong_revision["runtime_identity"]
        assert isinstance(wrong_identity, dict)
        wrong_identity["source_revision"] = "b" * 40

        wrong = self._run(wrong_revision)

        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("observed 'bbbb", wrong.stderr)

    def test_rejects_runtime_with_the_wrong_source_dirty_state(self) -> None:
        runtime = self._runtime()
        identity = runtime["runtime_identity"]
        assert isinstance(identity, dict)
        identity["source_dirty"] = True

        mismatched = self._run(runtime)

        self.assertNotEqual(mismatched.returncode, 0)
        self.assertIn(
            "runtime_identity.source_dirty does not identify this checkout",
            mismatched.stderr,
        )

        counter = Path(self.temporary.name) / "health-counter"
        counter.unlink(missing_ok=True)
        matched = self._run(runtime, {"FAKE_SOURCE_DIRTY": "1"})
        self.assertEqual(matched.returncode, 0, matched.stderr)

    def test_configured_runs_dir_is_part_of_reuse_identity(self) -> None:
        configured_runs = Path(self.temporary.name) / "selected-runs"
        runtime = self._runtime()
        identity = runtime["runtime_identity"]
        assert isinstance(identity, dict)
        identity["runs_dir"] = str(configured_runs.resolve())
        identity["workspace_dir"] = str((configured_runs / "_workspace").resolve())

        completed = self._run(
            runtime,
            {"MODEL_HARNESS_RUNS_DIR": str(configured_runs)},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(configured_runs.is_dir())
        observed_homes = self.dsh_home_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(observed_homes)
        self.assertEqual(set(observed_homes), {str((configured_runs / ".dsh").resolve())})
        observed_exports = self.dsh_artifact_export_log.read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertTrue(observed_exports)
        self.assertEqual(
            set(observed_exports),
            {str((configured_runs / "_workspace" / "exports").resolve())},
        )

    def test_launcher_routes_default_artifact_exports_to_runtime_workspace(self) -> None:
        script = (self.root / "scripts" / START_SCRIPT.name).read_text(encoding="utf-8")

        self.assertIn(
            'MODEL_HARNESS_ARTIFACT_EXPORT_DIR:-${WORKSPACE_DIR}/exports',
            script,
        )
        self.assertIn('export MODEL_HARNESS_ARTIFACT_EXPORT_DIR', script)

    def test_isolated_runtime_reuses_standard_user_credentials_store(self) -> None:
        credentials_file = self.home_dir / ".dsh" / ".credentials.yaml"
        credentials_file.parent.mkdir(parents=True)
        credentials_file.write_text("FAKE_PROVIDER_KEY: fixture-value\n", encoding="utf-8")
        credentials_file.chmod(0o600)

        completed = self._run(self._runtime())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = self.dsh_credentials_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(observed)
        self.assertEqual(set(observed), {str(credentials_file.resolve())})
        observed_homes = self.dsh_home_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(observed_homes)
        self.assertEqual(
            set(observed_homes),
            {str((self.root / "runs" / ".dsh").resolve())},
        )
        combined_output = completed.stdout + completed.stderr
        self.assertNotIn(str(credentials_file.resolve()), combined_output)
        self.assertNotIn("fixture-value", combined_output)

    def test_explicit_credentials_store_overrides_standard_user_store(self) -> None:
        standard_file = self.home_dir / ".dsh" / ".credentials.yaml"
        standard_file.parent.mkdir(parents=True)
        standard_file.write_text("FAKE_PROVIDER_KEY: standard-value\n", encoding="utf-8")
        standard_file.chmod(0o600)
        explicit_file = Path(self.temporary.name) / "operator-selected.yaml"
        explicit_file.write_text("FAKE_PROVIDER_KEY: explicit-value\n", encoding="utf-8")
        explicit_file.chmod(0o600)

        completed = self._run(
            self._runtime(),
            {"MODEL_HARNESS_DSH_CREDENTIALS_FILE": str(explicit_file)},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = self.dsh_credentials_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(observed)
        self.assertEqual(set(observed), {str(explicit_file.resolve())})
        combined_output = completed.stdout + completed.stderr
        self.assertNotIn(str(explicit_file.resolve()), combined_output)
        self.assertNotIn("explicit-value", combined_output)

    def test_missing_shared_store_keeps_credentials_inside_isolated_dsh_home(self) -> None:
        completed = self._run(self._runtime())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        expected = (self.root / "runs" / ".dsh" / ".credentials.yaml").resolve()
        observed = self.dsh_credentials_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(observed)
        self.assertEqual(set(observed), {str(expected)})
        self.assertNotIn(str(expected), completed.stdout + completed.stderr)

    def test_reused_backend_with_inconsistent_dsh_probe_fails_closed(self) -> None:
        completed = self._run(
            self._runtime(),
            {"FAKE_AGENT_PROBE_OK": "0"},
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "Refusing to start another DSH process: the reused backend reported a real Agent",
            completed.stderr,
        )

    def test_script_uses_only_tracked_process_ids_for_cleanup(self) -> None:
        source = START_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("pkill", source)
        self.assertNotIn("killall", source)
        self.assertNotIn('echo "${DSH_CONFIG}"', source)
        self.assertIn('kill "${AGENT_PID}"', source)
        self.assertIn('kill "${BACKEND_PID}"', source)

    def test_public_start_exposes_only_the_product_app_url(self) -> None:
        completed = self._run(
            self._runtime(),
            {"SPECIALIST_MODEL_STUDIO_PUBLIC_START": "1"},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "http://127.0.0.1:8765/app")
        self.assertNotIn("DSH runtime", completed.stdout)

    def test_public_and_l6_starts_require_a_ready_model_provider(self) -> None:
        unavailable = self._runtime(
            ready=False,
            provider={
                "provider": "deepseek-official",
                "active": True,
                "configured": False,
                "ready": False,
                "source": None,
                "reason": "llm_credential_missing",
            },
        )
        for mode in (
            {"SPECIALIST_MODEL_STUDIO_PUBLIC_START": "1"},
            {"SPECIALIST_MODEL_STUDIO_L6_ACCEPTANCE": "1"},
        ):
            with self.subTest(mode=mode):
                counter = Path(self.temporary.name) / "health-counter"
                counter.unlink(missing_ok=True)
                completed = self._run(unavailable, mode)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("agent.ready expected True, observed False", completed.stderr)

    def test_development_start_allows_transport_with_provider_setup_pending(self) -> None:
        completed = self._run(
            self._runtime(
                ready=False,
                provider={
                    "provider": "deepseek-official",
                    "active": True,
                    "configured": False,
                    "ready": False,
                    "source": None,
                    "reason": "llm_credential_missing",
                },
            )
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Reusing the existing DSH runtime.", completed.stdout)


if __name__ == "__main__":
    unittest.main()
