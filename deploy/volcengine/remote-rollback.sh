#!/usr/bin/env bash
set -euo pipefail

TARGET_RELEASE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="/opt/specialist-model-studio"
RELEASES_DIR="${APP_ROOT}/releases"
LEGACY_RELEASES_DIR="/opt/specialist-model-studio-releases"
CURRENT_LINK="${APP_ROOT}/current"
PREVIOUS_LINK="${APP_ROOT}/previous"
PYTHON_BIN="/usr/bin/python3.12"
RELEASE_MANIFEST_NAME=".git/specialist-model-studio-release.json"

release_manifest_revision() {
  local release_dir="${1:-}"
  local expected_revision="${2:-}"
  local expected_release_id="${3:-}"
  local manifest_path="${release_dir}/${RELEASE_MANIFEST_NAME}"

  [[ -f "${manifest_path}" && ! -L "${manifest_path}" ]] || return 1
  "${PYTHON_BIN}" - "${manifest_path}" "${expected_revision}" "${expected_release_id}" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
expected_revision = sys.argv[2]
expected_release_id = sys.argv[3]
try:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)

revision = payload.get("revision")
release_id = payload.get("release_id")
valid = (
    payload.get("schema_version") == 1
    and payload.get("build_complete") is True
    and isinstance(revision, str)
    and re.fullmatch(r"[0-9a-f]{40}", revision) is not None
    and isinstance(release_id, str)
    and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}", release_id) is not None
    and manifest_path.parent.parent.name == release_id
)
if expected_revision:
    valid = valid and revision == expected_revision
if expected_release_id:
    valid = valid and release_id == expected_release_id
if not valid:
    raise SystemExit(1)
print(revision)
PY
}

canonical_retained_release() {
  local candidate
  local release_root remainder

  candidate="$(readlink -f "${1:-}" 2>/dev/null || true)"
  [[ -n "${candidate}" && -d "${candidate}" ]] || return 1
  for release_root in "${RELEASES_DIR}" "${LEGACY_RELEASES_DIR}"; do
    case "${candidate}" in
      "${release_root}/"*)
        remainder="${candidate#"${release_root}/"}"
        if [[ -n "${remainder}" && "${remainder}" != */* ]]; then
          if [[ "${release_root}" == "${RELEASES_DIR}" ]]; then
            release_manifest_revision "${candidate}" >/dev/null || return 1
          fi
          printf '%s\n' "${candidate}"
          return 0
        fi
        ;;
    esac
  done
  return 1
}

is_retained_release() {
  canonical_retained_release "${1:-}" >/dev/null
}

resolve_safe_release_link() {
  local link_path="${1:-}"
  local target

  [[ -n "${link_path}" && ( -e "${link_path}" || -L "${link_path}" ) ]] || return 1
  target="$(canonical_retained_release "${link_path}")" || return 1
  printf '%s\n' "${target}"
}

atomic_replace_release_link() {
  local target
  local link_path="${2:-}"
  local suffix="${3:-next}"
  local staged_link observed_target

  target="$(canonical_retained_release "${1:-}")" || return 1
  [[ -n "${link_path}" && -n "${suffix}" ]] || return 1
  staged_link="${link_path}.${suffix}"
  ln -sfn "${target}" "${staged_link}" || return 1
  if ! mv -Tf "${staged_link}" "${link_path}"; then
    rm -f -- "${staged_link}"
    return 1
  fi
  observed_target="$(readlink -f "${link_path}" 2>/dev/null || true)"
  [[ "${observed_target}" == "${target}" ]]
}

restore_current_after_failed_rollback() {
  local old_target="${1:-}"
  local had_current="${2:-}"
  local failed_target="${3:-}"
  local observed_target

  failed_target="$(canonical_retained_release "${failed_target}")" || return 1
  observed_target="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
  [[ -n "${failed_target}" && "${observed_target}" == "${failed_target}" ]] || return 1

  if [[ "${had_current}" == "true" ]]; then
    atomic_replace_release_link "${old_target}" "${CURRENT_LINK}" "restore"
    return
  fi
  [[ "${had_current}" == "false" ]] || return 1
  rm -f -- "${CURRENT_LINK}" || return 1
  [[ ! -e "${CURRENT_LINK}" && ! -L "${CURRENT_LINK}" ]]
}

run_readiness_for_release() {
  local release_target
  local timeout_seconds="${2:-180}"
  local readiness_script="${3:-${SCRIPT_DIR}/readiness.sh}"

  release_target="$(canonical_retained_release "${1:-}")" || return 1
  case "${release_target}" in
    "${LEGACY_RELEASES_DIR}/"*)
      SMS_ALLOW_LEGACY_RELEASE=1 "${readiness_script}" "${timeout_seconds}"
      ;;
    *)
      "${readiness_script}" "${timeout_seconds}"
      ;;
  esac
}

# Allow shell-level tests to source the transaction helpers without executing a
# privileged rollback. Normal invocation still follows the full path below.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

if (( EUID != 0 )); then
  echo "remote-rollback.sh must run as root" >&2
  exit 1
fi

if [[ -n "${TARGET_RELEASE}" ]] && ! [[ "${TARGET_RELEASE}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}$ ]]; then
  echo "Invalid target release name." >&2
  exit 2
fi

HAD_CURRENT="false"
OLD_TARGET=""
if [[ -e "${CURRENT_LINK}" || -L "${CURRENT_LINK}" ]]; then
  HAD_CURRENT="true"
  if ! OLD_TARGET="$(resolve_safe_release_link "${CURRENT_LINK}")"; then
    echo "Refusing rollback: current does not resolve to a retained release in an approved root." >&2
    exit 1
  fi
fi
if [[ -n "${TARGET_RELEASE}" ]]; then
  TARGET="$(readlink -f "${RELEASES_DIR}/${TARGET_RELEASE}" 2>/dev/null || true)"
else
  TARGET="$(resolve_safe_release_link "${PREVIOUS_LINK}" 2>/dev/null || true)"
fi

if ! is_retained_release "${TARGET}" || [[ "${TARGET}" == "${OLD_TARGET}" ]]; then
  echo "No distinct retained release is available for rollback." >&2
  exit 1
fi

atomic_replace_release_link "${TARGET}" "${CURRENT_LINK}" "rollback"

if ! systemctl restart specialist-model-studio.service \
    || ! run_readiness_for_release "${TARGET}" 180; then
  echo "Rollback target failed readiness; restoring the release active before this attempt." >&2
  if ! restore_current_after_failed_rollback "${OLD_TARGET}" "${HAD_CURRENT}" "${TARGET}"; then
    echo "Failed to restore the current link safely; the service will remain stopped." >&2
    systemctl stop specialist-model-studio.service || true
    exit 1
  fi
  if [[ "${HAD_CURRENT}" == "true" ]]; then
    systemctl reset-failed specialist-model-studio.service || true
    systemctl restart specialist-model-studio.service || true
    run_readiness_for_release "${OLD_TARGET}" 120 || true
  else
    systemctl stop specialist-model-studio.service || true
  fi
  exit 1
fi

if [[ "${HAD_CURRENT}" == "true" ]]; then
  atomic_replace_release_link "${OLD_TARGET}" "${PREVIOUS_LINK}" "next"
fi

echo "rollback_ready target=$(basename "${TARGET}") url=https://studio.learnbuddy.top/app"
