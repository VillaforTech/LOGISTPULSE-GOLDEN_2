#!/usr/bin/env python3
"""Casos de resiliencia/latencia de eventos para Order Fulfillment
(issue #5). Solo libreria estandar.

POR QUE TODO ESTO SE SALTA HOY (SKIPPED, no PASS):
El contrato de eventos (topic `logistpulse.fulfillment.events.v1`,
eventId, outbox, checkpoints de consumidor, Grafana Live) es
responsabilidad del issue #1 (contrato/outbox) y del issue #4
(integracion/streaming). Hoy (verificado contra el sistema real):
  - services/fulfillment-api solo publica en el topic legado
    `logistpulse.orders` con un payload minimo {orderId, event,
    storeId}, sin eventId ni outbox.
  - services/fulfillment-worker consume ese topic y solo mueve
    WAITING -> PREPARING -> READY; no expone checkpoints propios mas
    alla del group_id de Kafka, ni un campo readyAt.
  - No existe ningun endpoint ni stream de Grafana Live que consumir.

Por lo tanto NINGUNO de los casos de este archivo puede ejecutarse de
verdad todavia. Cada caso DETECTA la ausencia del contrato requerido y
reporta SKIPPED con exit code 3, dejando explicito que un SKIPPED NO es
un resultado verde: run-acceptance.sh nunca debe contar un SKIPPED como
PASS.

Cuando el issue #2 (analitica persistente) y el #3 (Grafana Live)
esten disponibles, cada funcion `check_*` debe reemplazar su deteccion
de ausencia por la implementacion real indicada en su TODO.

Casos cubiertos (esqueleto ejecutable, hoy todos SKIPPED):
  1. Duplicado del mismo eventId (idempotencia del consumidor).
  2. Eventos desordenados / tardios (fuera de orden de secuencia).
  3. Broker caido despues del commit de la transaccion de negocio, con
     outbox pendiente de publicar (perdida cero garantizada por outbox).
  4. Reinicio del consumidor antes y despues del checkpoint (offset
     commit) para validar que no se duplica ni se pierde trabajo.
  5. Desconexion de Grafana Live y verificacion de reconexion/backfill.

Codigos de salida del script completo:
  0 = todos los casos ejecutables PASARON (hoy, imposible: todos SKIPPED)
  3 = al menos un caso SKIPPED por dependencia ausente (issues #2 y #3) y
      ninguno FALLO -- este es el resultado esperado HOY.
  1 = al menos un caso FALLO de verdad (una vez implementado).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

EVENTS_TOPIC = "logistpulse.fulfillment.events.v1"
LEGACY_TOPIC = "logistpulse.orders"

SKIPPED = "SKIPPED"
PASS = "PASS"
FAIL = "FAIL"


def log(msg: str) -> None:
    print(f"[resilience] {msg}", flush=True)


def http_get_json(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        cuerpo = resp.read().decode("utf-8")
        return resp.status, json.loads(cuerpo) if cuerpo else None


def _contrato_eventos_disponible(base_url: str) -> bool:
    """Detecta si el contrato de eventos del issue #1 ya existe.

    Heuristica actual (verificada contra el sistema real de hoy): no
    existe ningun endpoint HTTP que exponga eventos individuales de
    fulfillment ni un campo `readyAt`/`eventId` en
    GET /api/fulfillment/orders. Mientras esos campos no aparezcan,
    se asume que el contrato NO esta disponible.

    TODO(issue #1): reemplazar esta heuristica por una comprobacion
    directa del contrato real una vez publicado (por ejemplo, un
    endpoint /api/fulfillment/events o un campo `eventId`/`readyAt`
    documentado en el contrato).
    """
    try:
        status, cuerpo = http_get_json(f"{base_url}/api/fulfillment/orders")
    except Exception as e:
        log(f"no se pudo consultar la API de fulfillment para detectar el contrato: {e}")
        return False
    if status != 200 or not isinstance(cuerpo, list):
        return False
    if not cuerpo:
        # Sin pedidos no podemos inspeccionar campos; asumimos ausente
        # por seguridad (nunca se asume disponible sin evidencia).
        return False
    campos = set(cuerpo[0].keys())
    return "eventId" in campos or "readyAt" in campos


def _reportar_skip(nombre_caso: str, motivo: str) -> str:
    log(f"{nombre_caso}: SKIPPED - {motivo}")
    print(f"CASO: {nombre_caso} RESULTADO: SKIPPED motivo={motivo}")
    return SKIPPED


def check_evento_duplicado(base_url: str, contrato_ok: bool) -> str:
    """Caso 1: duplicado del mismo eventId.

    Objetivo real (una vez exista el contrato): publicar dos veces el
    mismo evento (mismo eventId) y verificar que el estado del pedido
    solo se actualiza una vez (idempotencia), sin duplicar efectos
    (p.ej. sin duplicar la transicion PREPARING->READY).
    """
    nombre = "evento_duplicado"
    if not contrato_ok:
        return _reportar_skip(
            nombre,
            f"requiere #2 (services/business-analytics, sin fusionar: rama feat/2-business-analytics)",
        )
    # TODO(issues #2 y #3): implementar el caso real:
    #   1. Producir un evento con eventId=X hacia el topic de eventos.
    #   2. Reenviar EXACTAMENTE el mismo evento (mismo eventId=X).
    #   3. Verificar via el contrato/endpoint que el efecto se aplico
    #      una sola vez (idempotencia del consumidor).
    log(f"{nombre}: TODO implementar contra el contrato real")
    return FAIL  # nunca debe llegar aqui hasta implementar el TODO


def check_eventos_desordenados(base_url: str, contrato_ok: bool) -> str:
    """Caso 2: eventos desordenados o tardios.

    Objetivo real: enviar eventos fuera de secuencia (p.ej. READY antes
    que PREPARING, o un evento con timestamp anterior a uno ya
    procesado) y verificar que el consumidor no retrocede el estado del
    pedido ni corrompe el KPI.
    """
    nombre = "eventos_desordenados"
    if not contrato_ok:
        return _reportar_skip(
            nombre,
            f"requiere #2 (proyeccion analitica que observe orden y eventos tardios)",
        )
    # TODO(issues #2 y #3): implementar:
    #   1. Enviar evento de transicion N+1 antes que N.
    #   2. Enviar despues el evento N (tardio).
    #   3. Verificar que el estado final es consistente con el orden
    #      logico de negocio, no con el orden de llegada.
    log(f"{nombre}: TODO implementar contra el contrato real")
    return FAIL


def check_broker_caido_outbox_pendiente(base_url: str, contrato_ok: bool) -> str:
    """Caso 3: broker caido despues del commit de negocio, con outbox
    pendiente de publicar.

    Objetivo real: confirmar que un commit de negocio (p.ej. INSERT del
    pedido) exitoso con el broker caido inmediatamente despues deja el
    evento en una tabla outbox pendiente, y que al recuperarse el broker
    el evento se publica sin perdida ni duplicado espurio.
    """
    nombre = "broker_caido_outbox_pendiente"
    if not contrato_ok:
        return _reportar_skip(
            nombre,
            "requiere #2 (consumidor analitico para observar el outbox pendiente)",
        )
    # TODO(issues #2 y #3): implementar:
    #   1. Detener el broker (docker compose stop redpanda) tras un
    #      commit de negocio.
    #   2. Verificar que el evento queda en la tabla outbox (pendiente).
    #   3. Levantar el broker y verificar que el evento se publica
    #      exactamente una vez.
    log(f"{nombre}: TODO implementar contra el contrato real")
    return FAIL


def check_reinicio_consumidor_checkpoint(base_url: str, contrato_ok: bool) -> str:
    """Caso 4: reinicio del consumidor antes y despues del checkpoint.

    Objetivo real: matar el worker antes de comitear el offset (debe
    reprocesar sin perder el pedido) y despues de comitearlo (no debe
    reprocesar el mismo pedido dos veces).
    """
    nombre = "reinicio_consumidor_checkpoint"
    if not contrato_ok:
        return _reportar_skip(
            nombre,
            "requiere #2 (checkpoints del consumidor analitico)",
        )
    # TODO(issues #2 y #3): implementar:
    #   1. Reiniciar fulfillment-worker antes de que confirme el offset
    #      de un mensaje -> verificar que el pedido SI llega a READY
    #      (no se pierde).
    #   2. Reiniciar fulfillment-worker despues de confirmar el offset
    #      -> verificar que NO se reprocesa el mismo pedido (no hay
    #      transicion duplicada).
    log(f"{nombre}: TODO implementar contra el contrato real")
    return FAIL


def check_desconexion_grafana_live(base_url: str, contrato_ok: bool) -> str:
    """Caso 5: desconexion de Grafana Live.

    Objetivo real (depende ademas del issue #3, paneles/streaming):
    forzar la desconexion del stream de Grafana Live y verificar que
    reconecta y recupera el backlog perdido (o lo marca explicitamente
    como gap), sin mostrar datos silenciosamente incorrectos.
    """
    nombre = "desconexion_grafana_live"
    # Este caso depende ademas del issue #3 (paneles/streaming), no solo del #1.
    if not contrato_ok:
        return _reportar_skip(
            nombre,
            f"requiere #3 (Grafana Live, paneles, reconexion)",
        )
    # TODO(issue #1/#3): implementar:
    #   1. Cortar la conexion de Grafana Live (o del datasource
    #      streaming) mientras se generan eventos.
    #   2. Reconectar y verificar que el panel reconoce el gap o hace
    #      backfill, sin mostrar continuidad falsa.
    log(f"{nombre}: TODO implementar contra el contrato real")
    return FAIL


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()

    log(
        "Verificando si el contrato de eventos del issue #1 "
        f"({EVENTS_TOPIC}) ya existe..."
    )
    contrato_ok = _contrato_eventos_disponible(args.base_url)
    if contrato_ok:
        log("contrato de eventos detectado: se intentaran los casos reales.")
    else:
        log(
            f"contrato de eventos NO detectado (solo se observa el topic legado "
            f"{LEGACY_TOPIC} sin eventId/outbox). Todos los casos se reportaran "
            "SKIPPED. Esto NO es un resultado verde."
        )

    casos = [
        check_evento_duplicado,
        check_eventos_desordenados,
        check_broker_caido_outbox_pendiente,
        check_reinicio_consumidor_checkpoint,
        check_desconexion_grafana_live,
    ]

    resultados = [caso(args.base_url, contrato_ok) for caso in casos]

    hubo_fail = any(r == FAIL for r in resultados)
    hubo_skip = any(r == SKIPPED for r in resultados)

    print("---")
    print(f"resumen: PASS={resultados.count(PASS)} FAIL={resultados.count(FAIL)} SKIPPED={resultados.count(SKIPPED)}")

    if hubo_fail:
        print("RESULTADO: FAIL (al menos un caso de resiliencia fallo)")
        return 1
    if hubo_skip:
        print(
            "RESULTADO: SKIPPED (dependen de #2 (analitica) y #3 (Grafana Live), aun sin fusionar; SKIPPED nunca cuenta "
            "como resultado verde/PASS)"
        )
        return 3
    print("RESULTADO: PASS (todos los casos de resiliencia se ejecutaron y pasaron)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
