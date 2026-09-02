#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS="${1:-180}"
BACKEND_URL="http://127.0.0.1:3010"
SERVICE_NAME="specialist-model-studio.service"
CURRENT_LINK="/opt/specialist-model-studio/current"
PYTHON_BIN="/usr/bin/python3.12"

if ! [[ "${TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "readiness timeout must be a positive integer" >&2
  exit 2
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "readiness failed: ${PYTHON_BIN} is unavailable" >&2
  exit 1
fi

EXPECTED_REVISION=""
if [[ -d "${CURRENT_LINK}/.git" ]]; then
  EXPECTED_REVISION="$(git -C "${CURRENT_LINK}" rev-parse HEAD 2>/dev/null || true)"
fi

validate_runtime() {
  local payload="$1"
  "${PYTHON_BIN}" -c '
import json
import sys

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
if expected_revision and identity.get("source_revision") != expected_revision:
    raise SystemExit(1)
' "${EXPECTED_REVISION}" <<<"${payload}" >/dev/null 2>&1
}

deadline=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  if systemctl is-active --quiet "${SERVICE_NAME}" \
      && curl --fail --silent --show-error --max-time 3 "${BACKEND_URL}/health" >/dev/null 2>&1; then
    runtime_payload="$(curl --fail --silent --show-error --max-time 5 "${BACKEND_URL}/runtime" 2>/dev/null || true)"
    if [[ -n "${runtime_payload}" ]] && validate_runtime "${runtime_payload}"; then
      echo "ready: service active, backend healthy, real Agent/provider ready, revision ${EXPECTED_REVISION:-unavailable}"
      exit 0
    fi
  fi
  sleep 2
done

echo "readiness failed after ${TIMEOUT_SECONDS}s; inspect the private systemd journal on the server" >&2
exit 1
