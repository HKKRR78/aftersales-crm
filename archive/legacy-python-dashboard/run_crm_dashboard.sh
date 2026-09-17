#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${ECOM_DEPLOY_ROOT:-/Users/Shared/ecom-profit}"
PROJECT_ROOT="${ECOM_PROJECT_ROOT:-${DEPLOY_ROOT}/projects/crm}"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

export ECOM_DEPLOY_ROOT="${DEPLOY_ROOT}"
export ECOM_PROJECT_ROOT="${PROJECT_ROOT}"
export CRM_HOST="${CRM_HOST:-0.0.0.0}"
export CRM_PORT="${CRM_PORT:-8088}"
export CRM_RUNTIME_ROOT="${CRM_RUNTIME_ROOT:-${DEPLOY_ROOT}/projects/crm/runtime/crm_dashboard}"

cd "${PROJECT_ROOT}"
exec "${PYTHON_BIN}" "${PROJECT_ROOT}/crm_server.py"
