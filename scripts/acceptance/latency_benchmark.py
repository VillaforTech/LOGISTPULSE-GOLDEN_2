#!/usr/bin/env python3
"""Wrapper delgado del benchmark de latencia de creacion -> panel (issue #5).

QUE EJECUTA ESTE SCRIPT
------------------------
Este archivo YA NO mide nada por si mismo. Es un wrapper delgado que
delega toda la medicion real en `panel-benchmark.cjs` (Node + Playwright,
Chromium real), exactamente como se resolvio el mismo problema en
BANKPULSE (`scripts/acceptance/latency_benchmark.py` +
`panel-benchmark.cjs` de ese repo, ya aceptado y fusionado a main).

Se mantiene como wrapper Python (en vez de invocar el .cjs directamente
desde `scripts/team-acceptance.sh`) para no tocar ese runner: expone
exactamente la misma interfaz de linea de comandos que ya usa
`scripts/team-acceptance.sh`:

    python3 scripts/acceptance/latency_benchmark.py --base-url "$base" \
        --out artifacts/acceptance/latency.json

QUE EXIGE EL VALIDADOR (scripts/check-panel-evidence.py)
---------------------------------------------------------
El JSON escrito en `--out` es verificado por `scripts/check-panel-evidence.py`,
que ya esta en main y es un contrato duro. Exige, entre otras cosas:
  - `measurementTarget == "grafana-render"` (medicion real de panel, no de
    la API).
  - Ausencia (o `false`) de `coberturaParcial` / `coberturaParcialPanelPendiente`.
  - `requested == observed == len(samples) == 100`, `lost == 0`, `errors`
    vacio.
  - 100 `correlationId` unicos entre las muestras.
  - Cada muestra con `correlationId`, `rendered=True`, `correct=True`,
    `quality=="FRESH"`, `revision>0` y `latencyMs` finito y `>=0`.
  - `p95Ms == sorted(latencias)[94]`, `p95Ms <= 1000` y coincidente con el
    p95 calculado a partir de las muestras (tolerancia 0.001).

Ese esquema solo puede satisfacerse con una medicion real contra el panel
de Grafana (Grafana Live + el panel plugin de negocio), nunca con datos
sinteticos ni con una medicion que solo llegue hasta la API.

DE QUE DEPENDE (Y POR QUE HOY FALLA A PROPOSITO)
--------------------------------------------------
`panel-benchmark.cjs` necesita el adaptador de Grafana Live (issue #3:
`services/grafana-live-adapter`, que empuja snapshots de negocio del
servicio de analitica del issue #2 hacia Grafana Live) y el panel de
negocio provisionado en el dashboard. NINGUNO de los dos existe todavia
en esta rama:
  - El issue #3 no ha entregado `services/grafana-live-adapter`.
  - El servicio de analitica del issue #2
    (`services/business-analytics`) vive sin fusionar en
    `feat/2-business-analytics`.

Por lo tanto, hoy `panel-benchmark.cjs` DETECTA en tiempo de ejecucion
que el panel/adaptador no esta disponible, imprime un mensaje claro en
espanol explicando esa dependencia y termina con codigo de salida 3
(distinto de 0; bajo `set -euo pipefail` en `scripts/team-acceptance.sh`
esto detiene la corrida, igual que un SKIPPED en
`scripts/acceptance/resilience_checks.py`). Esta PROHIBIDO que este
wrapper, o el .cjs que invoca, produzcan un `latency.json` con datos
sinteticos/simulados, marquen `measurementTarget="grafana-render"` sin
un render real, rellenen muestras para llegar a 100, o retornen 0 sin
haber medido nada real. Cuando el issue #3 fusione el adaptador (y el
#2 este integrado), `panel-benchmark.cjs` debe funcionar sin cambios en
este wrapper -- ver los TODO en ese archivo para los ajustes finos
(uid del dashboard, nombre del datasource/canal Live, selector del
panel).

Uso:
  python3 scripts/acceptance/latency_benchmark.py --base-url http://localhost:8080 \
      --out artifacts/acceptance/latency.json

Codigos de salida (propagados tal cual desde panel-benchmark.cjs):
  0 = 100 muestras reales de render de panel, todas correctas y frescas,
      con p95 <= 1000ms (lo que exige scripts/check-panel-evidence.py).
  2 = error de entorno inesperado (p.ej. Playwright no instalado).
  3 = SKIPPED honesto: el panel/adaptador de Grafana Live (issue #3) no
      esta disponible todavia. NO es un PASS.
  otro != 0 = la medicion real se ejecuto pero no paso el criterio
      (perdidas, errores, p95 > 1000ms, etc.).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080", help="Base del edge (default: %(default)s)")
    parser.add_argument("--out", default="artifacts/acceptance/latency.json", help="ruta de salida del JSON de evidencia de panel")
    args = parser.parse_args()

    script = Path(__file__).with_name("panel-benchmark.cjs")
    sys.exit(subprocess.call(["node", str(script), args.base_url, args.out]))
