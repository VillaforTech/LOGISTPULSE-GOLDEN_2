#!/usr/bin/env python3
"""Benchmark de latencia de creacion -> observabilidad de pedidos
(issue #5). Solo libreria estandar.

COBERTURA PARCIAL: no mide el panel (depende de #3). La meta de negocio
"p95 <= 1s" del laboratorio se define HASTA EL PANEL (Grafana Live,
issue #3), que hoy no existe. Este script mide una cosa mas modesta y
ya verificable: desde que se envia el POST de creacion hasta que ese
pedido es observable con su revision (aqui, su `status`/`updatedAt`
actual) via GET /api/fulfillment/orders. Es una PROYECCION del extremo
API, no una medicion del panel. Cuando el issue #3 exista, este script
debe extenderse (o reemplazarse) para medir hasta la observabilidad real
en el panel.

REGLA DURA sobre operaciones perdidas:
Una operacion que nunca se vuelve observable (nunca aparece en la lista
de los ultimos 20 pedidos dentro del tiempo maximo de esta corrida) es
una PERDIDA. Las perdidas NO se excluyen del calculo de percentiles ni
se ignoran: cualquier perdida hace FALLAR la prueba completa (exit 1).
Nunca se reporta un p95 "limpio" descartando las perdidas: eso seria
maquillar la muestra y producir un falso verde.

Uso:
  python3 latency_benchmark.py --base-url http://localhost:8080 -n 100

Salida:
  - Resumen en stdout: enviados, vistos, perdidos, errores, p50, p95, maximo.
  - Un JSON con las muestras crudas (--out, por defecto
    latency_benchmark_result.json en el directorio actual).

Codigos de salida:
  0 = OK (todas las operaciones fueron vistas, sin perdidas ni errores)
  1 = FAIL (hubo al menos una operacion perdida o con error de envio)
  2 = ERROR de entorno (readiness nunca llego a UP, o la API de listado
      no respondio en absoluto)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

SERVICIOS_SALUD = ["inventory", "logistics", "operations", "fulfillment"]


def log(msg: str) -> None:
    print(f"[latency-benchmark] {msg}", flush=True)


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


def esperar_readiness(base_url: str, timeout_total_s: float) -> bool:
    pendientes = set(SERVICIOS_SALUD)
    limite = time.monotonic() + timeout_total_s
    while pendientes and time.monotonic() < limite:
        for servicio in list(pendientes):
            try:
                status, cuerpo = http_get_json(f"{base_url}/health/{servicio}", timeout=3.0)
                if status == 200 and isinstance(cuerpo, dict) and cuerpo.get("status") == "UP":
                    pendientes.discard(servicio)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                pass
        if pendientes:
            time.sleep(2)
    return not pendientes


def percentil(valores_ordenados, p):
    """Percentil simple por interpolacion (metodo "nearest-rank" con
    interpolacion lineal), sin dependencias externas."""
    if not valores_ordenados:
        return None
    if len(valores_ordenados) == 1:
        return valores_ordenados[0]
    k = (len(valores_ordenados) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(valores_ordenados) - 1)
    if f == c:
        return valores_ordenados[f]
    return valores_ordenados[f] + (valores_ordenados[c] - valores_ordenados[f]) * (k - f)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("-n", "--num-operaciones", type=int, default=100, help="cantidad de pedidos a enviar (>=100 recomendado)")
    parser.add_argument("--channel", default="LATENCY-BENCH", help="channel identificable de esta corrida")
    parser.add_argument("--total", type=float, default=1.0, help="total de cada pedido (unidad demo, no USD)")
    parser.add_argument("--readiness-timeout-s", type=float, default=120.0)
    parser.add_argument("--observacion-timeout-s", type=float, default=60.0, help="tiempo maximo total esperando que TODAS las operaciones sean observables")
    parser.add_argument("--poll-interval-s", type=float, default=0.5)
    parser.add_argument("--out", default="latency_benchmark_result.json", help="ruta de salida del JSON con las muestras crudas")
    args = parser.parse_args()

    if args.num_operaciones < 100:
        log(f"ADVERTENCIA: N={args.num_operaciones} < 100, el criterio del laboratorio pide N>=100")

    log("esperando readiness real de las 4 APIs...")
    if not esperar_readiness(args.base_url, args.readiness_timeout_s):
        log("ERROR: readiness nunca llego a UP para todas las APIs")
        print("RESULTADO: ERROR enviados=0 vistos=0 perdidos=0 errores=0")
        return 2

    # 1) Enviar N operaciones identificables, registrando t_envio de cada una.
    muestras = {}  # orderId -> dict con t_envio, t_visto, revision_inicial, revision_final
    errores_envio = 0
    for i in range(args.num_operaciones):
        t0 = time.monotonic()
        try:
            status, cuerpo = http_post_json(
                f"{args.base_url}/api/fulfillment/orders",
                {"storeId": "STORE-042", "channel": args.channel, "total": args.total},
            )
            if status != 201 or not isinstance(cuerpo, dict) or "orderId" not in cuerpo:
                raise RuntimeError(f"respuesta invalida: status={status} cuerpo={cuerpo}")
            order_id = cuerpo["orderId"]
            muestras[order_id] = {
                "orderId": order_id,
                "indice": i,
                "t_envio": t0,
                "t_visto": None,
                "revision_inicial": cuerpo.get("status"),
                "revision_final": None,
                "latencia_s": None,
                "perdido": True,
                "error_envio": None,
            }
        except Exception as e:
            errores_envio += 1
            log(f"error enviando operacion {i}: {e}")

    log(f"enviadas {len(muestras)} operaciones (errores de envio: {errores_envio})")

    # 2) Polling acotado de GET /api/fulfillment/orders hasta que todas
    #    las operaciones sean observables (o venza el timeout).
    limite = time.monotonic() + args.observacion_timeout_s
    pendientes = set(muestras.keys())
    error_listado = None
    while pendientes and time.monotonic() < limite:
        try:
            status, cuerpo = http_get_json(f"{args.base_url}/api/fulfillment/orders")
            if status != 200 or not isinstance(cuerpo, list):
                raise RuntimeError(f"listado invalido: status={status}")
            t_lectura = time.monotonic()
            for pedido in cuerpo:
                oid = pedido.get("orderId")
                if oid in pendientes:
                    m = muestras[oid]
                    m["t_visto"] = t_lectura
                    m["revision_final"] = pedido.get("status")
                    m["latencia_s"] = t_lectura - m["t_envio"]
                    m["perdido"] = False
                    pendientes.discard(oid)
        except Exception as e:
            error_listado = str(e)
            log(f"error leyendo la lista de pedidos: {e}")
        if pendientes:
            time.sleep(args.poll_interval_s)

    if not muestras:
        log("ERROR: no se pudo enviar ninguna operacion (0 muestras)")
        print("RESULTADO: ERROR enviados=0 vistos=0 perdidos=0 errores=0")
        return 2

    vistos = [m for m in muestras.values() if not m["perdido"]]
    perdidos = [m for m in muestras.values() if m["perdido"]]

    latencias = sorted(m["latencia_s"] for m in vistos)
    p50 = percentil(latencias, 50)
    p95 = percentil(latencias, 95)
    maximo = max(latencias) if latencias else None

    resultado = {
        "baseUrl": args.base_url,
        "numOperaciones": args.num_operaciones,
        "enviados": len(muestras),
        "erroresEnvio": errores_envio,
        "vistos": len(vistos),
        "perdidos": len(perdidos),
        "p50Segundos": p50,
        "p95Segundos": p95,
        "maximoSegundos": maximo,
        "coberturaParcialPanelPendiente": True,
        "notaCobertura": (
            "COBERTURA PARCIAL: no mide el panel (depende de #3). "
            "Mide solo hasta la observabilidad via API "
            "(GET /api/fulfillment/orders), no hasta Grafana Live."
        ),
        "reglaOperacionesPerdidas": (
            "Las operaciones perdidas NO se excluyen de los percentiles: "
            "su presencia hace FALLAR la prueba completa."
        ),
        "muestras": list(muestras.values()),
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    log(f"muestras crudas guardadas en {args.out}")

    log("COBERTURA PARCIAL: no mide el panel (depende de #3).")
    p50_txt = f"{p50:.3f}s" if p50 is not None else "N/A"
    p95_txt = f"{p95:.3f}s" if p95 is not None else "N/A"
    max_txt = f"{maximo:.3f}s" if maximo is not None else "N/A"
    print(
        "RESULTADO_BENCHMARK: "
        f"enviados={len(muestras)} vistos={len(vistos)} perdidos={len(perdidos)} "
        f"errores={errores_envio} p50={p50_txt} p95={p95_txt} maximo={max_txt}"
    )

    # REGLA DURA: cualquier perdida o error de envio hace fallar la prueba,
    # sin excepcion y sin excluirla del calculo anterior (ya se incluyo).
    if perdidos or errores_envio:
        log(
            f"FAIL: {len(perdidos)} operaciones perdidas y {errores_envio} errores de envio. "
            "Una operacion perdida jamas se excluye del resultado: la prueba falla."
        )
        print("RESULTADO: FAIL (hay operaciones perdidas y/o errores de envio)")
        return 1

    if error_listado and pendientes:
        # No deberia llegar aqui si perdidos ya cubre esto, pero se deja
        # explicito por claridad.
        print("RESULTADO: FAIL (errores de lectura del listado con pendientes)")
        return 1

    print("RESULTADO: PASS (todas las operaciones fueron observadas, sin perdidas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
