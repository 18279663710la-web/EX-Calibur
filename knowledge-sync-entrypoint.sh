#!/bin/sh
set -eu

log() {
  printf '[knowledge-sync] %s\n' "$*"
}

run_sync_once() {
  if [ -z "${DIFY_DATASET_API_KEY:-}" ] || [ -z "${DIFY_DATASET_ID:-}" ]; then
    log "Knowledge sync is not configured: set DIFY_DATASET_API_KEY and DIFY_DATASET_ID to enable uploads."
    return 0
  fi

  log "sync start: source=${LOCAL_FILE_DIR:-/app/knowledge}, dataset=${DIFY_DATASET_ID}"
  python sync_script.py \
    --source-dir "${LOCAL_FILE_DIR:-/app/knowledge}" \
    --ledger "${SYNC_LEDGER_PATH:-/app/state/sync_ledger.json}" \
    --base-url "${DIFY_BASE_URL:-http://host.docker.internal/v1}" \
    --dataset-id "${DIFY_DATASET_ID}" \
    --pipeline "${RAG_SYNC_PIPELINE:-direct}" \
    --archive-dir "${STRUCTURED_MARKDOWN_DIR:-/app/structured_markdown}" || {
      code="$?"
      log "sync failed with exit code ${code}"
      return "$code"
    }
  log "sync complete"
}

if [ "${SYNC_RUN_ON_START:-true}" = "true" ]; then
  run_sync_once || true
fi

if [ "${SYNC_ONCE:-false}" = "true" ]; then
  exit 0
fi

while true; do
  sleep "${SYNC_INTERVAL_SECONDS:-60}"
  run_sync_once || true
done
