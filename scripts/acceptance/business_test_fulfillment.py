#!/usr/bin/env python3
"""Prueba de ACEPTACION DE NEGOCIO de extremo a extremo para Order
Fulfillment (issue #5).

Objetivo: verificar contra la API real (sin mocks) que un pedido
aceptado llega a `READY` dentro de su plazo de negocio, consultando
SIEMPRE el pedido por su `orderId` (GET /api/fulfillment/orders/{id}),
nunca escaneando el listado parcial de los ultimos 20 pedidos de
GET /api/fulfillment/orders (docs/kpis-deber-01.md es explicito: ese
listado "no es la poblacion de los KPIs" ni de esta prueba).

Reglas de negocio verificadas (docs/kpis-deber-01.md,
docs/events-deber-01.md):
  - El plazo de negocio es `createdAt + 15s`.
  - `readyAt` se persiste una sola vez, exactamente cuando el pedido
    pasa a READY; es la fuente de verdad del cumplimiento del plazo,
    NUNCA `updatedAt` (que puede cambiar por otras razones).
  - `aggregateVersion` avanza 1 (OrderAccepted) -> 2 (PreparationStarted)
    -> 3 (OrderReady) y nunca retrocede; se usa aqui para trazar que las
    lecturas sucesivas por ID corresponden al mismo pedido y a una
    progresion valida, no para decidir el veredicto de negocio.

Solo usa la biblioteca estandar de Python (urllib.request, json, time,
argparse). No requiere `requests` ni ninguna otra dependencia externa.

Codigos de salida:
  0 -> PASS: el pedido de esta corrida llego a READY dentro del plazo,
       confirmado consultandolo por su ID.
  1 -> FAIL de negocio: el pedido se observo por ID pero no llego a
       READY a tiempo (sigue abierto vencido, o `readyAt` excede el
       plazo).
  2 -> ERROR de entorno: la readiness real de las APIs no se alcanzo,
       hubo un error de red/infra, o el pedido creado por esta corrida
       dejo de ser observable por su ID (p.ej. 404). Un ERROR NUNCA se
       reporta ni se interpreta como PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8080"
# Los 4 servicios ruteados por el edge; misma lista que scripts/wait-ready.py.
SERVICIOS_SALUD = ["inventory", "logistics", "operations", "fulfillment"]
DEADLINE_SECONDS_DEFAULT = 15.0


class ErrorDeEntorno(RuntimeError):
    """Fallo de infraestructura/entorno: nunca debe interpretarse como PASS."""


def log(msg: str) -> None:
    print(f"[business-test] {msg}", flush=True)


def _http(method: str, url: str, body: dict | None = None, timeout: float = 10.0):
    """Llamada HTTP reutilizable con la stdlib. Devuelve (status_code, dict|None).

    No lanza excepcion por status >= 400: un 404/4xx es parte del
    protocolo de negocio que estamos observando (p.ej. "el pedido no
    aparece por su ID"), y quien llama decide que significa. Solo un
    error de red/conexion real se traduce en ErrorDeEntorno.
    """
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            parsed = json.loads(raw) if raw else None
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise ErrorDeEntorno(f"No se pudo conectar a {url}: {exc}") from exc


def esperar_readiness(base_url: str, timeout_total_s: float, log_fn=log) -> None:
    """Espera la disponibilidad REAL de las 4 APIs (no la asume), replicando
    la logica de scripts/wait-ready.py. Un HTTP de error NUNCA cuenta como
    listo. Si vence el timeout sin que todas reporten UP, lanza
    ErrorDeEntorno (el llamador debe reportar ERROR, nunca PASS)."""
    pendientes = set(SERVICIOS_SALUD)
    limite = time.monotonic() + timeout_total_s
    while pendientes and time.monotonic() < limite:
        for servicio in list(pendientes):
            url = f"{base_url}/health/{servicio}"
            try:
                status, cuerpo = _http("GET", url, timeout=3.0)
                if status == 200 and isinstance(cuerpo, dict) and cuerpo.get("status") == "UP":
                    pendientes.discard(servicio)
                    log_fn(f"health OK: {servicio}")
            except ErrorDeEntorno as e:
                log_fn(f"health aun no disponible: {servicio} ({e})")
        if pendientes:
            time.sleep(1)
    if pendientes:
        raise ErrorDeEntorno(f"servicios que NUNCA reportaron UP: {sorted(pendientes)}")


def crear_pedido(base_url: str, store_id: str, channel: str, total: float) -> dict:
    status, cuerpo = _http(
        "POST",
        f"{base_url}/api/fulfillment/orders",
        {"storeId": store_id, "channel": channel, "total": total},
    )
    if status != 201 or not isinstance(cuerpo, dict) or "orderId" not in cuerpo:
        raise ErrorDeEntorno(f"creacion de pedido invalida: status={status} cuerpo={cuerpo}")
    return cuerpo


def obtener_pedido_por_id(base_url: str, order_id: str) -> tuple[int, dict | None]:
    """Consulta el pedido por su ID exacto: GET /api/fulfillment/orders/{id}.

    Nunca escanea el listado de los ultimos 20 (GET /api/fulfillment/orders):
    ese listado esta explicitamente excluido como fuente de verdad en
    docs/kpis-deber-01.md. Devuelve (status, cuerpo) tal cual; quien llama
    decide si un 404 es un ERROR de entorno."""
    return _http("GET", f"{base_url}/api/fulfillment/orders/{order_id}")


def verificar_progresion_version(anterior: int | None, actual: int | None, log_fn=log) -> None:
    """Traza aggregateVersion de punta a punta: cuando esta disponible, no
    debe retroceder entre dos lecturas sucesivas del mismo orderId. No
    decide el veredicto de negocio por si sola; es una verificacion de
    consistencia/trazabilidad (docs/events-deber-01.md: 1->2->3, una sola
    direccion)."""
    if anterior is None or actual is None:
        return
    if actual < anterior:
        raise ErrorDeEntorno(
            f"aggregateVersion retrocedio de {anterior} a {actual}: el pedido "
            "observado por ID ya no es trazable de punta a punta"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base del edge (default: %(default)s)")
    parser.add_argument("--store-id", default="STORE-042", help="storeId del pedido de prueba")
    parser.add_argument("--channel", default="ACCEPTANCE-TEST", help="channel identificable de esta corrida")
    parser.add_argument("--total", type=float, default=25.5, help="total del pedido de prueba (unidad demo, no USD)")
    parser.add_argument("--plazo-s", type=float, default=DEADLINE_SECONDS_DEFAULT, help="plazo de negocio en segundos (igual a L-K1)")
    parser.add_argument("--readiness-timeout-s", type=float, default=120.0, help="tiempo maximo esperando /health/<servicio>")
    parser.add_argument("--poll-timeout-s", type=float, default=30.0, help="tiempo maximo de polling consultando el pedido por su ID")
    parser.add_argument("--poll-interval-s", type=float, default=0.5, help="intervalo entre consultas GET /api/fulfillment/orders/{id}")
    args = parser.parse_args()

    inicio = time.monotonic()

    # 1) Readiness real de las 4 APIs, nunca un sleep fijo.
    log("esperando readiness real de las 4 APIs via /health/<servicio>...")
    try:
        esperar_readiness(args.base_url, args.readiness_timeout_s)
    except ErrorDeEntorno as e:
        t = time.monotonic() - inicio
        log(f"readiness NUNCA se alcanzo: {e}")
        print(f"RESULTADO: ERROR orderId=N/A estado=SIN_READINESS t={t:.1f}s")
        return 2
    log("readiness OK")

    # 2) Crear un pedido identificable.
    try:
        creado = crear_pedido(args.base_url, args.store_id, args.channel, args.total)
    except ErrorDeEntorno as e:
        t = time.monotonic() - inicio
        log(f"error creando el pedido: {e}")
        print(f"RESULTADO: ERROR orderId=N/A estado=ERROR_CREACION t={t:.1f}s")
        return 2

    order_id = creado["orderId"]
    version_previa = creado.get("aggregateVersion")
    log(f"pedido creado: orderId={order_id} estado_inicial={creado.get('status')} aggregateVersion={version_previa} total={args.total}")

    # 3) Consultar el pedido por su ID exacto (nunca la lista de 20) hasta
    #    que llegue a READY o venza el polling.
    limite_poll = time.monotonic() + args.poll_timeout_s
    pedido: dict | None = None
    try:
        while time.monotonic() < limite_poll:
            status, cuerpo = obtener_pedido_por_id(args.base_url, order_id)
            if status == 404:
                raise ErrorDeEntorno(
                    f"el pedido {order_id} (creado por esta misma corrida) no aparece "
                    "consultado por su ID: GET /api/fulfillment/orders/{id} devolvio 404"
                )
            if status != 200 or not isinstance(cuerpo, dict):
                raise ErrorDeEntorno(f"lectura por ID invalida: status={status} cuerpo={cuerpo}")
            if cuerpo.get("orderId") != order_id:
                raise ErrorDeEntorno(
                    f"la consulta por ID devolvio un pedido distinto: pedi {order_id}, "
                    f"recibi {cuerpo.get('orderId')}"
                )
            verificar_progresion_version(version_previa, cuerpo.get("aggregateVersion"))
            version_previa = cuerpo.get("aggregateVersion")
            pedido = cuerpo
            if pedido.get("status") == "READY":
                break
            time.sleep(args.poll_interval_s)
    except ErrorDeEntorno as e:
        t = time.monotonic() - inicio
        log(f"error de entorno consultando el pedido por ID: {e}")
        print(f"RESULTADO: ERROR orderId={order_id} estado=NO_OBSERVABLE_POR_ID t={t:.1f}s")
        return 2

    t_total = time.monotonic() - inicio

    if pedido is None:
        # No deberia ocurrir (poll_timeout_s <= 0), pero por si acaso: sin
        # ninguna lectura valida, es ERROR, nunca PASS.
        print(f"RESULTADO: ERROR orderId={order_id} estado=SIN_LECTURAS t={t_total:.1f}s")
        return 2

    estado_final = pedido.get("status")
    created_at = pedido.get("createdAt")
    ready_at = pedido.get("readyAt")
    aggregate_version = pedido.get("aggregateVersion")

    if created_at is None:
        log("ADVERTENCIA: el pedido no trae createdAt; no se puede calcular el plazo")
        print(f"RESULTADO: ERROR orderId={order_id} estado=SIN_CREATED_AT t={t_total:.1f}s")
        return 2

    plazo = float(created_at) + args.plazo_s

    if estado_final == "READY":
        # La fuente de verdad del cumplimiento es readyAt persistido, NUNCA
        # updatedAt (docs/kpis-deber-01.md: updatedAt puede cambiar por
        # otras razones y no sustituye a readyAt).
        if ready_at is None:
            log("FALSO VERDE: el pedido quedo READY pero no persistio readyAt")
            print(f"RESULTADO: FAIL orderId={order_id} estado=READY_SIN_READY_AT t={t_total:.1f}s")
            return 1
        # readyAt == deadline cuenta como a tiempo (borde documentado en
        # docs/kpis-deber-01.md, caso 4: "<=" cuenta como a tiempo).
        if float(ready_at) <= plazo:
            print(
                f"RESULTADO: PASS orderId={order_id} estado=READY readyAt={ready_at} "
                f"plazo={plazo:.3f} aggregateVersion={aggregate_version} t={t_total:.1f}s"
            )
            return 0
        log(f"el pedido llego a READY tarde: readyAt={ready_at} > plazo={plazo:.3f}")
        print(
            f"RESULTADO: FAIL orderId={order_id} estado=READY_TARDE readyAt={ready_at} "
            f"plazo={plazo:.3f} t={t_total:.1f}s"
        )
        return 1

    if estado_final in ("WAITING", "PREPARING"):
        log(f"el pedido no alcanzo READY dentro del polling: estado={estado_final}")
        print(f"RESULTADO: FAIL orderId={order_id} estado={estado_final} t={t_total:.1f}s")
        return 1

    # Estado inesperado (ni READY ni WAITING/PREPARING).
    log(f"estado final inesperado: {estado_final}")
    print(f"RESULTADO: FAIL orderId={order_id} estado={estado_final} t={t_total:.1f}s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
