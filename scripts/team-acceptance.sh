#!/usr/bin/env bash
# Required acceptance runner once #1/#2/#3/#5 are integrated. Missing/skipped work blocks.
set -euo pipefail
base="${1:-http://localhost:8080}"
mkdir -p artifacts/acceptance
for file in business_test_fulfillment.py latency_benchmark.py resilience_checks.py; do
  test -f "scripts/acceptance/$file" || { echo "Missing acceptance component: $file" >&2; exit 1; }
done
python3 scripts/acceptance/business_test_fulfillment.py --base-url "$base" | tee artifacts/acceptance/business.log
python3 scripts/acceptance/latency_benchmark.py --base-url "$base" --out artifacts/acceptance/latency.json | tee artifacts/acceptance/latency.log
python3 scripts/check-panel-evidence.py artifacts/acceptance/latency.json
# exit 3 (SKIPPED) is a failure under set -e; the earlier team aggregate accepted it.
python3 scripts/acceptance/resilience_checks.py --base-url "$base" | tee artifacts/acceptance/resilience.log
