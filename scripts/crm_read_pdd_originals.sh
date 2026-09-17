#!/bin/zsh
# Reuse the official company exporter and its platform lock. Preserve original
# files and validation evidence; never invoke ingestion with --apply or cleanup.
set -euo pipefail
if [[ $# -ne 4 ]]; then
  print -u2 -- 'usage: crm_read_pdd_originals.sh START END PDD_PROJECT ARTIFACT_DIRECTORY'
  exit 2
fi
start_date="$1"
end_date="$2"
PDD_RUN_ROOT="$3"
artifact_directory="$4"
PYTHON_BIN="/Users/Shared/ecom-profit/projects/ecom-profit-app/.venv/bin/python"
NODE_BIN="/Users/yyerybz/.local/bin/node"
if [[ -e "$artifact_directory" ]]; then
  print -u2 -- 'Artifact directory already exists; choose a new path to preserve earlier evidence.'
  exit 2
fi
mkdir -p "$artifact_directory"
chmod 700 "$artifact_directory"
source "$PDD_RUN_ROOT/config/pdd.env"
source "$PDD_RUN_ROOT/scripts/pdd_batch_common.sh"
pdd_lock_acquire "crm-original-orders-$start_date-$end_date"
trap 'pdd_lock_release' EXIT
"$PDD_RUN_ROOT/scripts/start_pdd_debug_chrome_macmini.sh"
export PDD_ORDER_START="$start_date" PDD_ORDER_END="$end_date"
export PDD_ORDER_ACCOUNT_DOWNLOAD_DIR="$artifact_directory/raw"
export PDD_ORDER_ACCOUNT_IGNORE_EXISTING_TASKS=1
export PDD_START_INDEX=1 PDD_END_INDEX=19
export PDD_SHOP_ID_MAP="$artifact_directory/shop-identity.json"
export PDD_SHOP_ID_AUDIT_DIR="$artifact_directory/shop-identity-evidence"
export PDD_FAILED_INDEX_FILE="$artifact_directory/failed-shops.txt"
export PDD_NO_DATA_FILE="$artifact_directory/confirmed-empty-shops.txt"
cp "$PDD_RUN_ROOT/config/pdd_shop_ids.json" "$PDD_SHOP_ID_MAP"
if [[ -e "$PDD_FAILED_INDEX_FILE" ]]; then
  print -u2 -- 'Previous run evidence exists; choose a new artifact directory.'
  exit 2
fi
"$NODE_BIN" "$PDD_RUN_ROOT/scripts/pdd_order_custom_export_chrome_cdp.mjs" \
  > "$artifact_directory/export.log" 2>&1
if [[ -s "$PDD_FAILED_INDEX_FILE" ]]; then
  print -u2 -- "Original export incomplete. Evidence: $artifact_directory/export.log"
  exit 1
fi
"$PYTHON_BIN" "$PDD_RUN_ROOT/scripts/pdd_order_report_ingest.py" \
  --report-type custom --source-dir "$artifact_directory/raw" \
  --run-log "$artifact_directory/export.log" --start "$start_date" --end "$end_date" \
  --output "$artifact_directory/validation.json" > "$artifact_directory/validation.log" 2>&1
print -- "Original exports and validation retained at $artifact_directory; no formal data changed."
