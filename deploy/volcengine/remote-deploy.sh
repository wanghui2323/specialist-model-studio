#!/usr/bin/env bash
set -euo pipefail

REVISION="${1:-}"
DEPLOY_REF="${2:-}"
REPOSITORY_URL="${3:-}"
RELEASE_ID="${4:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_USER="specialist-model-studio"
APP_GROUP="specialist-model-studio"
APP_ROOT="/opt/specialist-model-studio"
RELEASES_DIR="${APP_ROOT}/releases"
LEGACY_RELEASES_DIR="/opt/specialist-model-studio-releases"
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
RELEASE_MANIFEST_NAME=".git/specialist-model-studio-release.json"
CONFIG_BACKUP_DIR="${SCRIPT_DIR}/configuration.previous"

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

write_release_manifest() {
  local release_dir="${1:-}"
  local revision="${2:-}"
  local release_id="${3:-}"
  local manifest_path="${release_dir}/${RELEASE_MANIFEST_NAME}"
  local staged_manifest="${SCRIPT_DIR}/specialist-model-studio-release.${release_id}.next"

  [[ ! -e "${manifest_path}" && ! -L "${manifest_path}" ]] || return 1
  "${PYTHON_BIN}" - "${revision}" "${release_id}" >"${staged_manifest}" <<'PY'
import json
import sys

print(json.dumps({
    "schema_version": 1,
    "revision": sys.argv[1],
    "release_id": sys.argv[2],
    "build_complete": True,
}, sort_keys=True, separators=(",", ":")))
PY
  install -o root -g root -m 0444 "${staged_manifest}" "${manifest_path}"
  rm -f -- "${staged_manifest}"
  release_manifest_revision "${release_dir}" "${revision}" "${release_id}" >/dev/null
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

restore_current_after_failed_deploy() {
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
  local readiness_script="${3:-${LIBEXEC_DIR}/readiness.sh}"

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

backup_managed_file() {
  local source_path="${1:-}"
  local backup_path="${2:-}"

  [[ -n "${source_path}" && -n "${backup_path}" ]] || return 1
  if [[ -L "${source_path}" ]]; then
    echo "Refusing deployment: managed configuration is a symbolic link: ${source_path}" >&2
    return 1
  fi
  if [[ ! -e "${source_path}" ]]; then
    return 2
  fi
  [[ -f "${source_path}" ]] || return 1
  cp -p "${source_path}" "${backup_path}"
}

restore_managed_file() {
  local destination="${1:-}"
  local backup_path="${2:-}"
  local existed="${3:-}"

  [[ -n "${destination}" && -n "${backup_path}" ]] || return 1
  case "${existed}" in
    true)
      [[ -f "${backup_path}" && ! -L "${backup_path}" ]] || return 1
      cp -p "${backup_path}" "${destination}"
      ;;
    false)
      rm -f -- "${destination}"
      ;;
    *)
      return 1
      ;;
  esac
}

restore_installed_configuration() {
  restore_managed_file "${SERVICE_FILE}" "${CONFIG_BACKUP_DIR}/service" "${HAD_SERVICE_FILE}"
  restore_managed_file "${LIBEXEC_DIR}/readiness.sh" "${CONFIG_BACKUP_DIR}/readiness" "${HAD_READINESS_FILE}"
  restore_managed_file "${NGINX_FILE}" "${CONFIG_BACKUP_DIR}/nginx" "${HAD_NGINX_FILE}"
  systemctl daemon-reload
  nginx -t
  systemctl reload nginx
}

restore_previous_after_failed_deploy() {
  local observed_target

  observed_target="$(readlink -f "${PREVIOUS_LINK}" 2>/dev/null || true)"
  if [[ "${HAD_PREVIOUS}" == "true" ]]; then
    if [[ "${observed_target}" == "${OLD_PREVIOUS_TARGET}" ]]; then
      return 0
    fi
    [[ "${observed_target}" == "${OLD_TARGET}" ]] || return 1
    atomic_replace_release_link "${OLD_PREVIOUS_TARGET}" "${PREVIOUS_LINK}" "restore"
    return
  fi
  [[ "${HAD_PREVIOUS}" == "false" ]] || return 1
  if [[ -z "${observed_target}" && ! -L "${PREVIOUS_LINK}" ]]; then
    return 0
  fi
  [[ "${observed_target}" == "${OLD_TARGET}" ]] || return 1
  rm -f -- "${PREVIOUS_LINK}"
  [[ ! -e "${PREVIOUS_LINK}" && ! -L "${PREVIOUS_LINK}" ]]
}

activate_new_release() {
  systemctl daemon-reload
  systemctl restart specialist-model-studio.service
  run_readiness_for_release "${RELEASE_DIR}" 180
  systemctl reload nginx
  if [[ "${HAD_CURRENT}" == "true" ]]; then
    atomic_replace_release_link "${OLD_TARGET}" "${PREVIOUS_LINK}" "next"
  fi
  systemctl enable specialist-model-studio.service >/dev/null
}

# Allow shell-level tests to source the transaction helpers without executing a
# privileged deployment. Normal invocation still follows the full path below.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

if (( EUID != 0 )); then
  echo "remote-deploy.sh must run as root" >&2
  exit 1
fi

