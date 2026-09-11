#!/usr/bin/env bash
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_HOST="${MODEL_HARNESS_HOST:-127.0.0.1}"
BACKEND_PORT="${MODEL_HARNESS_PORT:-8765}"
AGENT_HOST="${MODEL_HARNESS_AGENT_HOST:-127.0.0.1}"
AGENT_PORT="${MODEL_HARNESS_AGENT_PORT:-3080}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
AGENT_URL="http://${AGENT_HOST}:${AGENT_PORT}"
HARNESS_PYTHON="${MODEL_HARNESS_PYTHON:-${HARNESS_ROOT}/.venv/bin/python}"
RUNS_DIR_INPUT="${MODEL_HARNESS_RUNS_DIR:-${HARNESS_ROOT}/runs}"
LOCKED_DSH_RUNTIME="${HARNESS_ROOT}/acceptance/dsh-runtime"
LOCKED_DSH_BIN="${LOCKED_DSH_RUNTIME}/node_modules/.bin/dsh"
EXPECTED_DSH_VERSION="0.1.0-rc.6"
CURRENT_DSH_PLUGIN="specialist-model-studio-dsh-plugin"
LEGACY_DSH_PLUGIN="ai-pm-model-harness-dsh-plugin"
EXPECTED_PROJECTOR_REVISION="3.3"
EXPECTED_SYNTHESIS_VERDICT_VERSION="1.0"
EXPECTED_ACTION_SCHEMA_VERSION="1.0"
EXPECTED_CONVERSATION_SCHEMA="${MODEL_HARNESS_CONVERSATION_SCHEMA_VERSION:-2.0}"
STARTED_BACKEND=0
BACKEND_PID=""
STARTED_AGENT=0
AGENT_PID=""
REUSED_BACKEND=0
AGENT_BRIDGE_TOKEN="${MODEL_HARNESS_AGENT_BRIDGE_TOKEN:-}"
PUBLIC_START="${SPECIALIST_MODEL_STUDIO_PUBLIC_START:-0}"
L6_ACCEPTANCE="${SPECIALIST_MODEL_STUDIO_L6_ACCEPTANCE:-0}"
BACKEND_START_ATTEMPTS="${MODEL_HARNESS_BACKEND_START_ATTEMPTS:-180}"
PREFLIGHT_TIMEOUT_SECONDS="${MODEL_HARNESS_PREFLIGHT_TIMEOUT_SECONDS:-60}"
REQUIRE_PROVIDER_READY=0
if [[ "${PUBLIC_START}" == "1" || "${L6_ACCEPTANCE}" == "1" ]]; then
  REQUIRE_PROVIDER_READY=1
fi
ALLOW_SYSTEM_DSH="${MODEL_HARNESS_ALLOW_SYSTEM_DSH:-0}"
DSH_BIN=""

status() {
  if [[ "${PUBLIC_START}" != "1" ]]; then
    printf '%s\n' "$*"
  fi
}

announce_product() {
  if [[ "${PUBLIC_START}" == "1" ]]; then
    printf '%s\n' "${BACKEND_URL}/app"
  else
    echo "Specialist Model Studio: ${BACKEND_URL}/app"
    echo "DSH runtime (internal/debug): ${AGENT_URL}"
    echo "Press Ctrl-C to stop services started by this command."
  fi
}

if [[ ! -x "${HARNESS_PYTHON}" ]]; then
  echo "Missing ${HARNESS_PYTHON}. Run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[server]'" >&2
  exit 1
fi

