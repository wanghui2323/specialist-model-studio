#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-itutor}"
TARGET_RELEASE="${1:-}"

if [[ -n "${TARGET_RELEASE}" ]] && ! [[ "${TARGET_RELEASE}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}$ ]]; then
  echo "Target must be a release name such as 20260902T083000Z-11bda20." >&2
  exit 2
fi

STAGE_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
REMOTE_STAGE="/tmp/specialist-model-studio-rollback-${STAGE_ID}"
ssh "${DEPLOY_HOST}" "umask 077 && mkdir -- '${REMOTE_STAGE}'"
scp "${SCRIPT_DIR}/remote-rollback.sh" "${SCRIPT_DIR}/readiness.sh" "${DEPLOY_HOST}:${REMOTE_STAGE}/"
ssh -t "${DEPLOY_HOST}" \
  "sudo /bin/bash '${REMOTE_STAGE}/remote-rollback.sh' '${TARGET_RELEASE}'"
