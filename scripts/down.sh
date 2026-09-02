#!/usr/bin/env bash
set -euo pipefail
docker compose -f observability/compose.yaml down 2>/dev/null || true
docker compose down