if ! [[ "${BACKEND_START_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "MODEL_HARNESS_BACKEND_START_ATTEMPTS must be a positive integer." >&2
  exit 1
fi

if ! [[ "${PREFLIGHT_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "MODEL_HARNESS_PREFLIGHT_TIMEOUT_SECONDS must be a positive integer." >&2
  exit 1
fi

# Local dependency files can be cloud placeholders or damaged. Bound each
# preflight subprocess, including its children, without logging partial config
# output (which may contain provider settings). This is not a model-code worker.
run_preflight() {
  "${HARNESS_PYTHON}" - "${PREFLIGHT_TIMEOUT_SECONDS}" "$@" <<'PY'
import os
import signal
import subprocess
import sys

def stop(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()

try:
    process = subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
except OSError:
    print("Runtime preflight command could not start.", file=sys.stderr)
    sys.exit(127)
try:
    output, errors = process.communicate(timeout=int(sys.argv[1]))
except subprocess.TimeoutExpired:
    stop(process)
    print("Runtime preflight timed out; check locally available dependencies and reinstall from the lockfile.", file=sys.stderr)
    sys.exit(124)
except KeyboardInterrupt:
    stop(process)
    sys.exit(130)
sys.stdout.buffer.write(output)
sys.stderr.buffer.write(errors)
sys.exit(process.returncode)
PY
}

RUNS_DIR="$("${HARNESS_PYTHON}" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${RUNS_DIR_INPUT}")"
WORKSPACE_DIR="${RUNS_DIR}/_workspace"
ARTIFACT_EXPORT_DIR_INPUT="${MODEL_HARNESS_ARTIFACT_EXPORT_DIR:-${WORKSPACE_DIR}/exports}"
MODEL_HARNESS_ARTIFACT_EXPORT_DIR="$("${HARNESS_PYTHON}" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve(strict=False))' "${ARTIFACT_EXPORT_DIR_INPUT}")"
export MODEL_HARNESS_ARTIFACT_EXPORT_DIR
BACKEND_LOG="${RUNS_DIR}/.conversation-backend.log"
DSH_ROOT_INPUT="${DSH_HOME:-${RUNS_DIR}/.dsh}"
DSH_ROOT="$("${HARNESS_PYTHON}" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${DSH_ROOT_INPUT}")"
export DSH_HOME="${DSH_ROOT}"
STANDARD_DSH_CREDENTIALS_INPUT="${HOME:-}/.dsh/.credentials.yaml"
CREDENTIALS_FILE_INPUT="${MODEL_HARNESS_DSH_CREDENTIALS_FILE:-}"
if [[ -z "${CREDENTIALS_FILE_INPUT}" && -n "${HOME:-}" && -f "${STANDARD_DSH_CREDENTIALS_INPUT}" ]]; then
  CREDENTIALS_FILE_INPUT="${STANDARD_DSH_CREDENTIALS_INPUT}"
fi
if [[ -z "${CREDENTIALS_FILE_INPUT}" ]]; then
  CREDENTIALS_FILE_INPUT="${DSH_ROOT}/.credentials.yaml"
fi
MODEL_HARNESS_DSH_CREDENTIALS_FILE="$("${HARNESS_PYTHON}" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve(strict=False))' "${CREDENTIALS_FILE_INPUT}")"
export MODEL_HARNESS_DSH_CREDENTIALS_FILE
DSH_WEB_PACKAGE="${DSH_ROOT}/profiles/web/package.json"

if [[ -x "${LOCKED_DSH_BIN}" ]]; then
  DSH_BIN="${LOCKED_DSH_BIN}"
elif [[ "${ALLOW_SYSTEM_DSH}" == "1" && "${PUBLIC_START}" != "1" && "${L6_ACCEPTANCE}" != "1" ]]; then
  DSH_BIN="$(command -v dsh || true)"
  if [[ -z "${DSH_BIN}" ]]; then
    echo "MODEL_HARNESS_ALLOW_SYSTEM_DSH=1 was set, but no dsh executable is available on PATH." >&2
    exit 1
  fi
  status "Development fallback: using the system DSH CLI at ${DSH_BIN}."
else
  echo "Missing the repository-locked DeepSeek Harness CLI at ${LOCKED_DSH_BIN}." >&2
  echo "Run: npm ci --prefix \"${LOCKED_DSH_RUNTIME}\" --ignore-scripts" >&2
  if [[ "${PUBLIC_START}" == "1" || "${L6_ACCEPTANCE}" == "1" ]]; then
    echo "Public and L6 acceptance starts refuse an unlocked system DSH CLI." >&2
  else
    echo "Developers may explicitly opt into an unlocked PATH fallback with MODEL_HARNESS_ALLOW_SYSTEM_DSH=1." >&2
  fi
  exit 1
fi

if ! OBSERVED_DSH_VERSION="$(run_preflight "${DSH_BIN}" --version 2>&1)"; then
  echo "Could not read the DeepSeek Harness CLI version from ${DSH_BIN}." >&2
  echo "${OBSERVED_DSH_VERSION}" >&2
  exit 1
fi
OBSERVED_DSH_VERSION="$(printf '%s\n' "${OBSERVED_DSH_VERSION}" | sed -n '1p' | tr -d '\r')"
if [[ "${OBSERVED_DSH_VERSION}" != "${EXPECTED_DSH_VERSION}" ]]; then
  echo "DeepSeek Harness CLI version mismatch: expected ${EXPECTED_DSH_VERSION}, observed ${OBSERVED_DSH_VERSION:-<empty>}." >&2
  echo "Reinstall the locked runtime with: npm ci --prefix \"${LOCKED_DSH_RUNTIME}\" --ignore-scripts" >&2
  exit 1
fi

if [[ "${PUBLIC_START}" == "1" ]]; then
  run_preflight "${HARNESS_ROOT}/scripts/install_dsh_preset.sh" >/dev/null
else
  run_preflight "${HARNESS_ROOT}/scripts/install_dsh_preset.sh"
fi

status "Synchronizing the current Specialist Model Studio plugin..."
if [[ -f "${DSH_WEB_PACKAGE}" ]] && grep -Fq "\"${LEGACY_DSH_PLUGIN}\"" "${DSH_WEB_PACKAGE}"; then
  if [[ "${PUBLIC_START}" == "1" ]]; then
    run_preflight "${DSH_BIN}" plugin --profile web remove "${LEGACY_DSH_PLUGIN}" >/dev/null
  else
    run_preflight "${DSH_BIN}" plugin --profile web remove "${LEGACY_DSH_PLUGIN}"
  fi
fi
if [[ "${PUBLIC_START}" == "1" ]]; then
  run_preflight "${DSH_BIN}" plugin --profile web add "${HARNESS_ROOT}/integrations/deepseek-harness" >/dev/null
else
  run_preflight "${DSH_BIN}" plugin --profile web add "${HARNESS_ROOT}/integrations/deepseek-harness"
fi

status "Inspecting the DSH web profile..."
if DSH_CONFIG="$(run_preflight "${DSH_BIN}" --profile web --dump-config 2>&1)"; then
  :
else
  PREFLIGHT_EXIT="$?"
  if [[ "${PREFLIGHT_EXIT}" == "124" ]]; then
    echo "Runtime configuration preflight timed out after ${PREFLIGHT_TIMEOUT_SECONDS}s. Reinstall locked dependencies with npm ci; no services were started." >&2
  fi
  echo "Could not inspect the DSH web profile. Provider diagnostics are withheld here so the selected credential-store path is not written to launcher output." >&2
  exit 1
fi

if ! grep -F "${CURRENT_DSH_PLUGIN}" >/dev/null <<<"${DSH_CONFIG}"; then
  echo "The Specialist Model Studio plugin is not linked to the DSH web profile." >&2
  echo "Run: \"${DSH_BIN}\" plugin --profile web add \"${HARNESS_ROOT}/integrations/deepseek-harness\"" >&2
  exit 1
fi

mkdir -p "${RUNS_DIR}"
AGENT_LOG="${RUNS_DIR}/.conversation-agent.log"

status "Checking the Specialist Model Studio backend..."

fetch_backend_runtime() {
  curl --fail --silent --show-error --max-time 2 "${BACKEND_URL}/runtime"
}

validate_backend_runtime() {
  local runtime_payload="$1"
  local validation_context="$2"
  local expected_revision=""
  local expected_source_dirty=""
  local validation_error=""

  expected_revision="$(git -c "safe.directory=${HARNESS_ROOT}" -C "${HARNESS_ROOT}" rev-parse HEAD 2>/dev/null || true)"
  if [[ -n "${expected_revision}" ]]; then
    if [[ -n "$(git -c "safe.directory=${HARNESS_ROOT}" -C "${HARNESS_ROOT}" status --porcelain --untracked-files=normal 2>/dev/null || true)" ]]; then
      expected_source_dirty="true"
    else
      expected_source_dirty="false"
    fi
  fi
  if ! validation_error="$({
    EXPECTED_RUNS_DIR="${RUNS_DIR}" \
      EXPECTED_WORKSPACE_ROOT="${WORKSPACE_DIR}" \
      EXPECTED_SOURCE_ROOT="${HARNESS_ROOT}" \
      EXPECTED_SOURCE_REVISION="${expected_revision}" \
      EXPECTED_SOURCE_DIRTY="${expected_source_dirty}" \
      EXPECTED_CONVERSATION_ORIGIN="${AGENT_URL}" \
      EXPECTED_PROJECTOR_REVISION="${EXPECTED_PROJECTOR_REVISION}" \
      EXPECTED_SYNTHESIS_VERDICT_VERSION="${EXPECTED_SYNTHESIS_VERDICT_VERSION}" \
      EXPECTED_ACTION_SCHEMA_VERSION="${EXPECTED_ACTION_SCHEMA_VERSION}" \
      EXPECTED_CONVERSATION_SCHEMA="${EXPECTED_CONVERSATION_SCHEMA}" \
      REQUIRE_PROVIDER_READY="${REQUIRE_PROVIDER_READY}" \
      "${HARNESS_PYTHON}" -c '
import json
import os
import sys
from pathlib import Path


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


try:
    payload = json.load(sys.stdin)
except (TypeError, ValueError) as exc:
    fail(f"/runtime did not return valid JSON: {exc}")

if not isinstance(payload, dict):
    fail("/runtime payload must be a JSON object")

agent = payload.get("agent")
if not isinstance(agent, dict):
    fail("/runtime.agent must be a JSON object")

required = {
    "available": True,
    "real_agent": True,
    "implementation": "dsh_native_subagents",
    "conversation_schema_version": os.environ["EXPECTED_CONVERSATION_SCHEMA"],
    "synthesis_verdict_version": os.environ["EXPECTED_SYNTHESIS_VERDICT_VERSION"],
    "conversation_action_schema_version": os.environ["EXPECTED_ACTION_SCHEMA_VERSION"],
    "task_truth_source": "TrainingTask",
}
for key, expected in required.items():
    observed = agent.get(key)
    if observed != expected:
        fail(f"agent.{key} expected {expected!r}, observed {observed!r}")

if os.environ["REQUIRE_PROVIDER_READY"] == "1":
    for key in ("transport_ready", "ready"):
        observed = agent.get(key)
        if observed is not True:
            fail(f"agent.{key} expected True, observed {observed!r}")
    provider = agent.get("provider")
    if not isinstance(provider, dict):
        fail("agent.provider must be a JSON object for a public or L6 start")
    for key in ("active", "configured", "ready"):
        observed = provider.get(key)
        if observed is not True:
            fail(f"agent.provider.{key} expected True, observed {observed!r}")

observed_projector = agent.get("conversation_projector_revision")
expected_projector = os.environ["EXPECTED_PROJECTOR_REVISION"]
if observed_projector != expected_projector:
    fail(
        "agent.conversation_projector_revision is incompatible: "
        f"expected {expected_projector!r}, "
        f"observed {observed_projector!r}"
    )

if payload.get("primary_experience") != "conversation":
    fail(
        "primary_experience expected 'conversation', "
        f"observed {payload.get('primary_experience')!r}"
    )


def canonical(value):
    return str(Path(value).expanduser().resolve(strict=False))


runtime_identity = payload.get("runtime_identity")
if not isinstance(runtime_identity, dict):
    fail("/runtime.runtime_identity must be a JSON object")

identity_paths = {
    "source_root": os.environ["EXPECTED_SOURCE_ROOT"],
    "runs_dir": os.environ["EXPECTED_RUNS_DIR"],
    "workspace_dir": os.environ["EXPECTED_WORKSPACE_ROOT"],
}
for key, expected in identity_paths.items():
    observed = runtime_identity.get(key)
    if not isinstance(observed, str) or canonical(observed) != canonical(expected):
        fail(
            f"runtime_identity.{key} does not identify this startup target: "
            f"expected {canonical(expected)!r}, observed {observed!r}"
        )

expected_origin = os.environ["EXPECTED_CONVERSATION_ORIGIN"].rstrip("/")
observed_origin = runtime_identity.get("conversation_origin")
if not isinstance(observed_origin, str) or observed_origin.rstrip("/") != expected_origin:
    fail(
        "runtime_identity.conversation_origin does not identify the configured "
        f"DSH endpoint: expected {expected_origin!r}, observed {observed_origin!r}"
    )


containers = [("runtime", payload), ("agent", agent)]
for owner, candidate in (
    ("runtime.identity", payload.get("identity")),
    ("agent.identity", agent.get("identity")),
):
    if isinstance(candidate, dict):
        containers.append((owner, candidate))

path_contracts = {
    "runs_dir": os.environ["EXPECTED_RUNS_DIR"],
    "runs_root": os.environ["EXPECTED_RUNS_DIR"],
    "workspace_root": os.environ["EXPECTED_WORKSPACE_ROOT"],
    "source_root": os.environ["EXPECTED_SOURCE_ROOT"],
    "project_root": os.environ["EXPECTED_SOURCE_ROOT"],
    "harness_root": os.environ["EXPECTED_SOURCE_ROOT"],
}
for owner, container in containers:
    for key, expected in path_contracts.items():
        observed = container.get(key)
        if observed in (None, ""):
            continue
        if not isinstance(observed, str) or canonical(observed) != canonical(expected):
            fail(
                f"{owner}.{key} does not identify this checkout: "
                f"expected {canonical(expected)!r}, observed {observed!r}"
            )

expected_source_revision = os.environ.get("EXPECTED_SOURCE_REVISION", "")
if expected_source_revision:
    observed_source_revision = runtime_identity.get("source_revision")
    if observed_source_revision != expected_source_revision:
        fail(
            "runtime_identity.source_revision does not identify this checkout: "
            f"expected {expected_source_revision!r}, "
            f"observed {observed_source_revision!r}"
        )
    for owner, container in containers:
        for key in ("source_revision", "git_revision", "git_commit"):
            observed = container.get(key)
            if observed not in (None, "") and observed != expected_source_revision:
                fail(
                    f"{owner}.{key} does not identify this source revision: "
                    f"expected {expected_source_revision!r}, observed {observed!r}"
                )

expected_source_dirty = os.environ.get("EXPECTED_SOURCE_DIRTY", "")
if expected_source_dirty in {"true", "false"}:
    expected_dirty_value = expected_source_dirty == "true"
    observed_source_dirty = runtime_identity.get("source_dirty")
    if observed_source_dirty is not expected_dirty_value:
        fail(
            "runtime_identity.source_dirty does not identify this checkout: "
            f"expected {expected_dirty_value!r}, observed {observed_source_dirty!r}"
        )
' <<<"${runtime_payload}"
  } 2>&1)"; then
    echo "Refusing ${validation_context}: ${BACKEND_URL} is not the expected real multi-agent runtime." >&2
    echo "${validation_error}" >&2
    echo "Choose unused MODEL_HARNESS_PORT / MODEL_HARNESS_AGENT_PORT values, or stop the exact conflicting process after identifying it." >&2
    return 1
  fi
}

wait_for_real_agent_runtime() {
  local runtime_payload=""
  local last_error="/runtime was not reachable"
  local validation_output=""

  for _attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if [[ "${STARTED_AGENT}" == "1" ]] && ! kill -0 "${AGENT_PID}" 2>/dev/null; then
      echo "DSH runtime exited before the backend reported a compatible real Agent." >&2
      return 1
    fi
    if runtime_payload="$(fetch_backend_runtime 2>/dev/null)"; then
      if validation_output="$(validate_backend_runtime "${runtime_payload}" "runtime readiness" 2>&1)"; then
        return 0
      fi
      last_error="${validation_output}"
    fi
    sleep 0.5
  done

  echo "The backend never reported a compatible real multi-agent runtime." >&2
  echo "${last_error}" >&2
  return 1
}

cleanup() {
  if [[ "${STARTED_AGENT}" == "1" ]] && kill -0 "${AGENT_PID}" 2>/dev/null; then
    kill "${AGENT_PID}" 2>/dev/null || true
  fi
  if [[ "${STARTED_BACKEND}" == "1" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; then
  if [[ -z "${AGENT_BRIDGE_TOKEN}" ]]; then
    echo "Refusing to reuse ${BACKEND_URL} without the same MODEL_HARNESS_AGENT_BRIDGE_TOKEN used to start it." >&2
    exit 1
  fi
  if ! EXISTING_RUNTIME="$(fetch_backend_runtime 2>&1)"; then
    echo "Refusing to reuse ${BACKEND_URL}: /health responded but /runtime could not be read." >&2
    echo "${EXISTING_RUNTIME}" >&2
    exit 1
  fi
  if ! validate_backend_runtime "${EXISTING_RUNTIME}" "to reuse the running backend"; then
    exit 1
  fi
  REUSED_BACKEND=1
else
  if [[ -z "${AGENT_BRIDGE_TOKEN}" ]]; then
    AGENT_BRIDGE_TOKEN="$("${HARNESS_PYTHON}" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  fi
  MODEL_HARNESS_CONVERSATION_URL="${AGENT_URL}" \
      MODEL_HARNESS_AGENT_BRIDGE_TOKEN="${AGENT_BRIDGE_TOKEN}" \
      PYTHONPATH="${HARNESS_ROOT}" \
    "${HARNESS_PYTHON}" -m model_harness.cli serve \
      --runs-dir "${RUNS_DIR}" \
      --host "${BACKEND_HOST}" \
      --port "${BACKEND_PORT}" >"${BACKEND_LOG}" 2>&1 &
  BACKEND_PID="$!"
  STARTED_BACKEND=1

  # A pristine environment may spend tens of seconds importing NumPy, SciPy,
  # and scikit-learn before Uvicorn can bind the port.  Keep the health gate,
  # but give a real cold start up to 90 seconds by default instead of declaring
  # a healthy checkout dead after five seconds.
  for ((_attempt=1; _attempt<=BACKEND_START_ATTEMPTS; _attempt++)); do
    if curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; then
      break
    fi
    if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
fi

if ! curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; then
  echo "Specialist Model Studio backend did not become healthy. See ${BACKEND_LOG}" >&2
  exit 1
fi

cd "${HARNESS_ROOT}"
if curl --fail --silent --max-time 2 "${AGENT_URL}/api/session.list" \
  -H "content-type: application/json" \
  --data '{"type":"client-request","rpcId":"model-harness-startup-probe","method":"session.list","payload":{}}' >/dev/null 2>&1; then
  if ! wait_for_real_agent_runtime; then
    echo "The running DSH endpoint is not connected to the expected Specialist Model Studio backend." >&2
    exit 1
  fi
  status "Reusing the existing DSH runtime."
  announce_product
  if [[ "${STARTED_BACKEND}" == "1" ]]; then
    wait "${BACKEND_PID}"
  else
    while curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; do
      sleep 5
    done
  fi
  exit 0
fi

if [[ "${REUSED_BACKEND}" == "1" ]]; then
  echo "Refusing to start another DSH process: the reused backend reported a real Agent, but ${AGENT_URL} did not pass the DSH session probe." >&2
  exit 1
fi

if [[ "${PUBLIC_START}" == "1" ]]; then
  MODEL_HARNESS_URL="${BACKEND_URL}" \
    MODEL_HARNESS_AGENT_BRIDGE_TOKEN="${AGENT_BRIDGE_TOKEN}" \
    "${DSH_BIN}" web --no-open --host "${AGENT_HOST}" --port "${AGENT_PORT}" >"${AGENT_LOG}" 2>&1 &
else
  MODEL_HARNESS_URL="${BACKEND_URL}" \
    MODEL_HARNESS_AGENT_BRIDGE_TOKEN="${AGENT_BRIDGE_TOKEN}" \
    "${DSH_BIN}" web --no-open --host "${AGENT_HOST}" --port "${AGENT_PORT}" &
fi
AGENT_PID="$!"
STARTED_AGENT=1

if ! wait_for_real_agent_runtime; then
  exit 1
fi

status "Verified the multi-agent transport contract; model-provider readiness is enforced by the product."
announce_product
wait "${AGENT_PID}"
