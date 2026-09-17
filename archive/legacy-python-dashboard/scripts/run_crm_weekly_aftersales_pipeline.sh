#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_ROOT="${ECOM_DEPLOY_ROOT:-/Users/Shared/ecom-profit}"
WPS_AFTERSALES_RUN_ROOT="${WPS_AFTERSALES_RUN_ROOT:-${DEPLOY_ROOT}/projects/crm}"
LOG_ROOT="${WPS_AFTERSALES_LOG_ROOT:-${WPS_AFTERSALES_RUN_ROOT}/logs}"
LOCK_DIR="${LOG_ROOT}/wps_sales_stock_pipeline.lock"
WAIT_FOR_LOCK_SECONDS="${WAIT_FOR_LOCK_SECONDS:-3600}"
NOW_TAG="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_ROOT}/wps_weekly_aftersales_${NOW_TAG}.log"
RUN_RESULT_JSON="${LOG_ROOT}/wps_weekly_aftersales_${NOW_TAG}.json"
AFTERSALES_STATE_FILE="${WPS_WEEKLY_AFTERSALES_STATE_FILE:-${LOG_ROOT}/wps_weekly_aftersales_state.json}"
DINGTALK_NOTIFY_ENV_FILE="${DINGTALK_NOTIFY_ENV_FILE:-${DEPLOY_ROOT}/projects/shared-notify/config/dingtalk_notify.env}"
if [[ ! -f "${DINGTALK_NOTIFY_ENV_FILE}" ]]; then
  DINGTALK_NOTIFY_ENV_FILE="${DINGTALK_ENV_FILE:-${DEPLOY_ROOT}/projects/shared-notify/config/dingtalk.env}"
fi

mkdir -p "${LOG_ROOT}"

acquire_lock() {
  local waited=0
  while ! mkdir "${LOCK_DIR}" 2>/dev/null; do
    if [[ "${WAIT_FOR_LOCK_SECONDS}" -le 0 || "${waited}" -ge "${WAIT_FOR_LOCK_SECONDS}" ]]; then
      echo "销售库存/销售出库周覆盖任务正在运行中，售后周报本次未启动。锁：${LOCK_DIR}"
      return 1
    fi
    echo "销售库存/销售出库周覆盖任务正在运行中，售后周报等待 30 秒后重试。已等待 ${waited}s"
    sleep 30
    waited=$((waited + 30))
  done
}

if ! acquire_lock; then
  exit 1
fi

cleanup() {
  rm -rf "${LOCK_DIR}"
}
trap cleanup EXIT

cd "${PROJECT_ROOT}" || exit 1
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "WPS 售后经营异常周报自动化"
echo "=========================="
echo "Project: ${PROJECT_ROOT}"
echo "Log: ${LOG_FILE}"
echo "Start: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Lock: ${LOCK_DIR}"
echo

notify_pipeline() {
  local status="$1"
  local message="$2"
  local notifier="${PROJECT_ROOT}/tools/dingtalk_pipeline_notify.py"
  local python_bin="${PYTHON_BIN:-python3}"
  if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    python_bin="${PROJECT_ROOT}/.venv/bin/python"
  fi
  if [[ -f "${notifier}" ]]; then
    "${python_bin}" "${notifier}" \
      --env-file "${DINGTALK_NOTIFY_ENV_FILE}" \
      --state-file "${AFTERSALES_STATE_FILE}" \
      --status "${status}" \
      --title "售后经营异常周报" \
      --message "${message}" \
      --log-file "${LOG_FILE}" || true
  fi
}

send_dashboard_to_dingtalk() {
  local message="$1"
  local sender="${PROJECT_ROOT}/tools/dingtalk_send_dashboard_file.py"
  local python_bin="${PYTHON_BIN:-python3}"
  if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    python_bin="${PROJECT_ROOT}/.venv/bin/python"
  fi
  if [[ -f "${sender}" ]]; then
    "${python_bin}" "${sender}" \
      --env-file "${DINGTALK_NOTIFY_ENV_FILE}" \
      --state-file "${AFTERSALES_STATE_FILE}" \
      --title "售后经营异常周报看板" \
      --message "${message}" || true
  fi
}

run_step() {
  local title="$1"
  shift
  echo
  echo ">>> ${title}"
  "$@"
  local rc=$?
  if [[ ${rc} -ne 0 ]]; then
    echo
    echo "FAILED: ${title}，退出码 ${rc}"
    notify_pipeline "failed" "售后经营异常周报失败环节：${title}；退出码：${rc}。"
    exit "${rc}"
  fi
}

run_json_step() {
  local title="$1"
  local json_file="$2"
  shift 2
  echo
  echo ">>> ${title}"
  "$@" | tee "${json_file}"
  local rc=${PIPESTATUS[0]}
  if [[ ${rc} -ne 0 ]]; then
    echo
    echo "FAILED: ${title}，退出码 ${rc}"
    notify_pipeline "failed" "售后经营异常周报失败环节：${title}；退出码：${rc}。"
    exit "${rc}"
  fi
}

build_success_notify_message() {
  local python_bin="${PYTHON_BIN:-python3}"
  if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    python_bin="${PROJECT_ROOT}/.venv/bin/python"
  fi
  "${python_bin}" - "${RUN_RESULT_JSON}" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
except Exception:
    data = {}
msg = data.get('message') or '售后经营异常周报任务已完成。'
if '没有发现新的售后明细' in msg or '没有可处理' in msg:
    print(json.dumps({'notify': False, 'message': msg}, ensure_ascii=False))
else:
    start = data.get('window_start') or '-'
    end = data.get('window_end') or '-'
    files = []
    if data.get('xlsx'):
        files.append('Excel 周报')
    if data.get('html'):
        files.append('HTML 看板')
    print(json.dumps({'notify': True, 'message': f'售后经营异常周报已完成，统计付款时间 {start} 到 {end}；已生成并上传：' + '、'.join(files or ['结果文件']) + '。'}, ensure_ascii=False))
PY
}

run_step "检查 WPS / kdocs / 文件夹配置" \
  bash scripts/run_crm_weekly_aftersales_sync.sh doctor

run_json_step "下载班牛售后明细，生成周报和看板，并上传到 WPS" "${RUN_RESULT_JSON}" \
  bash scripts/run_crm_weekly_aftersales_sync.sh --json weekly-run

run_step "展示当前售后周报结果状态" \
  bash scripts/run_crm_weekly_aftersales_sync.sh --json pending-results

echo
echo "Done: $(date '+%Y-%m-%d %H:%M:%S')"
echo "本次日志：${LOG_FILE}"
notify_payload="$(build_success_notify_message)"
should_notify="$(printf '%s' "${notify_payload}" | "${PYTHON_BIN:-python3}" -c 'import json,sys; print(json.load(sys.stdin).get("notify"))' 2>/dev/null || echo False)"
notify_message="$(printf '%s' "${notify_payload}" | "${PYTHON_BIN:-python3}" -c 'import json,sys; print(json.load(sys.stdin).get("message", ""))' 2>/dev/null || true)"
if [[ "${should_notify}" == "True" ]]; then
  notify_pipeline "success" "${notify_message}"
  send_dashboard_to_dingtalk "${notify_message}"
else
  echo "${notify_message}"
  echo "本次没有新售后明细，跳过钉钉完成通知。"
fi
