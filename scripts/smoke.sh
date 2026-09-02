#!/usr/bin/env bash
set -euo pipefail
base=${1:-http://localhost:8080}
echo '[1/6] console'
curl -fsS "$base/" | grep -q LOGISTPULSE
echo '[2/6] inventory'
curl -fsS "$base/api/inventory/STORE-042" | grep -q Pollo
echo '[3/6] distribution'
curl -fsS "$base/api/distribution/trucks" | grep -q TRUCK-017
echo '[4/6] operations'
for i in $(seq 1 20); do if curl -fsS "$base/api/operations/STORE-042/devices" | grep -q FREEZER; then break; fi; sleep 2; done
curl -fsS "$base/api/operations/STORE-042/devices" | grep -q FREEZER
echo '[5/6] order create'
curl -fsS -X POST -H 'Content-Type: application/json' -d '{"storeId":"STORE-042","channel":"CI","total":25.5}' "$base/api/fulfillment/orders" | grep -q ORD-
echo '[6/6] health'
for s in inventory logistics operations fulfillment; do curl -fsS "$base/health/$s" | grep -q UP; done
echo 'LOGISTPULSE smoke test OK'
