#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "remote-deploy.sh must run as root" >&2
  exit 1
fi

REVISION="${1:-}"
DEPLOY_REF="${2:-}"
REPOSITORY_URL="${3:-}"
RELEASE_ID="${4:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_USER="specialist-model-studio"
APP_GROUP="specialist-model-studio"
APP_ROOT="/opt/specialist-model-studio"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
PREVIOUS_LINK="${APP_ROOT}/previous"
DATA_ROOT="/opt/specialist-model-studio-data"
ENV_FILE="/etc/specialist-model-studio/studio.env"
SERVICE_FILE="/etc/systemd/system/specialist-model-studio.service"
NGINX_FILE="/etc/nginx/conf.d/specialist-model-studio.conf"
LIBEXEC_DIR="/usr/local/libexec/specialist-model-studio"
HTPASSWD_FILE="/etc/nginx/.htpasswd-specialist-model-studio"
TLS_CERT="/etc/letsencrypt/live/studio.learnbuddy.top/fullchain.pem"
TLS_KEY="/etc/letsencrypt/live/studio.learnbuddy.top/privkey.pem"
NODE_DIR="/opt/node-v22.23.1/bin"
PNPM_VERSION="11.19.0"
PYTHON_BIN="/usr/bin/python3.12"
UV_VERSION="0.9.21"
PYTHON_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"

