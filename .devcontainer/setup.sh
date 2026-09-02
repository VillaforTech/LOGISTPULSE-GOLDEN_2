#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ ! -f .env ]; then cp .env.example .env; fi
printf '[LOGISTPULSE] Environment ready. Validate with: docker compose config --services
'
