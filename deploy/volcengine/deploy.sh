#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-itutor}"
DEPLOY_REPOSITORY_URL="${DEPLOY_REPOSITORY_URL:-https://github.com/wanghui2323/specialist-model-studio.git}"

cd "${REPOSITORY_ROOT}"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Refusing deployment: tracked source changes are not committed." >&2
  exit 1
fi

REVISION="${1:-$(git rev-parse HEAD)}"
if ! [[ "${REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Revision must be a full 40-character lowercase Git SHA." >&2
  exit 2
fi

DEPLOY_REF="${DEPLOY_REF:-$(git branch --show-current)}"
if [[ -z "${DEPLOY_REF}" ]] || ! [[ "${DEPLOY_REF}" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "DEPLOY_REF must name a safe remote branch or tag." >&2
  exit 2
fi

REMOTE_TIP="$(git ls-remote "${DEPLOY_REPOSITORY_URL}" "refs/heads/${DEPLOY_REF}" "refs/tags/${DEPLOY_REF}" | awk 'NR == 1 {print $1}')"
if [[ "${REMOTE_TIP}" != "${REVISION}" ]]; then
  echo "Refusing deployment: ${REVISION} is not the published tip of ${DEPLOY_REF}." >&2
  exit 1
fi

SHORT_REVISION="${REVISION:0:7}"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-${SHORT_REVISION}"
REMOTE_STAGE="/tmp/specialist-model-studio-deploy-${RELEASE_ID}"

echo "Preparing non-secret deployment helpers on ${DEPLOY_HOST}:${REMOTE_STAGE}"
ssh "${DEPLOY_HOST}" "umask 077 && mkdir -- '${REMOTE_STAGE}'"
scp \
  "${SCRIPT_DIR}/remote-deploy.sh" \
  "${SCRIPT_DIR}/readiness.sh" \
  "${SCRIPT_DIR}/specialist-model-studio.service" \
  "${SCRIPT_DIR}/nginx-site.conf" \
  "${DEPLOY_HOST}:${REMOTE_STAGE}/"

echo "Deploying published revision ${REVISION} as ${RELEASE_ID}"
ssh -t "${DEPLOY_HOST}" \
  "sudo /bin/bash '${REMOTE_STAGE}/remote-deploy.sh' '${REVISION}' '${DEPLOY_REF}' '${DEPLOY_REPOSITORY_URL}' '${RELEASE_ID}'"

echo "Deployment accepted: https://studio.learnbuddy.top/app"