if ! [[ "${REVISION}" =~ ^[0-9a-f]{40}$ ]] \
    || ! [[ "${DEPLOY_REF}" =~ ^[A-Za-z0-9._/-]+$ ]] \
    || ! [[ "${REPOSITORY_URL}" =~ ^https://github\.com/[A-Za-z0-9._/-]+\.git$ ]] \
    || ! [[ "${RELEASE_ID}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}$ ]]; then
  echo "Invalid deployment identity." >&2
  exit 2
fi

for command in git curl nginx systemctl runuser stat; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Missing required server command: ${command}" >&2
    exit 1
  fi
done

UV_BIN="$(command -v uv || true)"
if [[ -z "${UV_BIN}" ]]; then
  echo "Missing uv on the server." >&2
  exit 1
fi
if [[ "$("${UV_BIN}" --version | awk '{print $2}')" != "${UV_VERSION}" ]]; then
  echo "uv ${UV_VERSION} is required on the server." >&2
  exit 1
fi
if [[ ! -x "${PYTHON_BIN}" ]] || [[ "$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.12" ]]; then
  echo "Python 3.12 is required at ${PYTHON_BIN}." >&2
  exit 1
fi
if [[ ! -x "${NODE_DIR}/node" ]] || [[ "$("${NODE_DIR}/node" --version)" != "v22.23.1" ]] || [[ ! -x "${NODE_DIR}/npm" ]]; then
  echo "Node v22.23.1 and npm are required in ${NODE_DIR}." >&2
  exit 1
fi
if [[ ! -x "${NODE_DIR}/corepack" ]]; then
  echo "Corepack is required in ${NODE_DIR} so DSH can manage profile plugins." >&2
  exit 1
fi
env PATH="${NODE_DIR}:/usr/bin:/bin" corepack enable pnpm
env PATH="${NODE_DIR}:/usr/bin:/bin" corepack prepare "pnpm@${PNPM_VERSION}" --activate
if [[ "$(env PATH="${NODE_DIR}:/usr/bin:/bin" pnpm --version)" != "${PNPM_VERSION}" ]]; then
  echo "pnpm ${PNPM_VERSION} could not be activated through Corepack." >&2
  exit 1
fi

if [[ ! -s "${ENV_FILE}" ]] \
    || [[ "$(stat -c '%U:%G' "${ENV_FILE}")" != "root:root" ]] \
    || [[ "$(stat -c '%a' "${ENV_FILE}")" != "600" ]]; then
  echo "Refusing deployment: ${ENV_FILE} must already exist, be non-empty, root:root, and mode 600." >&2
  exit 1
fi
for required_file in "${HTPASSWD_FILE}" "${TLS_CERT}" "${TLS_KEY}"; do
  if [[ ! -s "${required_file}" ]]; then
    echo "Refusing deployment: required private-preview file is missing: ${required_file}" >&2
    exit 1
  fi
done

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "${DATA_ROOT}/home" --shell /usr/sbin/nologin "${APP_USER}"
fi

install -d -o root -g root -m 0755 "${APP_ROOT}" "${RELEASES_DIR}"
for directory in home runs exports dsh cache cache/uv cache/huggingface; do
  install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${DATA_ROOT}/${directory}"
done

RELEASE_DIR="${RELEASES_DIR}/${RELEASE_ID}"
if [[ -e "${RELEASE_DIR}" ]]; then
  echo "Refusing deployment: release already exists: ${RELEASE_DIR}" >&2
  exit 1
fi
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${RELEASE_DIR}"

run_as_app() {
  runuser -u "${APP_USER}" -- env \
    HOME="${DATA_ROOT}/home" \
    PATH="${NODE_DIR}:/usr/local/bin:/usr/bin:/bin" \
    UV_CACHE_DIR="${DATA_ROOT}/cache/uv" \
    "$@"
}

run_as_app git clone --quiet --filter=blob:none --no-checkout --branch "${DEPLOY_REF}" "${REPOSITORY_URL}" "${RELEASE_DIR}"
run_as_app git -C "${RELEASE_DIR}" checkout --quiet --detach "${REVISION}"
OBSERVED_REVISION="$(run_as_app git -C "${RELEASE_DIR}" rev-parse HEAD)"
if [[ "${OBSERVED_REVISION}" != "${REVISION}" ]] || [[ -n "$(run_as_app git -C "${RELEASE_DIR}" status --porcelain --untracked-files=no)" ]]; then
  echo "Release checkout did not reproduce the requested clean revision." >&2
  exit 1
fi

LOCKED_REQUIREMENTS="${RELEASE_DIR}/.deployment-requirements.txt"
run_as_app "${UV_BIN}" export \
  --quiet \
  --directory "${RELEASE_DIR}" \
  --frozen \
  --extra server \
  --format requirements-txt \
  --no-emit-project \
  --output-file "${LOCKED_REQUIREMENTS}"
run_as_app "${UV_BIN}" venv \
  --directory "${RELEASE_DIR}" \
  --python "${PYTHON_BIN}" \
  "${RELEASE_DIR}/.venv"
run_as_app "${UV_BIN}" pip install \
  --directory "${RELEASE_DIR}" \
  --python "${RELEASE_DIR}/.venv/bin/python" \
  --require-hashes \
  --default-index "${PYTHON_INDEX_URL}" \
  --no-progress \
  --requirement "${LOCKED_REQUIREMENTS}"
run_as_app "${UV_BIN}" pip install \
  --directory "${RELEASE_DIR}" \
  --python "${RELEASE_DIR}/.venv/bin/python" \
  --no-deps \
  --default-index "${PYTHON_INDEX_URL}" \
  --no-progress \
  "${RELEASE_DIR}"
rm -f -- "${LOCKED_REQUIREMENTS}"
run_as_app "${NODE_DIR}/npm" ci --prefix "${RELEASE_DIR}/integrations/deepseek-harness" --ignore-scripts
run_as_app "${NODE_DIR}/npm" ci --prefix "${RELEASE_DIR}/acceptance/dsh-runtime" --ignore-scripts

if [[ ! -x "${RELEASE_DIR}/.venv/bin/specialist-model-studio" ]] \
    || [[ ! -x "${RELEASE_DIR}/acceptance/dsh-runtime/node_modules/.bin/dsh" ]]; then
  echo "Locked Python/DSH runtime installation is incomplete." >&2
  exit 1
fi

NGINX_BACKUP=""
if [[ -f "${NGINX_FILE}" ]]; then
  NGINX_BACKUP="${SCRIPT_DIR}/nginx-site.previous.conf"
  cp --preserve=mode,ownership,timestamps "${NGINX_FILE}" "${NGINX_BACKUP}"
fi
install -o root -g root -m 0644 "${SCRIPT_DIR}/specialist-model-studio.service" "${SERVICE_FILE}"
install -o root -g root -m 0644 "${SCRIPT_DIR}/nginx-site.conf" "${NGINX_FILE}"
install -d -o root -g root -m 0755 "${LIBEXEC_DIR}"
install -o root -g root -m 0755 "${SCRIPT_DIR}/readiness.sh" "${LIBEXEC_DIR}/readiness.sh"
if ! nginx -t; then
  if [[ -n "${NGINX_BACKUP}" ]]; then
    install -o root -g root -m 0644 "${NGINX_BACKUP}" "${NGINX_FILE}"
  else
    rm -f -- "${NGINX_FILE}"
  fi
  echo "Nginx validation failed; the previous site file was restored." >&2
  exit 1
fi

OLD_TARGET="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
if [[ -n "${OLD_TARGET}" && -d "${OLD_TARGET}" && "${OLD_TARGET}" == "${RELEASES_DIR}/"* ]]; then
  ln -sfn "${OLD_TARGET}" "${PREVIOUS_LINK}.next"
  mv -Tf "${PREVIOUS_LINK}.next" "${PREVIOUS_LINK}"
fi
ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}.next"
mv -Tf "${CURRENT_LINK}.next" "${CURRENT_LINK}"

systemctl daemon-reload
if ! systemctl restart specialist-model-studio.service \
    || ! "${LIBEXEC_DIR}/readiness.sh" 180 \
    || ! systemctl reload nginx; then
  echo "New release failed readiness or Nginx activation; restoring the previous release." >&2
  if [[ -n "${NGINX_BACKUP}" ]]; then
    install -o root -g root -m 0644 "${NGINX_BACKUP}" "${NGINX_FILE}"
  else
    rm -f -- "${NGINX_FILE}"
  fi
  if nginx -t; then
    systemctl reload nginx || true
  fi
  if [[ -n "${OLD_TARGET}" && -d "${OLD_TARGET}" && "${OLD_TARGET}" == "${RELEASES_DIR}/"* ]]; then
    ln -sfn "${OLD_TARGET}" "${CURRENT_LINK}.restore"
    mv -Tf "${CURRENT_LINK}.restore" "${CURRENT_LINK}"
    systemctl restart specialist-model-studio.service || true
    "${LIBEXEC_DIR}/readiness.sh" 120 || true
  else
    systemctl stop specialist-model-studio.service || true
  fi
  exit 1
fi

systemctl enable specialist-model-studio.service >/dev/null

echo "release=${RELEASE_ID} revision=${REVISION} service=ready url=https://studio.learnbuddy.top/app"
