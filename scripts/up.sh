#!/usr/bin/env bash
set -euo pipefail
docker compose up -d --build --wait --wait-timeout 240
python3 scripts/wait-ready.py
docker compose ps
