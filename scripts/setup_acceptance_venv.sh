#!/usr/bin/env bash
set -euo pipefail

# Local acceptance helper: build a clean Python venv for the Studio backend when
# the repo `.venv` is not usable (e.g. a native wheel that hangs on import).
#
# The host may sit behind a local HTTPS proxy whose certificate is not in the
# system Python trust store, and the proxy itself can be up or down between
# sessions. We therefore install against PyPI directly and skip TLS host
# verification for the package index only; this does not change the app or its
# network policy, only how the acceptance venv is populated.

HARNESS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${MODEL_HARNESS_ACCEPT_VENV:-${HARNESS_ROOT}/.venv-accept}"
PYTHON_BIN="${MODEL_HARNESS_ACCEPT_PYTHON:-python3}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy ALL_PROXY all_proxy

"${VENV_DIR}/bin/python" -m pip install -q --trusted-host pypi.org \
  --trusted-host files.pythonhosted.org \
  "numpy==2.5.2" "scipy==1.18.0" "scikit-learn==1.9.0" \
  "onnxruntime==1.29.0" "threadpoolctl==3.6.0" "joblib" "Pillow" \
  "certifi>=2024.8.30" "huggingface-hub>=0.34,<1.0" \
  "fastapi>=0.115,<1.0" "uvicorn>=0.30,<1.0" "websockets>=15,<16" \
  "httpx2>=2.0,<3.0" "setuptools>=69" "wheel"

# Editable install with --no-deps so the CLI entry points exist (the test suite
# checks the installed console scripts). Build isolation is disabled so the
# step does not need to reach the network again for setuptools.
"${VENV_DIR}/bin/python" -m pip install -q --no-deps --no-build-isolation -e "${HARNESS_ROOT}"

echo "Acceptance venv ready: ${VENV_DIR}/bin/python"
echo "Run: PYTHONPATH=\"${HARNESS_ROOT}\" \"${VENV_DIR}/bin/python\" -m model_harness.cli serve --runs-dir <runs-dir> --host 127.0.0.1 --port 8891"
