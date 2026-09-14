# Deber 01 — El falso verde (LOGISTPULSE)

**Repositorio:** LOGISTPULSE-GOLDEN_2
**Issue:** [#5](https://github.com/VillaforTech/LOGISTPULSE-GOLDEN_2/issues/5) — Pruebas de extremo a extremo, resiliencia y evidencia del falso verde
**Autor:** Daniel (`@Dmt-155lbs`)
**Rama de evidencia:** `feat/5-deber-01-harness`

> **Nota de estado.** Este documento se redacta con el harness de pruebas ya escrito (`scripts/acceptance/`, `tests/kpis/`, `fixtures/`) pero **antes** de ejecutarlo contra un despliegue real y **antes** de que existan PR, corridas de CI o capturas del proyecto. Toda sección o celda marcada `PENDIENTE` describe un resultado **esperado/diseñado**, no uno **observado**. Ninguna cifra de latencia, ningún SHA de commit, ninguna URL de PR ni ningún run id de GitHub Actions mostrados aquí son inventados: donde el dato todavía no existe, se deja `PENDIENTE` explícitamente para que Daniel lo complete con evidencia real.

## Tabla de contenidos

1. [Capacidad de negocio seleccionada](#1-capacidad-de-negocio-seleccionada)
2. [Escenario de falso verde](#2-escenario-de-falso-verde)
3. [Riesgo / pérdida potencial](#3-riesgo--pérdida-potencial)
4. [KPIs propios](#4-kpis-propios)
5. [Arquitectura y semántica temporal](#5-arquitectura-y-semántica-temporal)
6. [Diagrama del Release Gate](#6-diagrama-del-release-gate)
7. [Evidencia: PR sano (verde)](#7-evidencia-pr-sano-verde)
8. [Evidencia: PR con tecnología verde y negocio rojo](#8-evidencia-pr-con-tecnología-verde-y-negocio-rojo)
9. [Evidencia del bloqueo efectivo del merge](#9-evidencia-del-bloqueo-efectivo-del-merge)
10. [Diagnóstico y corrección](#10-diagnóstico-y-corrección)
11. [Ejecución final verde](#11-ejecución-final-verde)
12. [Cómo reproducir desde un Codespace limpio](#12-cómo-reproducir-desde-un-codespace-limpio)
13. [Tabla de contribuciones del equipo](#13-tabla-de-contribuciones-del-equipo)
14. [Checklist de la rúbrica 3+5+2](#14-checklist-de-la-rúbrica-352)
15. [Límites del benchmark de laboratorio](#15-límites-del-benchmark-de-laboratorio)

---

## 1. Capacidad de negocio seleccionada

**Capacidad protegida:** *todo pedido aceptado debe alcanzar el estado `READY` dentro del plazo prometido.*

En LOGISTPULSE, `services/fulfillment-api` acepta un pedido (`POST /api/fulfillment/orders`) y lo inserta en estado `WAITING`. `services/fulfillment-worker` consume el evento del topic legado `logistpulse.orders` y ejecuta la transición `WAITING -> PREPARING -> (duerme 4 s) -> READY`. El plazo de negocio del laboratorio es:

```
deadline = createdAt + 15 s
```

Cualquier pedido aceptado que a partir de ese instante siga en `WAITING` o `PREPARING` viola la capacidad protegida, sin importar que la infraestructura esté sana.

## 2. Escenario de falso verde

Un **falso verde** ocurre cuando toda la señal técnica dice "todo bien" mientras el negocio está incumpliendo su promesa:

- `GET /health/inventory`, `/health/logistics`, `/health/operations`, `/health/fulfillment` responden `200 {"status":"UP"}`.
- `docker compose ps` muestra todos los contenedores arriba.
- El pedido fue aceptado con HTTP 201 y tiene un `orderId` válido.
- **Pero** el pedido sigue en `WAITING` o `PREPARING` más allá de `createdAt + 15s`.

Este es exactamente el defecto que `scripts/acceptance/business_test_fulfillment.py` está diseñado para detectar: crea un pedido identificable, espera su plazo de negocio y falla (`exit 1`) si no llegó a `READY` a tiempo — sin importar que toda la infraestructura reporte `UP`.

**Caso de aceptación fijado por el issue #5** (documentado también en `fixtures/logistpulse/pedido-vencido-25-50.json`):

> Un pedido de `total = 25.5` (unidad monetaria de laboratorio) sigue abierto (`WAITING`) a los 20 s de creado. El plazo (15 s) venció 5 s antes de esta observación.

## 3. Riesgo / pérdida potencial

Los montos siguientes están expresados en **unidades monetarias de laboratorio** (datos demo generados para el ejercicio). No representan USD, no representan ingresos perdidos ni una pérdida financiera demostrada; son una unidad de laboratorio que cuantifica el tamaño del incumplimiento de negocio para poder compararlo entre corridas.

Para el caso de aceptación (pedido `total = 25.5`, todavía abierto a los 20 s):

| Magnitud | Valor | Unidad |
|---|---:|---|
| Compromisos de preparación incumplidos (L-K1) | 100 | % de la cohorte elegible |
| Valor comprometido en pedidos vencidos (L-K2) | 25.5 | unidades monetarias demo |
| Deuda acumulada de preparación (L-K3) | 5 | pedido-segundos |

## 4. KPIs propios

Los KPIs son funciones puras implementadas en `tests/kpis/logist_kpis.py` (sin red, sin base de datos; reciben la lista de pedidos y el instante `ahora` inyectado) y verificadas con `tests/kpis/test_logist_kpis.py`.

| KPI | Nombre | Fórmula | Población | Ventana | Umbral |
|---|---|---|---|---|---|
| **L-K1** | Compromisos de preparación incumplidos | `100 * incumplidos_con_plazo_vencido / elegibles_con_plazo_vencido` | Pedidos con `createdAt` dentro de la ventana de cohorte cuyo plazo (`createdAt + 15s`) ya venció | 900 s (15 min) de cohorte, evaluados sobre `ahora` | **0 %** — sin elegibles se reporta `"SIN MUESTRA"`, nunca `0.0` ni `100.0` |
| **L-K2** | Valor comprometido en pedidos vencidos | `Σ total` de pedidos `WAITING`/`PREPARING` con plazo vencido | Backlog completo (todos los pedidos abiertos y vencidos, sin ventana) | Foto del instante `ahora` | **0 unidades monetarias demo** |
| **L-K3** | Deuda acumulada de preparación | `Σ max(0, ahora - createdAt - 15s)` sobre pedidos `WAITING`/`PREPARING` | Backlog completo (sin ventana) | Foto del instante `ahora` | **0 pedido-segundos** |

Reglas de diseño verificadas en el código:

- `L-K1` nunca reporta `0.0` ni `100.0` cuando no hay elegibles: devuelve el literal `"SIN MUESTRA"` (`calcular_l_k1`, `logist_kpis.py`).
- `L-K2` usa `Decimal` (nunca `float`) para evitar el error binario de redondeo al sumar montos de laboratorio.
- Un pedido que llegó a `READY` tarde (fuera del plazo) sigue contando como incumplido en `L-K1` mientras pertenezca a la cohorte — no se "perdona" por haber cerrado eventualmente.
- `readyAt` es un campo futuro (issue #1); hoy el sistema real no lo expone, así que `_ready_at()` usa `updatedAt` como aproximación solo cuando `status == "READY"`.

## 5. Arquitectura y semántica temporal

### Contrato de eventos (estado actual, verificado contra el código)

`services/fulfillment-api` publica en el topic legado `logistpulse.orders` un payload mínimo `{orderId, event, storeId}`, **sin `eventId` ni patrón outbox**. `services/fulfillment-worker` consume ese mismo topic con `group_id=kitchen-worker` y solo mueve `WAITING -> PREPARING -> READY`; no expone checkpoints propios más allá del offset de Kafka, ni un campo `readyAt`. El contrato de eventos versionado (`logistpulse.fulfillment.events.v1`, `eventId`, outbox) es responsabilidad del **issue #1**; su integración de extremo a extremo es responsabilidad del **issue #4**. `scripts/acceptance/resilience_checks.py` detecta en vivo esta ausencia (no la asume) y reporta `SKIPPED` (exit 3) en sus cinco casos mientras el contrato no exista.

### Temporizadores

- Plazo de negocio: `createdAt + 15 s` (constante `PLAZO_S_DEFECTO` en `logist_kpis.py`).
- Transición real del worker: `PREPARING` inmediatamente tras `WAITING`, luego `time.sleep(4)` antes de `READY` (`services/fulfillment-worker/app.py`).
- Ventana de cohorte de L-K1: 900 s (15 min).

### Qué significa "tiempo real" en este laboratorio

El objetivo de tiempo real del laboratorio es: **p95 ≤ 1 s** desde que se envía el `POST /api/fulfillment/orders` hasta que el panel (Grafana Live, issue #3) representa la revisión de ese pedido, sobre **al menos 100 operaciones**, donde **una sola actualización perdida hace fallar la prueba completa** (no se excluye del cálculo de percentiles).

`scripts/acceptance/latency_benchmark.py` mide hoy una cosa más modesta y ya verificable: desde el `POST` hasta que el pedido es observable vía `GET /api/fulfillment/orders` (API, no panel), porque el panel del issue #3 todavía no existe. El script lo declara explícitamente como **cobertura parcial** y aplica la regla dura de pérdidas: cualquier pedido que nunca se vuelve observable dentro del timeout hace fallar la prueba completa (`exit 1`), sin excluirlo del percentil.

## 6. Diagrama del Release Gate

Estado real de `.github/workflows/ci.yml` hoy — el gate agregado **solo** exige que las dos etapas previas terminen en `success`; **no** ejecuta todavía la prueba de negocio ni las verificaciones de tiempo real (eso es trabajo del issue #4):

```text
PR
 |
 v
+-----------------------+      +----------------+      +--------------------------+
| architecture-contract |----->|   integration  |----->|      Release gate        |
| (assets + compose     |      | (build, up,    |      | (HOY: solo exige que     |
|  config --quiet)       |      |  smoke.sh,     |      |  architecture-contract e |
+-----------------------+      |  Prometheus/    |      |  integration == success) |
                                |  Grafana health)|      +--------------------------+
                                +----------------+                    |
                                                                       v
                                                          +-------------------------+
                                                          |  PASS  /  BLOCK         |
                                                          |  (falla/omite/cancela   |
                                                          |   cualquier etapa)      |
                                                          +-------------------------+

PENDIENTE (issue #4): insertar aqui una etapa "Business Test" que ejecute
scripts/acceptance/run-acceptance.sh y tests/kpis, y que el Release gate
tambien dependa de su resultado. Hoy esa etapa NO existe en el pipeline
real; este bloque documenta el DISENO objetivo, no el estado actual.
```

Diagrama del pipeline objetivo del Deber 01 (diseño, no implementado todavía):

```text
PR -> Build -> Test -> Docker -> Business Test -> PASS/BLOCK
```

## 7. Evidencia: PR sano (verde)

`PENDIENTE — requiere abrir un PR de evidencia con la infraestructura sana y un pedido que sí llega a READY a tiempo (caso de fixtures/logistpulse/pedido-sano.json); depende de que #4 conecte scripts/acceptance/run-acceptance.sh al pipeline de CI (hoy el Release gate no lo invoca).`

| Campo | Valor |
|---|---|
| URL del PR | `PENDIENTE — Daniel debe pegar la URL real` |
| SHA del commit | `PENDIENTE — Daniel debe pegar el SHA real` |
| Run ID de GitHub Actions | `PENDIENTE — Daniel debe pegar el run id real` |
| `architecture-contract` | `PENDIENTE` |
| `integration` | `PENDIENTE` |
| `Release gate` | `PENDIENTE` |
| Salida de `bash scripts/acceptance/run-acceptance.sh` | `PENDIENTE — pegar la tabla resumen real de la corrida` |
| Captura del panel (Grafana Live) | `PENDIENTE — requiere el panel del issue #3, todavía no existe` |

## 8. Evidencia: PR con tecnología verde y negocio rojo

Esta es la regresión controlada del issue #5: infraestructura sana (`UP`), pero el pedido de `total = 25.5` no llega a `READY` a tiempo (caso `fixtures/logistpulse/pedido-vencido-25-50.json`). **Esta regresión se demuestra en un PR y nunca se integra en `main`.**

| Campo | Valor |
|---|---|
| URL del PR (draft, nunca mergeado) | `PENDIENTE — Daniel debe pegar la URL real` |
| SHA del commit | `PENDIENTE — Daniel debe pegar el SHA real` |
| Run ID de GitHub Actions | `PENDIENTE — Daniel debe pegar el run id real` |
| `architecture-contract` | `PENDIENTE (esperado: success — la regresión es de negocio, no de arquitectura)` |
| `integration` | `PENDIENTE (esperado: success — la infraestructura está sana)` |
| Resultado de `business_test_fulfillment.py` | `PENDIENTE (esperado: RESULTADO: FAIL orderId=... estado=WAITING|PREPARING)` |
| Resultado de `latency_benchmark.py` | `PENDIENTE` |
| Resultado de `resilience_checks.py` | `PENDIENTE (esperado hoy: SKIPPED, exit 3 — depende de #1/#4)` |
| Salida agregada de `run-acceptance.sh` | `PENDIENTE (esperado: GATE AGREGADO: FAIL, exit 1, por el FAIL de negocio)` |

## 9. Evidencia del bloqueo efectivo del merge

`PENDIENTE — hoy el Release gate de .github/workflows/ci.yml (verificado en este repo) NO ejecuta business_test_fulfillment.py ni run-acceptance.sh; solo exige que architecture-contract e integration terminen en success. Por lo tanto, con el pipeline actual, el PR del punto 8 pasaría el gate agregado aunque el negocio esté en rojo — este es precisamente el vacío que el issue #4 debe cerrar incorporando una etapa de Business Test de la que dependa el Release gate. Esta fila queda PENDIENTE hasta que #4 la implemente y Daniel pueda evidenciar un bloqueo real.`

| Campo | Valor |
|---|---|
| ¿El Release gate hoy considera el resultado de negocio? | No (verificado en `.github/workflows/ci.yml`) |
| Etapa "Business Test" en el pipeline | `PENDIENTE — depende de #4` |
| Captura del check en rojo bloqueando el botón de merge | `PENDIENTE — depende de #4` |
| URL del PR bloqueado | `PENDIENTE` |

## 10. Diagnóstico y corrección

| Campo | Valor |
|---|---|
| Causa raíz del falso verde | Ninguna: en LOGISTPULSE el worker (`services/fulfillment-worker/app.py`) implementa correctamente `WAITING -> PREPARING -> (4s) -> READY`. El "falso verde" de este issue es la **ausencia de una prueba de negocio en el gate**, no un bug de dominio — a diferencia de BANKPULSE, donde sí existe un defecto real en `SplitSession.closeIfAuthorized()`. |
| Corrección requerida | Issue #4 debe incorporar `scripts/acceptance/run-acceptance.sh` (o equivalente) como etapa `Business Test` del pipeline, y hacer que `Release gate` dependa de su resultado. |
| Estado de la corrección | `PENDIENTE — trabajo de #4, no de #5` |
| Evidencia de la corrección aplicada | `PENDIENTE` |

## 11. Ejecución final verde

`PENDIENTE — requiere que #4 incorpore la etapa Business Test al gate (punto 10) y que el equipo vuelva a correr scripts/acceptance/run-acceptance.sh y tests/kpis contra un despliegue sano con un pedido que sí cumple el plazo, para documentar aquí la corrida real.`

| Campo | Valor |
|---|---|
| URL del PR final | `PENDIENTE` |
| Run ID de GitHub Actions | `PENDIENTE` |
| Resultado de `business_test_fulfillment.py` | `PENDIENTE (esperado: RESULTADO: PASS)` |
| Resultado de `latency_benchmark.py` | `PENDIENTE (esperado: RESULTADO: PASS, p50/p95 reales, N>=100)` |
| Resultado de `run-acceptance.sh` | `PENDIENTE (esperado: GATE AGREGADO: PASS)` |
| `pytest tests/kpis` | `PENDIENTE (esperado: todos los casos en verde)` |

## 12. Cómo reproducir desde un Codespace limpio

Todos los comandos siguientes existen tal cual en este repositorio (`README.md`, `CONTRIBUTING.md`, `scripts/`).

**Bootstrap:**

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
bash scripts/smoke.sh
```

**Observabilidad (Prometheus/Grafana/cAdvisor):**

```bash
docker compose -f observability/compose.yaml up -d
```

Grafana en el puerto `3000` (`admin / logistpulse_demo`), Prometheus en `9090`, cAdvisor en `8088`.

**Tráfico y evidencia de aceptación (issue #5):**

```bash
bash scripts/acceptance/run-acceptance.sh http://localhost:8080
```

Este orquestador ejecuta en orden `business_test_fulfillment.py`, `latency_benchmark.py` (con `-n` configurable; el criterio del laboratorio pide `N >= 100`) y `resilience_checks.py`, e imprime una tabla resumen con el código de salida real de cada etapa.

Para ejecutar cada etapa por separado con parámetros propios (ver `--help` de cada script):

```bash
python3 scripts/acceptance/business_test_fulfillment.py --base-url http://localhost:8080 --total 25.5
python3 scripts/acceptance/latency_benchmark.py --base-url http://localhost:8080 -n 100
python3 scripts/acceptance/resilience_checks.py --base-url http://localhost:8080
```

**Replay del caso de aceptación exacto del issue #5** (pedido `total=25.5`, se puede repetir cuantas veces se quiera contra un entorno recién levantado):

```bash
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"storeId":"STORE-042","channel":"ACCEPTANCE-TEST","total":25.5}' \
  http://localhost:8080/api/fulfillment/orders
```

**Pruebas de KPIs (deterministas, sin infraestructura):**

```bash
pip install -r requirements-test.txt
python3 -m pytest tests/kpis -v
```

**Reinicio limpio del stack:**

```bash
bash scripts/down.sh
bash scripts/up.sh
```

**Live / panel de Grafana:** `PENDIENTE — depende de que el issue #3 (Grafana Live, paneles y alertas) exista; hoy no hay panel ni dashboard de streaming que reproducir en este repositorio.`

## 13. Tabla de contribuciones del equipo

| Issue | Responsable | Entrega (según `CONTRIBUTING.md`) | PR | Evidencia |
|---|---|---|---|---|
| #1 | `@nikotov` | Contrato de eventos, outbox del ciclo del pedido y definición de KPIs propios | `PENDIENTE` | `PENDIENTE` |
| #2 | `@DanielSalazar0710` | Analítica continua, deduplicación, estado persistente y temporizadores | `PENDIENTE` | `PENDIENTE` |
| #3 | `@oandretty010` | Grafana Live, paneles, alertas y reconexión | `PENDIENTE` | `PENDIENTE` |
| #4 | `@VillaforTech` | Compose, streaming, integración y Release Gate del deber | `PENDIENTE` | `PENDIENTE` |
| #5 | `@Dmt-155lbs` (Daniel, autor de este documento) | Pruebas de extremo a extremo, resiliencia y evidencia del falso verde | `PENDIENTE` | `scripts/acceptance/`, `tests/kpis/`, `fixtures/logistpulse/` en `feat/5-deber-01-harness`; ejecución real `PENDIENTE` |

## 14. Checklist de la rúbrica 3+5+2

**Bloque de 3 (fundamentos del falso verde):**

- [ ] Capacidad de negocio identificada correctamente (Sección 1) — hecho en este documento
- [ ] Escenario de falso verde descrito con precisión técnica (Sección 2) — hecho en este documento
- [ ] KPIs propios con fórmula, población, ventana y umbral (Sección 4) — hecho en este documento

**Bloque de 5 (evidencia de extremo a extremo):**

- [ ] PR sano documentado con checks reales — `PENDIENTE` (Sección 7)
- [ ] PR con regresión de negocio (tecnología verde, negocio rojo) — `PENDIENTE` (Sección 8)
- [ ] Bloqueo efectivo del merge evidenciado — `PENDIENTE`, depende de #4 (Sección 9)
- [ ] Diagnóstico y corrección documentados — `PENDIENTE`, corrección es de #4 (Sección 10)
- [ ] Ejecución final verde evidenciada — `PENDIENTE` (Sección 11)

**Bloque de 2 (reproducibilidad y rigor):**

- [ ] Instrucciones de reproducción desde Codespace limpio con comandos reales verificados contra el repo — hecho en este documento (Sección 12)
- [ ] Distinción explícita entre diseño/esperado y observado, sin inventar URLs/SHAs/run ids/capturas/latencias — hecho en este documento

## 15. Límites del benchmark de laboratorio

- `total` es una unidad monetaria de laboratorio (datos demo). No es USD, no es ingreso real ni pérdida financiera demostrada.
- El benchmark de latencia (`latency_benchmark.py`) mide hoy solo hasta la observabilidad vía API (`GET /api/fulfillment/orders`), no hasta el panel de Grafana Live — porque ese panel (issue #3) todavía no existe. Es una cobertura parcial, declarada como tal en el propio script.
- Los cinco casos de `resilience_checks.py` (evento duplicado, eventos desordenados, broker caído con outbox pendiente, reinicio de consumidor con checkpoint, desconexión de Grafana Live) son estructuralmente imposibles de ejecutar hoy: dependen del contrato de eventos versionado del issue #1 y de la integración del issue #4. El script lo detecta en vivo (no lo asume) y reporta `SKIPPED` (exit 3), que el orquestador nunca cuenta como verde.
- El Release gate actual (`.github/workflows/ci.yml`) solo exige que `architecture-contract` e `integration` terminen en `success`; no ejecuta la prueba de negocio del Deber 01. Incorporar esa etapa es trabajo del issue #4, no de este documento ni del issue #5.
- El HTTP 502 al consultar inventario durante el arranque, observado el 9 de septiembre de 2026 al configurar el equipo, es una caída técnica de infraestructura y **no** es el falso verde de negocio que este documento analiza.
- Los umbrales de los KPIs (0 % / 0 unidades demo / 0 pedido-segundos) son metas de laboratorio para un ejercicio académico, no un SLA de producción.
