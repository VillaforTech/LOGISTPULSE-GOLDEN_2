#!/usr/bin/env bash
set -euo pipefail

base=${1:-http://localhost:8080}
max_wait=${BUSINESS_TEST_MAX_WAIT_SECONDS:-20}
order_json=$(curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -d '{"storeId":"STORE-042","channel":"BUSINESS-TEST","total":25.5}' \
  "$base/api/fulfillment/orders")
order_id=$(printf '%s' "$order_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["orderId"])')
created_at=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["createdAt"])' <<<"$(curl -fsS "$base/api/fulfillment/orders/$order_id")")
deadline=$(python3 -c "print(float('$created_at') + 15)")
started=$(date +%s)

while true; do
  order=$(curl -fsS "$base/api/fulfillment/orders/$order_id")
  status=$(printf '%s' "$order" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  ready_at=$(printf '%s' "$order" | python3 -c 'import json,sys; value=json.load(sys.stdin).get("readyAt"); print("" if value is None else value)')
  if [[ "$status" == "READY" && -n "$ready_at" ]]; then
    python3 -c "import sys; sys.exit(0 if float('$ready_at') <= float('$deadline') else 1)" || {
      echo "BUSINESS TEST FAILED: $order_id became READY after its deadline" >&2
      exit 2
    }
    echo "BUSINESS TEST OK: $order_id READY at $ready_at (deadline $deadline)"
    exit 0
  fi
  if (( $(date +%s) - started >= max_wait )); then
    echo "BUSINESS TEST FAILED: $order_id remained $status without persistent readyAt" >&2
    exit 3
  fi
  sleep 0.25
done
