"""KPIs de laboratorio de LOGISTPULSE (issue #5).

Funciones puras: no abren sockets, no leen archivos, no importan nada que
arranque Kafka/Postgres/etc. Reciben la lista de pedidos y el instante
"ahora" como parametros, para que las pruebas puedan inyectar un reloj
determinista.

IMPORTANTE sobre `total`: es una unidad monetaria DE LABORATORIO
(datos demo generados para el ejercicio). No representa USD ni ingresos
reales ni perdidos. L-K2 es una suma de esas unidades demo, no dinero real.

Un "pedido" es un dict con, como minimo:
    orderId:   str
    total:     numero (se castea a Decimal via str() para evitar el
               error binario de float)
    status:    "WAITING" | "PREPARING" | "READY" (u otro estado terminal)
    createdAt: epoch segundos (float)
Opcionalmente:
    readyAt:   epoch segundos (float) - instante en que se alcanzo READY.
               Hoy el sistema real (services/fulfillment-api,
               services/fulfillment-worker) NO expone este campo todavia
               (lo construye el issue #1); si falta, se usa `updatedAt`
               como aproximacion SOLO cuando status == "READY", y en caso
               de no existir tampoco `updatedAt` se asume que el pedido
               sigue sin plazo cumplido (no se inventa un readyAt).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Mapping, Union

PLAZO_S_DEFECTO = 15
VENTANA_COHORTE_S_DEFECTO = 900  # 15 minutos

ESTADOS_ABIERTOS = {"WAITING", "PREPARING"}

SinMuestra = str  # literal "SIN MUESTRA"


def _to_decimal(valor) -> Decimal:
    """Convierte a Decimal pasando por str() para no arrastrar el error
    binario de un float (nunca Decimal(float) directo)."""
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def _ready_at(pedido: Mapping) -> Union[float, None]:
    """Devuelve el instante en que el pedido alcanzo READY, si se puede
    determinar. Prioriza `readyAt` (campo futuro del issue #1). Si no
    existe, y el estado actual es READY, usa `updatedAt` como
    aproximacion del sistema real actual. Si no hay forma de saberlo,
    devuelve None (pedido sin llegada a READY conocida)."""
    if "readyAt" in pedido and pedido["readyAt"] is not None:
        return pedido["readyAt"]
    if pedido.get("status") == "READY" and pedido.get("updatedAt") is not None:
        return pedido["updatedAt"]
    return None


def _vencio(pedido: Mapping, ahora: float, plazo_s: float) -> bool:
    """True si el plazo (createdAt + plazo_s) ya paso respecto de `ahora`."""
    return ahora >= pedido["createdAt"] + plazo_s


def _incumplio_plazo(pedido: Mapping, ahora: float, plazo_s: float) -> bool:
    """True si, dado que el plazo ya vencio, el pedido NO llego a READY a
    tiempo. Un pedido todavia abierto (WAITING/PREPARING) cuenta como
    incumplido. Uno que llego a READY tarde (ready_at > deadline) tambien
    cuenta como incumplido. Solo NO incumple si llego a READY a tiempo
    (ready_at <= deadline)."""
    deadline = pedido["createdAt"] + plazo_s
    ready_at = _ready_at(pedido)
    if ready_at is None:
        # Sin evidencia de haber llegado a READY -> sigue abierto a
        # efectos de este calculo -> incumplido (el plazo ya vencio).
        return True
    return ready_at > deadline


def calcular_l_k1(
    pedidos: Iterable[Mapping],
    ahora: float,
    plazo_s: float = PLAZO_S_DEFECTO,
    ventana_cohorte_s: float = VENTANA_COHORTE_S_DEFECTO,
) -> Union[float, SinMuestra]:
    """L-K1: % de pedidos con plazo vencido que incumplieron, dentro de la
    cohorte de pedidos creados en los ultimos `ventana_cohorte_s` segundos.

    L-K1 = 100 * (incumplidos con plazo vencido) / (elegibles con plazo vencido)

    - Cohorte: createdAt dentro de [ahora - ventana_cohorte_s, ahora].
    - Elegible: pertenece a la cohorte Y su plazo (createdAt + plazo_s) ya
      vencio (ahora >= createdAt + plazo_s).
    - Un pedido todavia abierto (WAITING/PREPARING) con plazo vencido
      cuenta como incumplido.
    - Un pedido que llego a READY tarde sigue contando como incumplido
      mientras pertenezca a la cohorte.
    - Sin pedidos elegibles -> "SIN MUESTRA" (nunca 0.0 ni 100.0).

    Devuelve un float (porcentaje 0..100) o el string "SIN MUESTRA".
    """
    elegibles = [
        p
        for p in pedidos
        if (ahora - p["createdAt"]) <= ventana_cohorte_s and _vencio(p, ahora, plazo_s)
    ]
    if not elegibles:
        return "SIN MUESTRA"
    incumplidos = sum(1 for p in elegibles if _incumplio_plazo(p, ahora, plazo_s))
    return 100.0 * incumplidos / len(elegibles)


def calcular_l_k2(
    pedidos: Iterable[Mapping],
    ahora: float,
    plazo_s: float = PLAZO_S_DEFECTO,
) -> Decimal:
    """L-K2: suma de `total` (unidades demo, NO USD) de TODOS los pedidos
    WAITING/PREPARING cuyo plazo ya vencio. Foto del backlog actual
    completo: NO se limita a la ventana de 15 minutos (a diferencia de
    L-K1).

    Devuelve Decimal para evitar el error binario de sumar floats.
    """
    total = Decimal("0")
    for p in pedidos:
        if p.get("status") in ESTADOS_ABIERTOS and _vencio(p, ahora, plazo_s):
            total += _to_decimal(p["total"])
    return total


def calcular_l_k3(
    pedidos: Iterable[Mapping],
    ahora: float,
    plazo_s: float = PLAZO_S_DEFECTO,
) -> float:
    """L-K3: suma de max(0, ahora - createdAt - plazo_s) sobre todos los
    pedidos todavia WAITING/PREPARING (backlog completo, sin ventana de
    cohorte). Unidad: pedido-segundo (segundos de atraso acumulados en el
    backlog abierto).
    """
    acumulado = 0.0
    for p in pedidos:
        if p.get("status") in ESTADOS_ABIERTOS:
            atraso = ahora - p["createdAt"] - plazo_s
            if atraso > 0:
                acumulado += atraso
    return acumulado
