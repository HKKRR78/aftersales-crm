#!/usr/bin/env bash
set -euo pipefail
export TZ=Asia/Shanghai
DEPLOY_ROOT="${ECOM_DEPLOY_ROOT:-/Users/Shared/ecom-profit}"
PROJECT_ROOT="${ECOM_PROJECT_ROOT:-${DEPLOY_ROOT}/projects/crm}"
PYTHON_BIN="${PYTHON_BIN:-${DEPLOY_ROOT}/projects/ecom-profit-app/.venv/bin/python}"
ENV_FILE="${CRM_AFTERSALES_ENV_FILE:-${PROJECT_ROOT}/config/crm_ticket_sync.env}"
LOCK_DIR="${PROJECT_ROOT}/run/crm-aftersales-daily.lock"
mkdir -p "${PROJECT_ROOT}/logs" "${PROJECT_ROOT}/run" "${PROJECT_ROOT}/evidence"
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "售后报告任务已有实例运行" >&2
  exit 75
fi
trap 'rmdir "${LOCK_DIR}"' EXIT
cd "${PROJECT_ROOT}"
set -a
. "${ENV_FILE}"
set +a
report_end="$(date +%F)"
report_start="$("${PYTHON_BIN}" -c 'from datetime import date;import sys;sys.path.insert(0,"scripts");from crm_report_scope import recent_release_scope;print(recent_release_scope(date.fromisoformat(sys.argv[1]))["requiredStart"])' "${report_end}")"
# Re-read the complete rolling issue scope because the source has no reliable
# update/delete feed for migrated tickets. Weekly stable segments make a late
# edit recoverable without treating an earlier successful read as current.
"${PYTHON_BIN}" scripts/crm_ticket_sync.py --start-date "${report_start}" --end-date "${report_end}" --page-size 200 --delay 7
export PDD_PROJECT_ROOT="${DEPLOY_ROOT}/projects/pinduoduo-data-collection"
# Refresh every referenced historical original proof before building; a
# previous report is not the input scope for today's reconciliation.
"${PYTHON_BIN}" scripts/crm_original_order_read.py --end "${report_end}" \
  --artifacts "${PROJECT_ROOT}/evidence/original-orders" \
  --company-source-root "${DEPLOY_ROOT}/projects/ecom-profit-app"
result_file="${LOCK_DIR}/result.json"
# Remove the result before releasing the lock, including on a failed build.
trap 'rm -f "${result_file}"; rmdir "${LOCK_DIR}"' EXIT
"${PYTHON_BIN}" scripts/crm_report_build.py --end "${report_end}" --artifacts "${PROJECT_ROOT}/evidence" --result-file "${result_file}"
batch_id="$("${PYTHON_BIN}" -c 'import json,sys;print(json.load(open(sys.argv[1]))["batch_id"])' "${result_file}")"
"${PYTHON_BIN}" scripts/crm_frozen_product_sales.py --batch "${batch_id}" \
  --frozen-through "${CRM_FROZEN_SALES_THROUGH:-2026-09-12}" \
  --artifacts "${PROJECT_ROOT}/evidence/frozen-sales"
"${PYTHON_BIN}" scripts/crm_product_denominators.py --batch "${batch_id}" --artifacts "${PROJECT_ROOT}/evidence/sales-facts"
"${PYTHON_BIN}" scripts/crm_report_publish.py verify --batch "${batch_id}" --verification-kind issues_full_denominators_partial
previous_batch="$("${PYTHON_BIN}" -c 'import sys;sys.path.insert(0,"scripts");from crm_schema import connect_mysql;c=connect_mysql();q=c.cursor();q.execute("SELECT batch_id FROM crm_report_current WHERE singleton=1");r=q.fetchone();print(r[0] if r else "");c.close()')"
"${PYTHON_BIN}" scripts/crm_report_publish.py select --batch "${batch_id}" --expected-current "${previous_batch}"