if ! [[ "${REVISION}" =~ ^[0-9a-f]{40}$ ]] \
    || ! [[ "${DEPLOY_REF}" =~ ^[A-Za-z0-9._/-]+$ ]] \
    || ! [[ "${REPOSITORY_URL}" =~ ^https://github\.com/[A-Za-z0-9._/-]+\.git$ ]] \
    || ! [[ "${RELEASE_ID}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}$ ]]; then
  echo "Invalid deployment identity." >&2
  exit 2
fi

for command in git curl nginx systemctl runuser stat readlink ln mv install cp; do
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
write_release_manifest "${RELEASE_DIR}" "${REVISION}" "${RELEASE_ID}"
# Freeze the completed checkout after dependency installation. The service can
# read and execute it through its group but can mutate only the separate data
# root allowed by systemd.
chown -R root:"${APP_GROUP}" "${RELEASE_DIR}"
chmod -R g+rX,go-w "${RELEASE_DIR}"
chmod 0755 "${RELEASE_DIR}"
FROZEN_REVISION="$(run_as_app git -c "safe.directory=${RELEASE_DIR}" -C "${RELEASE_DIR}" rev-parse --verify HEAD)"
FROZEN_DIRTY="$(run_as_app git -c "safe.directory=${RELEASE_DIR}" -C "${RELEASE_DIR}" status --porcelain --untracked-files=normal)"
RESOLVED_STUDIO_ROOT="$(
  run_as_app env \
    "SPECIALIST_MODEL_STUDIO_SOURCE_ROOT=${RELEASE_DIR}" \
    "${RELEASE_DIR}/.venv/bin/python" \
    -c 'from model_harness.cli import _resolve_studio_source_root; print(_resolve_studio_source_root())'
)"
if [[ "${FROZEN_REVISION}" != "${REVISION}" ]] \
    || [[ -n "${FROZEN_DIRTY}" ]] \
    || [[ "${RESOLVED_STUDIO_ROOT}" != "${RELEASE_DIR}" ]]; then
  echo "Frozen release identity or installed Studio launcher resolution is invalid." >&2
  exit 1
fi

HAD_CURRENT="false"
OLD_TARGET=""
if [[ -e "${CURRENT_LINK}" || -L "${CURRENT_LINK}" ]]; then
  HAD_CURRENT="true"
  if ! OLD_TARGET="$(resolve_safe_release_link "${CURRENT_LINK}")"; then
    echo "Refusing deployment: current does not resolve to a retained release in an approved root." >&2
    exit 1
  fi
fi

HAD_PREVIOUS="false"
OLD_PREVIOUS_TARGET=""
if [[ -e "${PREVIOUS_LINK}" || -L "${PREVIOUS_LINK}" ]]; then
  HAD_PREVIOUS="true"
  if ! OLD_PREVIOUS_TARGET="$(resolve_safe_release_link "${PREVIOUS_LINK}")"; then
    echo "Refusing deployment: previous does not resolve to a retained release in an approved root." >&2
    exit 1
  fi
fi

install -d -o root -g root -m 0700 "${CONFIG_BACKUP_DIR}"
HAD_SERVICE_FILE="false"
HAD_READINESS_FILE="false"
HAD_NGINX_FILE="false"
if backup_managed_file "${SERVICE_FILE}" "${CONFIG_BACKUP_DIR}/service"; then
  HAD_SERVICE_FILE="true"
elif [[ "$?" -ne 2 ]]; then
  exit 1
fi
if backup_managed_file "${LIBEXEC_DIR}/readiness.sh" "${CONFIG_BACKUP_DIR}/readiness"; then
  HAD_READINESS_FILE="true"
elif [[ "$?" -ne 2 ]]; then
  exit 1
fi
if backup_managed_file "${NGINX_FILE}" "${CONFIG_BACKUP_DIR}/nginx"; then
  HAD_NGINX_FILE="true"
elif [[ "$?" -ne 2 ]]; then
  exit 1
fi
install -o root -g root -m 0644 "${SCRIPT_DIR}/specialist-model-studio.service" "${SERVICE_FILE}"
install -o root -g root -m 0644 "${SCRIPT_DIR}/nginx-site.conf" "${NGINX_FILE}"
install -d -o root -g root -m 0755 "${LIBEXEC_DIR}"
install -o root -g root -m 0755 "${SCRIPT_DIR}/readiness.sh" "${LIBEXEC_DIR}/readiness.sh"
if ! nginx -t; then
  restore_installed_configuration || true
  echo "Nginx validation failed; the previous managed configuration was restored." >&2
  exit 1
fi

atomic_replace_release_link "${RELEASE_DIR}" "${CURRENT_LINK}" "next"

if ! activate_new_release; then
  echo "New release failed activation; restoring the complete previous deployment state." >&2
  systemctl stop specialist-model-studio.service || true
  if ! restore_current_after_failed_deploy "${OLD_TARGET}" "${HAD_CURRENT}" "${RELEASE_DIR}"; then
    echo "Failed to restore the current link safely; the service will remain stopped." >&2
    exit 1
  fi
  if ! restore_previous_after_failed_deploy; then
    echo "Failed to restore the previous link safely; the service will remain stopped." >&2
    exit 1
  fi
  if ! restore_installed_configuration; then
    echo "Failed to restore the managed configuration; the service will remain stopped." >&2
    exit 1
  fi
  if [[ "${HAD_CURRENT}" == "true" ]]; then
    systemctl reset-failed specialist-model-studio.service || true
    if ! systemctl restart specialist-model-studio.service \
        || ! run_readiness_for_release "${OLD_TARGET}" 120; then
      echo "The previous release was restored but failed its readiness check; the service will remain stopped." >&2
      systemctl stop specialist-model-studio.service || true
    fi
  else
    systemctl stop specialist-model-studio.service || true
  fi
  exit 1
fi

echo "release=${RELEASE_ID} revision=${REVISION} service=ready url=https://studio.learnbuddy.top/app"
