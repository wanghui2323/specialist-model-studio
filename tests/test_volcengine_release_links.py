from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "deploy" / "volcengine" / "remote-deploy.sh"
ROLLBACK_SCRIPT = ROOT / "deploy" / "volcengine" / "remote-rollback.sh"
SERVICE_FILE = ROOT / "deploy" / "volcengine" / "specialist-model-studio.service"
READINESS_SCRIPT = ROOT / "deploy" / "volcengine" / "readiness.sh"


class VolcengineReleaseLinkTests(unittest.TestCase):
    def _run_sourced(self, script_path: Path, commands: str) -> None:
        with tempfile.TemporaryDirectory(prefix="sms-release-links-") as temporary:
            environment = dict(os.environ)
            environment["SMS_TEST_ROOT"] = temporary
            environment["SCRIPT_UNDER_TEST"] = str(script_path)
            shell = textwrap.dedent(
                f"""
                set -euo pipefail
                set --
                source "${{SCRIPT_UNDER_TEST}}"

                SMS_TEST_ROOT="$(readlink -f "${{SMS_TEST_ROOT}}")"
                RELEASES_DIR="${{SMS_TEST_ROOT}}/releases"
                LEGACY_RELEASES_DIR="${{SMS_TEST_ROOT}}/legacy-releases"
                CURRENT_LINK="${{SMS_TEST_ROOT}}/current"
                PREVIOUS_LINK="${{SMS_TEST_ROOT}}/previous"
                SERVICE_FILE="${{SMS_TEST_ROOT}}/specialist-model-studio.service"
                LIBEXEC_DIR="${{SMS_TEST_ROOT}}/libexec"
                NGINX_FILE="${{SMS_TEST_ROOT}}/specialist-model-studio.conf"
                CONFIG_BACKUP_DIR="${{SMS_TEST_ROOT}}/configuration.previous"
                PYTHON_BIN="$(command -v python3)"
                mkdir -p \
                  "${{RELEASES_DIR}}" \
                  "${{LEGACY_RELEASES_DIR}}" \
                  "${{LIBEXEC_DIR}}" \
                  "${{CONFIG_BACKUP_DIR}}"

                write_test_manifest() {{
                  local release_dir="$1"
                  local revision="${{2:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}}"
                  local build_complete="${{3:-true}}"
                  "${{PYTHON_BIN}}" - "$release_dir" "$revision" "$build_complete" <<'PY'
import json
import sys
from pathlib import Path

release_dir = Path(sys.argv[1])
payload = {{
    "schema_version": 1,
    "revision": sys.argv[2],
    "release_id": release_dir.name,
    "build_complete": sys.argv[3] == "true",
}}
manifest = release_dir / ".git/specialist-model-studio-release.json"
manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_text(
    json.dumps(payload), encoding="utf-8"
)
PY
                }}

                # The production host is GNU/Linux and supports `mv -T`. The
                # test runner may be macOS, so emulate only that atomic replace
                # operation while exercising the real shell helpers.
                mv() {{
                  if [[ "${{1:-}}" == "-Tf" && "$#" -eq 3 ]]; then
                    command rm -f "$3"
                    command mv "$2" "$3"
                    return
                  fi
                  command mv "$@"
                }}

                {textwrap.dedent(commands)}
                """
            )
            completed = subprocess.run(
                ["bash", "-c", shell],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )

    def test_scripts_accept_only_direct_children_of_approved_release_roots(self) -> None:
        commands = r"""
            mkdir -p \
              "${RELEASES_DIR}/20260902T010101Z-aaaaaaa" \
              "${LEGACY_RELEASES_DIR}/legacy-release" \
              "${RELEASES_DIR}/nested/not-a-release" \
              "${SMS_TEST_ROOT}/outside"
            ln -s "${SMS_TEST_ROOT}/outside" "${RELEASES_DIR}/escape"
            write_test_manifest "${RELEASES_DIR}/20260902T010101Z-aaaaaaa"

            is_retained_release "${RELEASES_DIR}/20260902T010101Z-aaaaaaa"
            is_retained_release "${LEGACY_RELEASES_DIR}/legacy-release"
            ! is_retained_release "${RELEASES_DIR}/nested/not-a-release"
            ! is_retained_release "${SMS_TEST_ROOT}/outside"
            ! is_retained_release "${RELEASES_DIR}/escape"
        """
        for script_path in (DEPLOY_SCRIPT, ROLLBACK_SCRIPT):
            with self.subTest(script=script_path.name):
                self._run_sourced(script_path, commands)

    def test_scripts_reject_an_unsafe_current_before_switching(self) -> None:
        commands = r"""
            mkdir -p "${SMS_TEST_ROOT}/outside"
            ln -s "${SMS_TEST_ROOT}/outside" "${CURRENT_LINK}"
            ! resolve_safe_release_link "${CURRENT_LINK}"
            [[ "$(readlink -f "${CURRENT_LINK}")" == "${SMS_TEST_ROOT}/outside" ]]
        """
        for script_path in (DEPLOY_SCRIPT, ROLLBACK_SCRIPT):
            with self.subTest(script=script_path.name):
                self._run_sourced(script_path, commands)

    def test_failed_deploy_restores_legacy_current_without_polluting_previous(self) -> None:
        self._run_sourced(
            DEPLOY_SCRIPT,
            r"""
            mkdir -p \
              "${LEGACY_RELEASES_DIR}/active-legacy" \
              "${LEGACY_RELEASES_DIR}/older-legacy" \
              "${RELEASES_DIR}/20260902T020202Z-bbbbbbb"
            ln -s "${LEGACY_RELEASES_DIR}/active-legacy" "${CURRENT_LINK}"
            ln -s "${LEGACY_RELEASES_DIR}/older-legacy" "${PREVIOUS_LINK}"
            write_test_manifest "${RELEASES_DIR}/20260902T020202Z-bbbbbbb" \
              bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb

            old_target="$(resolve_safe_release_link "${CURRENT_LINK}")"
            previous_target="$(resolve_safe_release_link "${PREVIOUS_LINK}")"
            atomic_replace_release_link "${RELEASES_DIR}/20260902T020202Z-bbbbbbb" "${CURRENT_LINK}" "next"
            restore_current_after_failed_deploy \
              "${old_target}" true "${RELEASES_DIR}/20260902T020202Z-bbbbbbb"

            [[ "$(readlink -f "${CURRENT_LINK}")" == "${old_target}" ]]
            [[ "$(readlink -f "${PREVIOUS_LINK}")" == "${previous_target}" ]]
        """,
        )

    def test_failed_first_deploy_removes_the_new_current_link(self) -> None:
        self._run_sourced(
            DEPLOY_SCRIPT,
            r"""
            mkdir -p "${RELEASES_DIR}/20260902T030303Z-ccccccc"
            write_test_manifest "${RELEASES_DIR}/20260902T030303Z-ccccccc" \
              cccccccccccccccccccccccccccccccccccccccc
            atomic_replace_release_link "${RELEASES_DIR}/20260902T030303Z-ccccccc" "${CURRENT_LINK}" "next"
            restore_current_after_failed_deploy "" false "${RELEASES_DIR}/20260902T030303Z-ccccccc"
            [[ ! -e "${CURRENT_LINK}" && ! -L "${CURRENT_LINK}" ]]
        """,
        )

    def test_legacy_previous_can_become_current_and_preserves_rollback_history(self) -> None:
        self._run_sourced(
            ROLLBACK_SCRIPT,
            r"""
            mkdir -p \
              "${RELEASES_DIR}/20260902T040404Z-ddddddd" \
              "${LEGACY_RELEASES_DIR}/previous-legacy"
            write_test_manifest "${RELEASES_DIR}/20260902T040404Z-ddddddd" \
              dddddddddddddddddddddddddddddddddddddddd
            ln -s "${RELEASES_DIR}/20260902T040404Z-ddddddd" "${CURRENT_LINK}"
            ln -s "${LEGACY_RELEASES_DIR}/previous-legacy" "${PREVIOUS_LINK}"

            old_target="$(resolve_safe_release_link "${CURRENT_LINK}")"
            target="$(resolve_safe_release_link "${PREVIOUS_LINK}")"
            atomic_replace_release_link "${target}" "${CURRENT_LINK}" "rollback"
            atomic_replace_release_link "${old_target}" "${PREVIOUS_LINK}" "next"

            [[ "$(readlink -f "${CURRENT_LINK}")" == "${target}" ]]
            [[ "$(readlink -f "${PREVIOUS_LINK}")" == "${old_target}" ]]
        """,
        )

    def test_new_release_requires_a_complete_matching_manifest(self) -> None:
        commands = r"""
            mkdir -p \
              "${RELEASES_DIR}/20260902T050505Z-eeeeeee" \
              "${RELEASES_DIR}/20260902T060606Z-fffffff" \
              "${RELEASES_DIR}/20260902T070707Z-1111111"
            write_test_manifest "${RELEASES_DIR}/20260902T060606Z-fffffff" \
              ffffffffffffffffffffffffffffffffffffffff false
            write_test_manifest "${RELEASES_DIR}/20260902T070707Z-1111111" \
              1111111111111111111111111111111111111111

            ! is_retained_release "${RELEASES_DIR}/20260902T050505Z-eeeeeee"
            ! is_retained_release "${RELEASES_DIR}/20260902T060606Z-fffffff"
            is_retained_release "${RELEASES_DIR}/20260902T070707Z-1111111"
            [[ "$(release_manifest_revision "${RELEASES_DIR}/20260902T070707Z-1111111")" == \
              1111111111111111111111111111111111111111 ]]
        """
        for script_path in (DEPLOY_SCRIPT, ROLLBACK_SCRIPT):
            with self.subTest(script=script_path.name):
                self._run_sourced(script_path, commands)

    def test_readiness_fails_closed_for_manifest_revision_mismatch(self) -> None:
        source = READINESS_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('STRICT_REVISION="true"', source)
        self.assertIn('identity.get("source_revision") != expected_revision', source)
        self.assertIn('identity.get("source_dirty") is not False', source)
        self.assertIn("the active release has no valid completion manifest", source)
        self.assertNotIn("if expected_revision and", source)
        self.assertIn("SMS_ALLOW_LEGACY_RELEASE", source)

    def test_deploy_records_previous_only_after_new_release_readiness(self) -> None:
        source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        activation_start = source.index("activate_new_release()")
        activation_end = source.index("\n}\n", activation_start)
        activation = source[activation_start:activation_end]
        readiness_position = activation.index("run_readiness_for_release")
        previous_update_position = activation.index(
            'atomic_replace_release_link "${OLD_TARGET}" "${PREVIOUS_LINK}" "next"'
        )

        self.assertGreater(previous_update_position, readiness_position)
        self.assertIn("systemctl reload nginx", activation)

    def test_managed_configuration_round_trips_before_old_service_restart(self) -> None:
        self._run_sourced(
            DEPLOY_SCRIPT,
            r"""
            printf old-service >"${SERVICE_FILE}"
            printf old-readiness >"${LIBEXEC_DIR}/readiness.sh"
            printf old-nginx >"${NGINX_FILE}"
            chmod 0640 "${SERVICE_FILE}" "${NGINX_FILE}"
            chmod 0750 "${LIBEXEC_DIR}/readiness.sh"

            HAD_SERVICE_FILE=true
            HAD_READINESS_FILE=true
            HAD_NGINX_FILE=true
            backup_managed_file "${SERVICE_FILE}" "${CONFIG_BACKUP_DIR}/service"
            backup_managed_file "${LIBEXEC_DIR}/readiness.sh" "${CONFIG_BACKUP_DIR}/readiness"
            backup_managed_file "${NGINX_FILE}" "${CONFIG_BACKUP_DIR}/nginx"

            printf new-service >"${SERVICE_FILE}"
            printf new-readiness >"${LIBEXEC_DIR}/readiness.sh"
            printf new-nginx >"${NGINX_FILE}"
            systemctl() { printf '%s\n' "$*" >>"${SMS_TEST_ROOT}/events"; }
            nginx() { printf 'nginx %s\n' "$*" >>"${SMS_TEST_ROOT}/events"; }

            restore_installed_configuration
            [[ "$(cat "${SERVICE_FILE}")" == old-service ]]
            [[ "$(cat "${LIBEXEC_DIR}/readiness.sh")" == old-readiness ]]
            [[ "$(cat "${NGINX_FILE}")" == old-nginx ]]
            [[ "$("${PYTHON_BIN}" -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "${SERVICE_FILE}")" == 0o640 ]]
            [[ "$("${PYTHON_BIN}" -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "${LIBEXEC_DIR}/readiness.sh")" == 0o750 ]]
            [[ "$(cat "${SMS_TEST_ROOT}/events")" == $'daemon-reload\nnginx -t\nreload nginx' ]]
        """,
        )

    def test_failed_activation_restores_preexisting_previous_target(self) -> None:
        self._run_sourced(
            DEPLOY_SCRIPT,
            r"""
            mkdir -p \
              "${LEGACY_RELEASES_DIR}/current-legacy" \
              "${LEGACY_RELEASES_DIR}/previous-legacy"
            OLD_TARGET="${LEGACY_RELEASES_DIR}/current-legacy"
            OLD_PREVIOUS_TARGET="${LEGACY_RELEASES_DIR}/previous-legacy"
            HAD_PREVIOUS=true
            ln -s "${OLD_TARGET}" "${PREVIOUS_LINK}"

            restore_previous_after_failed_deploy
            [[ "$(readlink -f "${PREVIOUS_LINK}")" == "${OLD_PREVIOUS_TARGET}" ]]
        """,
        )

    def test_service_binds_the_cli_to_the_active_source_checkout(self) -> None:
        service = SERVICE_FILE.read_text(encoding="utf-8")

        self.assertIn(
            "Environment=SPECIALIST_MODEL_STUDIO_SOURCE_ROOT="
            "/opt/specialist-model-studio/current",
            service,
        )


if __name__ == "__main__":
    unittest.main()
