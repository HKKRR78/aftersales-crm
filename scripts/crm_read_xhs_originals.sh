#!/bin/zsh
# Reuse the company order API collector with its shared platform lock.
# This command reads and preserves original exports; it never loads ODS.
set -euo pipefail
if [[ $# -ne 4 ]]; then
  print -u2 -- 'usage: crm_read_xhs_originals.sh START END COMPANY_PROJECT ARTIFACT_DIRECTORY'
  exit 2
fi
start_date="$1" end_date="$2" company_project="$3" artifact_directory="$4"
lock_directory="/Users/Shared/ecom-profit/runtime/locks/xiaohongshu-global.lock"
if [[ -e "$artifact_directory" ]]; then
  print -u2 -- 'Artifact directory already exists; choose a new path to preserve earlier evidence.'
  exit 2
fi
mkdir -p "$artifact_directory" "${lock_directory:h}"
chmod 700 "$artifact_directory"
if ! mkdir "$lock_directory" 2>/dev/null; then
  owner_pid=""
  [[ -f "$lock_directory/owner_pid" ]] && owner_pid="$(<"$lock_directory/owner_pid")"
  if [[ -n "$owner_pid" ]] && kill -0 "$owner_pid" 2>/dev/null; then
    print -u2 -- "Xiaohongshu source task already running: $owner_pid"
    exit 75
  fi
  [[ -f "$lock_directory/owner_pid" ]] && rm "$lock_directory/owner_pid"
  rmdir "$lock_directory"
  mkdir "$lock_directory"
fi
print -- "$$" > "$lock_directory/owner_pid"
cleanup() {
  if [[ "$(<"$lock_directory/owner_pid")" == "$$" ]]; then
    rm "$lock_directory/owner_pid"
    rmdir "$lock_directory"
  fi
}
trap cleanup EXIT
export PYTHON_BIN="$company_project/.venv/bin/python"
read -r XHS_START_MS XHS_END_MS <<EOF
$("$PYTHON_BIN" - "$start_date" "$end_date" <<'PY'
from datetime import datetime,time,timedelta,timezone
import sys
zone=timezone(timedelta(hours=8))
start=datetime.fromisoformat(sys.argv[1]).replace(tzinfo=zone)
end=datetime.fromisoformat(sys.argv[2]).replace(tzinfo=zone)+timedelta(days=1)
if start>=end:raise ValueError('invalid original order interval')
print(int(start.timestamp()*1000),int(end.timestamp()*1000)-1)
PY
)
EOF
export XHS_START_MS XHS_END_MS XHS_CDP_PORT=9888
export XHS_STABLE_SELLER_ID=6737fc482ab06500156a6fc5
export XHS_OUTPUT_DIR="$artifact_directory" XHS_FILE_LABEL="${start_date//-/}-${end_date//-/}"
"$company_project/scripts/start_xiaohongshu_debug_chrome_macmini.sh"
"/Users/Shared/ecom-profit/runtime/node/bin/node" \
  "$company_project/scripts/xiaohongshu_order_api_collect_cdp.mjs" \
  > "$artifact_directory/export.log" 2>&1
print -- "Original API evidence retained at $artifact_directory; no formal data changed."
