#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS="${1:-180}"
BACKEND_URL="http://127.0.0.1:3010"
SERVICE_NAME="specialist-model-studio.service"
CURRENT_LINK="/opt/specialist-model-studio/current"
RELEASES_DIR="/opt/specialist-model-studio/releases"
LEGACY_RELEASES_DIR="/opt/specialist-model-studio-releases"
APP_USER="specialist-model-studio"
PYTHON_BIN="/usr/bin/python3.12"
RELEASE_MANIFEST_NAME=".git/specialist-model-studio-release.json"
ALLOW_LEGACY_RELEASE="${SMS_ALLOW_LEGACY_RELEASE:-0}"

if ! [[ "${TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "readiness timeout must be a positive integer" >&2
  exit 2
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "readiness failed: ${PYTHON_BIN} is unavailable" >&2
  exit 1
fi
if ! [[ "${ALLOW_LEGACY_RELEASE}" =~ ^[01]$ ]]; then
  echo "readiness failed: SMS_ALLOW_LEGACY_RELEASE must be 0 or 1" >&2
  exit 2
fi

release_manifest_revision() {
  local release_dir="${1:-}"
  local manifest_path="${release_dir}/${RELEASE_MANIFEST_NAME}"

  [[ -f "${manifest_path}" && ! -L "${manifest_path}" ]] || return 1
  "${PYTHON_BIN}" - "${manifest_path}" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
try:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
revision = payload.get("revision")
release_id = payload.get("release_id")
if not (
    payload.get("schema_version") == 1
    and payload.get("build_complete") is True
    and isinstance(revision, str)
    and re.fullmatch(r"[0-9a-f]{40}", revision) is not None
    and isinstance(release_id, str)
    and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}", release_id) is not None
    and manifest_path.parent.parent.name == release_id
):
    raise SystemExit(1)
print(revision)
PY
}

CURRENT_TARGET="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
EXPECTED_REVISION=""
STRICT_REVISION="false"
RELEASE_KIND=""
case "${CURRENT_TARGET}" in
  "${RELEASES_DIR}/"*)
    remainder="${CURRENT_TARGET#"${RELEASES_DIR}/"}"
    if [[ -z "${remainder}" || "${remainder}" == */* ]]; then
      echo "readiness failed: current is not a direct release child" >&2
      exit 1
    fi
    EXPECTED_REVISION="$(release_manifest_revision "${CURRENT_TARGET}" 2>/dev/null || true)"
    if ! [[ "${EXPECTED_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
      echo "readiness failed: the active release has no valid completion manifest" >&2
      exit 1
    fi
    STRICT_REVISION="true"
    RELEASE_KIND="manifest"
    ;;
  "${LEGACY_RELEASES_DIR}/"*)
    remainder="${CURRENT_TARGET#"${LEGACY_RELEASES_DIR}/"}"
    if [[ -z "${remainder}" || "${remainder}" == */* ]]; then
      echo "readiness failed: current is not a direct legacy release child" >&2
      exit 1
    fi
    EXPECTED_REVISION="$(runuser -u "${APP_USER}" -- git -c "safe.directory=${CURRENT_TARGET}" -C "${CURRENT_TARGET}" rev-parse --verify HEAD 2>/dev/null || true)"
    if [[ "${EXPECTED_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
      STRICT_REVISION="true"
      RELEASE_KIND="legacy-git"
    elif [[ "${ALLOW_LEGACY_RELEASE}" == "1" ]]; then
      RELEASE_KIND="legacy-explicit-exception"
    else
      echo "readiness failed: legacy release revision is unavailable; explicit migration rollback is required" >&2
      exit 1
    fi
    ;;
  *)
    echo "readiness failed: current does not resolve to an approved release root" >&2
    exit 1
    ;;
esac

validate_runtime() {
  local payload="$1"
  "${PYTHON_BIN}" -c '
import json
import sys
from pathlib import Path

payload = json.load(sys.stdin)
agent = payload.get("agent")
if not isinstance(agent, dict):
    raise SystemExit(1)
expected = {
    "available": True,
    "real_agent": True,
    "implementation": "dsh_native_subagents",
    "transport_ready": True,
    "ready": True,
}
for key, value in expected.items():
    if agent.get(key) != value:
        raise SystemExit(1)
provider = agent.get("provider")
if not isinstance(provider, dict):
    raise SystemExit(1)
for key in ("active", "configured", "ready"):
    if provider.get(key) is not True:
        raise SystemExit(1)
if payload.get("primary_experience") != "conversation":
    raise SystemExit(1)
identity = payload.get("runtime_identity")
if not isinstance(identity, dict):
    raise SystemExit(1)
expected_revision = sys.argv[1]
expected_source_root = Path(sys.argv[2]).resolve()
strict_revision = sys.argv[3] == "true"
observed_source_root_raw = identity.get("source_root")
if not isinstance(observed_source_root_raw, str) or not observed_source_root_raw:
    raise SystemExit(1)
observed_source_root = Path(observed_source_root_raw).resolve()
if strict_revision:
    if observed_source_root != expected_source_root:
        raise SystemExit(1)
    if identity.get("source_revision") != expected_revision:
        raise SystemExit(1)
    if identity.get("source_dirty") is not False:
        raise SystemExit(1)
else:
    try:
        observed_source_root.relative_to(expected_source_root)
    except ValueError:
        raise SystemExit(1)
' "${EXPECTED_REVISION}" "${CURRENT_TARGET}" "${STRICT_REVISION}" <<<"${payload}" >/dev/null 2>&1
}

deadline=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  if systemctl is-active --quiet "${SERVICE_NAME}" \
      && curl --fail --silent --show-error --max-time 3 "${BACKEND_URL}/health" >/dev/null 2>&1; then
    runtime_payload="$(curl --fail --silent --show-error --max-time 5 "${BACKEND_URL}/runtime" 2>/dev/null || true)"
    if [[ -n "${runtime_payload}" ]] && validate_runtime "${runtime_payload}"; then
      echo "ready: service active, backend healthy, real Agent/provider ready, revision ${EXPECTED_REVISION:-legacy-explicit-exception}, release ${RELEASE_KIND}"
      exit 0
    fi
  fi
  sleep 2
done

echo "readiness failed after ${TIMEOUT_SECONDS}s; inspect the private systemd journal on the server" >&2
exit 1
