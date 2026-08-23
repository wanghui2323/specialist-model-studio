#!/usr/bin/env bash
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_HOST="${MODEL_HARNESS_HOST:-127.0.0.1}"
BACKEND_PORT="${MODEL_HARNESS_PORT:-8765}"
AGENT_HOST="${MODEL_HARNESS_AGENT_HOST:-127.0.0.1}"
AGENT_PORT="${MODEL_HARNESS_AGENT_PORT:-3080}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
AGENT_URL="http://${AGENT_HOST}:${AGENT_PORT}"
HARNESS_PYTHON="${HARNESS_ROOT}/.venv/bin/python"
BACKEND_LOG="${HARNESS_ROOT}/runs/.conversation-backend.log"
STARTED_BACKEND=0
BACKEND_PID=""

if [[ ! -x "${HARNESS_PYTHON}" ]]; then
  echo "Missing ${HARNESS_PYTHON}. Run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[server]'" >&2
  exit 1
fi

if ! command -v dsh >/dev/null 2>&1; then
  echo "DeepSeek Harness CLI (dsh) is not installed or not on PATH." >&2
  exit 1
fi

"${HARNESS_ROOT}/scripts/install_dsh_preset.sh"

echo "Inspecting the DSH web profile..."
if ! DSH_CONFIG="$(dsh --profile web --dump-config 2>&1)"; then
  echo "Could not inspect the DSH web profile:" >&2
  echo "${DSH_CONFIG}" >&2
  exit 1
fi

if ! grep -E "(specialist-model-studio|ai-pm-model-harness)-dsh-plugin" >/dev/null <<<"${DSH_CONFIG}"; then
  echo "The Specialist Model Studio plugin is not linked to the DSH web profile." >&2
  echo "Run: dsh plugin --profile web add \"${HARNESS_ROOT}/integrations/deepseek-harness\"" >&2
  exit 1
fi

mkdir -p "${HARNESS_ROOT}/runs"

echo "Checking the Specialist Model Studio backend..."

cleanup() {
  if [[ "${STARTED_BACKEND}" == "1" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if ! curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; then
  MODEL_HARNESS_CONVERSATION_URL="${AGENT_URL}" \
    PYTHONPATH="${HARNESS_ROOT}" \
    "${HARNESS_PYTHON}" -m model_harness.cli serve \
      --runs-dir "${HARNESS_ROOT}/runs" \
      --host "${BACKEND_HOST}" \
      --port "${BACKEND_PORT}" >"${BACKEND_LOG}" 2>&1 &
  BACKEND_PID="$!"
  STARTED_BACKEND=1

  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    if curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
fi

if ! curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; then
  echo "Specialist Model Studio backend did not become healthy. See ${BACKEND_LOG}" >&2
  exit 1
fi

echo "Specialist Model Studio: ${BACKEND_URL}/app"
echo "DSH runtime (internal/debug): ${AGENT_URL}"
echo "Press Ctrl-C to stop services started by this command."

cd "${HARNESS_ROOT}"
if curl --fail --silent --max-time 2 "${AGENT_URL}/api/session.list" \
  -H "content-type: application/json" \
  --data '{"type":"client-request","rpcId":"model-harness-startup-probe","method":"session.list","payload":{}}' >/dev/null 2>&1; then
  echo "Reusing the existing DSH runtime."
  if [[ "${STARTED_BACKEND}" == "1" ]]; then
    wait "${BACKEND_PID}"
  else
    while curl --fail --silent --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; do
      sleep 5
    done
  fi
  exit 0
fi

MODEL_HARNESS_URL="${BACKEND_URL}" \
  dsh web --host "${AGENT_HOST}" --port "${AGENT_PORT}"
