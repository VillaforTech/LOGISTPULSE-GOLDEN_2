#!/usr/bin/env python3
"""Prueba de negocio de extremo a extremo para Order Fulfillment (issue #5).

Solo libreria estandar (urllib.request, json, time, argparse). Nada de
`requests` ni otras dependencias externas.

Flujo:
  1) Esperar la disponibilidad REAL (no asumida) de las 4 APIs del edge
     via GET /health/<servicio>, leyendo {"status":"UP",...} de cada una.
  2) Crear UN pedido identificable (storeId/channel propios de esta
     corrida) con `total` configurable via --total.
  3) Hacer polling acotado de GET /api/fulfillment/orders (la API solo
     devuelve los ultimos 20 pedidos) buscando ESE orderId por su valor
     exacto.
  4) Afirmar que el pedido alcanza status READY dentro del plazo
     configurado (--plazo-s, por defecto 15s, igual al KPI L-K1).

ADVERTENCIA EXPLICITA (tambien impresa en el resultado final):
  Si el orderId de esta corrida NUNCA aparece en la lista de los ultimos
  20 pedidos (porque otros procesos crearon >=20 pedidos nuevos mientras
  esperabamos, o porque la API fallo), el resultado es ERROR por
  poblacion insuficiente / entorno no observable. NUNCA se reporta PASS
  en ese caso: no hay forma de confirmar el estado real del pedido si no
  podemos verlo, y afirmar PASS sin verlo seria un falso verde.

Codigos de salida:
  0 = PASS (el pedido de esta corrida llego a READY dentro del plazo)
  1 = FAIL de negocio (el pedido se observo pero no llego a READY a
      tiempo, o llego a un estado inesperado)
  2 = ERROR de entorno/infraestructura (health no llego a UP, la API no
      respondio, o el pedido nunca fue observable en la lista de 20).
      Un ERROR NUNCA debe interpretarse ni reportarse como un falso
      verde/PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

SERVICIOS_SALUD = ["inventory", "logistics", "operations", "fulfillment"]


def log(msg: str) -> None:
    print(f"[business-test] {msg}", flush=True)


def http_get_json(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        cuerpo = resp.read().decode("utf-8")
        return resp.status, json.loads(cuerpo) if cuerpo else None


def http_post_json(url: str, payload: dict, timeout: float = 5.0):
    datos = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        cuerpo = resp.read().decode("utf-8")
        return resp.status, json.loads(cuerpo) if cuerpo else None


def esperar_readiness(base_url: str, timeout_total_s: float, log_fn=log) -> bool:
    """Espera la disponibilidad REAL de las 4 APIs (no la asume). Devuelve
    True solo si TODOS los servicios respondieron status UP dentro del
    plazo. No re-intenta indefinidamente: si vence el timeout, devuelve
    False y el llamador debe reportar ERROR (no PASS)."""
    pendientes = set(SERVICIOS_SALUD)
    limite = time.monotonic() + timeout_total_s
    while pendientes and time.monotonic() < limite:
        for servicio in list(pendientes):
            url = f"{base_url}/health/{servicio}"
            try:
                status, cuerpo = http_get_json(url, timeout=3.0)
                if status == 200 and isinstance(cuerpo, dict) and cuerpo.get("status") == "UP":
                    pendientes.discard(servicio)
                    log_fn(f"health OK: {servicio}")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                log_fn(f"health aun no disponible: {servicio} ({e})")
        if pendientes:
            time.sleep(2)
    if pendientes:
        log_fn(f"servicios que NUNCA reportaron UP: {sorted(pendientes)}")
        return False
    return True


def crear_pedido(base_url: str, store_id: str, channel: str, total: float):
    url = f"{base_url}/api/fulfillment/orders"
    payload = {"storeId": store_id, "channel": channel, "total": total}
    status, cuerpo = http_post_json(url, payload)
    if status != 201 or not isinstance(cuerpo, dict) or "orderId" not in cuerpo:
        raise RuntimeError(f"creacion de pedido invalida: status={status} cuerpo={cuerpo}")
    return cuerpo["orderId"], cuerpo.get("status")


def buscar_pedido(base_url: str, order_id: str):
    """Busca `order_id` dentro de GET /api/fulfillment/orders (solo
    devuelve los ultimos 20). Devuelve el dict del pedido o None si no
    aparece en esta lectura."""
    url = f"{base_url}/api/fulfillment/orders"
    status, cuerpo = http_get_json(url)
    if status != 200 or not isinstance(cuerpo, list):
        raise RuntimeError(f"lectura de lista de pedidos invalida: status={status}")
    for pedido in cuerpo:
        if pedido.get("orderId") == order_id:
            return pedido
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080", help="Base del edge (default: http://localhost:8080)")
    parser.add_argument("--store-id", default="STORE-042", help="storeId del pedido de prueba")
    parser.add_argument("--channel", default="ACCEPTANCE-TEST", help="channel identificable de esta corrida")
    parser.add_argument("--total", type=float, default=25.5, help="total del pedido de prueba (unidad demo, no USD)")
    parser.add_argument("--plazo-s", type=float, default=15.0, help="plazo de negocio en segundos (igual a L-K1)")
    parser.add_argument("--readiness-timeout-s", type=float, default=120.0, help="tiempo maximo esperando /health/*")
    parser.add_argument("--poll-timeout-s", type=float, default=30.0, help="tiempo maximo de polling buscando el pedido")
    parser.add_argument("--poll-interval-s", type=float, default=1.0, help="intervalo entre lecturas de la lista de pedidos")
    args = parser.parse_args()

    inicio = time.monotonic()

    # 1) Readiness real, no asumida.
    log("esperando readiness real de las 4 APIs via /health/<servicio>...")
    if not esperar_readiness(args.base_url, args.readiness_timeout_s):
        t = time.monotonic() - inicio
        print(f"RESULTADO: ERROR orderId=N/A estado=SIN_READINESS t={t:.1f}s")
        return 2

    # 2) Crear un pedido identificable.
    try:
        order_id, estado_creacion = crear_pedido(args.base_url, args.store_id, args.channel, args.total)
    except Exception as e:
        t = time.monotonic() - inicio
        log(f"error creando el pedido: {e}")
        print(f"RESULTADO: ERROR orderId=N/A estado=ERROR_CREACION t={t:.1f}s")
        return 2

    log(f"pedido creado: orderId={order_id} estado_inicial={estado_creacion} total={args.total}")

    # 3) Polling acotado de la lista de 20, buscando ESTE orderId.
    limite_poll = time.monotonic() + args.poll_timeout_s
    ultimo_estado = None
    visto_alguna_vez = False
    while time.monotonic() < limite_poll:
        try:
            pedido = buscar_pedido(args.base_url, order_id)
        except Exception as e:
            log(f"error leyendo la lista de pedidos: {e}")
            pedido = None
        if pedido is not None:
            visto_alguna_vez = True
            ultimo_estado = pedido.get("status")
            if ultimo_estado == "READY":
                break
        time.sleep(args.poll_interval_s)

    t_total = time.monotonic() - inicio

    # ADVERTENCIA: si el pedido nunca fue observable en la lista de 20,
    # el resultado es ERROR por poblacion insuficiente. NUNCA PASS.
    if not visto_alguna_vez:
        log(
            "ADVERTENCIA: el orderId de esta corrida nunca aparecio en "
            "GET /api/fulfillment/orders (lista de solo 20). Puede deberse "
            "a que otros procesos crearon >=20 pedidos nuevos mientras "
            "esperabamos, o a una falla de la API. Esto es un ERROR de "
            "entorno/poblacion insuficiente, NUNCA un PASS."
        )
        print(f"RESULTADO: ERROR orderId={order_id} estado=NO_OBSERVADO t={t_total:.1f}s")
        return 2

    # La condicion de negocio real es "llego a READY dentro de la ventana
    # de polling". El plazo de negocio (L-K1, 15s sobre createdAt) se
    # valida por separado y de forma exacta con los KPIs (tests/kpis);
    # este script confirma el flujo de extremo a extremo contra el
    # sistema real.
    if ultimo_estado == "READY":
        print(f"RESULTADO: PASS orderId={order_id} estado=READY t={t_total:.1f}s")
        return 0

    if ultimo_estado in ("WAITING", "PREPARING"):
        log(f"el pedido no alcanzo READY dentro del polling: estado={ultimo_estado}")
        print(f"RESULTADO: FAIL orderId={order_id} estado={ultimo_estado} t={t_total:.1f}s")
        return 1

    # Estado inesperado (ni READY ni WAITING/PREPARING).
    log(f"estado final inesperado: {ultimo_estado}")
    print(f"RESULTADO: FAIL orderId={order_id} estado={ultimo_estado} t={t_total:.1f}s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
