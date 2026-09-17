#!/usr/bin/env bash
# Wrapper delgado: delega TODA la evidencia de aceptacion del issue #5 en
# el runner oficial (scripts/team-acceptance.sh), que corre con
# `set -euo pipefail`. Este script ya NO reimplementa un gate agregado
# propio: cualquier exit distinto de 0 en cualquier etapa (incluido un
# SKIPPED/exit 3) propaga como fallo, sin la posibilidad de agregar un
# PASS cuando alguna etapa quedo SKIPPED.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec bash scripts/team-acceptance.sh "${LOGISTPULSE_URL:-http://localhost:8080}"
