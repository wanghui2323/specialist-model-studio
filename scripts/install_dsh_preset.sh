#!/usr/bin/env bash
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRESET_SOURCE="${HARNESS_ROOT}/integrations/deepseek-harness/presets/model-training"
DSH_ROOT="${DSH_HOME:-$(cd && pwd)/.dsh}"
PRESET_PARENT="${DSH_ROOT}/.agent-presets"
PRESET_TARGET="${PRESET_PARENT}/model-training"
MANAGED_MARKER="${PRESET_TARGET}/.managed-by-specialist-model-studio"
LEGACY_MANAGED_MARKER="${PRESET_TARGET}/.managed-by-ai-pm-model-harness"

if [[ -e "${PRESET_TARGET}" && ! -f "${MANAGED_MARKER}" && ! -f "${LEGACY_MANAGED_MARKER}" ]]; then
  echo "Refusing to overwrite unmanaged DSH preset: ${PRESET_TARGET}" >&2
  exit 1
fi

mkdir -p "${PRESET_TARGET}"
cp "${PRESET_SOURCE}/agent.cordis.yml" "${PRESET_TARGET}/agent.cordis.yml"
cp "${PRESET_SOURCE}/preset.yml" "${PRESET_TARGET}/preset.yml"
cp "${PRESET_SOURCE}/.managed-by-specialist-model-studio" "${MANAGED_MARKER}"
chmod 700 "${PRESET_PARENT}" "${PRESET_TARGET}"
chmod 600 "${PRESET_TARGET}/agent.cordis.yml" "${PRESET_TARGET}/preset.yml" "${MANAGED_MARKER}"

echo "Installed DSH preset: ${PRESET_TARGET}"
