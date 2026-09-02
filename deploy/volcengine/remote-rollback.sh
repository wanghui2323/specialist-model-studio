#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "remote-rollback.sh must run as root" >&2
  exit 1
fi

TARGET_RELEASE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="/opt/specialist-model-studio"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
PREVIOUS_LINK="${APP_ROOT}/previous"

if [[ -n "${TARGET_RELEASE}" ]] && ! [[ "${TARGET_RELEASE}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}$ ]]; then
  echo "Invalid target release name." >&2
  exit 2
fi

OLD_TARGET="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
if [[ -n "${TARGET_RELEASE}" ]]; then
  TARGET="$(readlink -f "${RELEASES_DIR}/${TARGET_RELEASE}" 2>/dev/null || true)"
else
  TARGET="$(readlink -f "${PREVIOUS_LINK}" 2>/dev/null || true)"
fi

if [[ -z "${TARGET}" || ! -d "${TARGET}" || "${TARGET}" != "${RELEASES_DIR}/"* || "${TARGET}" == "${OLD_TARGET}" ]]; then
  echo "No distinct retained release is available for rollback." >&2
  exit 1
fi

ln -sfn "${TARGET}" "${CURRENT_LINK}.rollback"
mv -Tf "${CURRENT_LINK}.rollback" "${CURRENT_LINK}"

if ! systemctl restart specialist-model-studio.service \
    || ! "${SCRIPT_DIR}/readiness.sh" 180; then
  echo "Rollback target failed readiness; restoring the release active before this attempt." >&2
  if [[ -n "${OLD_TARGET}" && -d "${OLD_TARGET}" && "${OLD_TARGET}" == "${RELEASES_DIR}/"* ]]; then
    ln -sfn "${OLD_TARGET}" "${CURRENT_LINK}.restore"
    mv -Tf "${CURRENT_LINK}.restore" "${CURRENT_LINK}"
    systemctl restart specialist-model-studio.service || true
    "${SCRIPT_DIR}/readiness.sh" 120 || true
  fi
  exit 1
fi

if [[ -n "${OLD_TARGET}" && -d "${OLD_TARGET}" && "${OLD_TARGET}" == "${RELEASES_DIR}/"* ]]; then
  ln -sfn "${OLD_TARGET}" "${PREVIOUS_LINK}.next"
  mv -Tf "${PREVIOUS_LINK}.next" "${PREVIOUS_LINK}"
fi

echo "rollback_ready target=$(basename "${TARGET}") url=https://studio.learnbuddy.top/app"
