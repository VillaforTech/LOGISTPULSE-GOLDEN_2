"""Pruebas de las funciones puras de KPIs (issue #5).

Reloj SIEMPRE inyectado via el parametro `ahora`. Nunca se usa
time.time() real: estas pruebas deben ser deterministas y repetibles.
"""

from decimal import Decimal

from .logist_kpis import calcular_l_k1, calcular_l_k2, calcular_l_k3

T0 = 1_700_000_000.0  # instante base arbitrario (epoch), fijo para el test


def _pedido(order_id, total, status, created_at, ready_at=None, updated_at=None):
    p = {
        "orderId": order_id,
        "total": total,
        "status": status,
        "createdAt": created_at,
    }
    if ready_at is not None:
        p["readyAt"] = ready_at
    if updated_at is not None:
        p["updatedAt"] = updated_at
    return p


def test_criterio_aceptacion_pedido_25_50_todavia_waiting_a_los_20s():
    """Caso exacto del criterio de aceptacion del issue #5:
    pedido total=25.5 creado en t0, todavia WAITING a los 20s.
    """
    pedido = _pedido("ORD-000001", 25.5, "WAITING", T0)
    ahora = T0 + 20

    assert calcular_l_k1([pedido], ahora) == 100.0
    assert calcular_l_k2([pedido], ahora) == Decimal("25.5")
    assert calcular_l_k3([pedido], ahora) == 5.0


def test_pedido_sano_ready_a_los_4s_no_incumple():
    """Un pedido que llega a READY bien dentro del plazo (4s de 15s) no
    debe contar como incumplido, incluso evaluado despues de vencido el
    plazo."""
    pedido = _pedido(
        "ORD-000002", 18.0, "READY", T0, updated_at=T0 + 4
    )
    ahora = T0 + 30  # plazo ya vencido, evaluamos con el pedido cerrado

    assert calcular_l_k1([pedido], ahora) == 0.0
    # Ya no esta WAITING/PREPARING -> no aporta a L-K2 ni L-K3.
    assert calcular_l_k2([pedido], ahora) == Decimal("0")
    assert calcular_l_k3([pedido], ahora) == 0.0


def test_borde_exacto_15s_ready_justo_a_tiempo():
    """Si el pedido llega a READY EXACTAMENTE en el instante del plazo
    (createdAt + 15s), se considera a tiempo (limite inclusivo)."""
    pedido = _pedido("ORD-000003", 10.0, "READY", T0, updated_at=T0 + 15)
    ahora = T0 + 15  # el plazo vence justo ahora

    assert calcular_l_k1([pedido], ahora) == 0.0


def test_borde_exacto_15s_pedido_abierto_ya_cuenta_vencido():
    """En el instante exacto createdAt + 15s, un pedido que sigue abierto
    (sin llegar a READY) ya se considera con plazo vencido e incumplido."""
    pedido = _pedido("ORD-000004", 10.0, "WAITING", T0)
    ahora = T0 + 15

    assert calcular_l_k1([pedido], ahora) == 100.0
    assert calcular_l_k2([pedido], ahora) == Decimal("10.0")
    assert calcular_l_k3([pedido], ahora) == 0.0  # atraso = 15-15 = 0, no > 0


def test_pedido_tardio_dentro_de_cohorte_sigue_incumplido():
    """Un pedido que SI llego a READY, pero tarde (fuera del plazo de
    15s), sigue contando como incumplido mientras pertenezca a la
    cohorte de 15 minutos."""
    pedido = _pedido(
        "ORD-000005", 12.0, "READY", T0, updated_at=T0 + 16
    )
    ahora = T0 + 100  # dentro de la ventana de 15 min, plazo ya vencido

    assert calcular_l_k1([pedido], ahora) == 100.0


def test_cohorte_vacia_da_sin_muestra():
    """Sin pedidos elegibles (ninguno con plazo vencido dentro de la
    cohorte de 15 min) el resultado es el string 'SIN MUESTRA', nunca
    0.0 ni 100.0."""
    assert calcular_l_k1([], T0) == "SIN MUESTRA"

    # Pedido recien creado, plazo todavia no vencido.
    pedido = _pedido("ORD-000006", 9.0, "WAITING", T0)
    ahora = T0 + 5
    assert calcular_l_k1([pedido], ahora) == "SIN MUESTRA"


def test_pedido_fuera_de_ventana_15min_no_entra_en_l_k1_pero_si_en_l_k2_l_k3():
    """Un pedido creado hace mas de 15 minutos (fuera de la cohorte) no
    debe contar en L-K1, pero SI debe seguir sumando en L-K2 (backlog
    completo) y L-K3 (backlog completo) si sigue abierto y vencido."""
    viejo = _pedido("ORD-000007", 40.0, "WAITING", T0 - 1000)  # > 900s atras
    ahora = T0

    # Unico pedido, y queda fuera de la cohorte -> sin elegibles -> SIN MUESTRA
    assert calcular_l_k1([viejo], ahora) == "SIN MUESTRA"

    # Pero L-K2/L-K3 no tienen ventana de 15 min: si cuenta.
    assert calcular_l_k2([viejo], ahora) == Decimal("40.0")
    assert calcular_l_k3([viejo], ahora) == 985.0  # 1000 - 15

    # Si ademas hay un pedido reciente incumplido, L-K1 se calcula solo
    # sobre la cohorte (el viejo queda excluido del denominador).
    reciente = _pedido("ORD-000008", 5.0, "WAITING", T0 - 20)
    assert calcular_l_k1([viejo, reciente], ahora) == 100.0
    assert calcular_l_k2([viejo, reciente], ahora) == Decimal("45.0")


def test_l_k2_usa_decimal_no_float():
    """L-K2 debe devolver un Decimal, nunca un float, para evitar el
    error de redondeo binario al sumar dinero de laboratorio."""
    pedido = _pedido("ORD-000009", 0.1, "WAITING", T0)
    otro = _pedido("ORD-000010", 0.2, "WAITING", T0)
    ahora = T0 + 20

    resultado = calcular_l_k2([pedido, otro], ahora)
    assert isinstance(resultado, Decimal)
    assert resultado == Decimal("0.3")


def test_l_k2_ignora_pedidos_ready_o_no_vencidos():
    """L-K2 solo suma pedidos WAITING/PREPARING con plazo YA vencido."""
    ready = _pedido("ORD-000011", 100.0, "READY", T0, updated_at=T0 + 4)
    no_vencido = _pedido("ORD-000012", 50.0, "PREPARING", T0)
    vencido_preparing = _pedido("ORD-000013", 30.0, "PREPARING", T0)
    ahora = T0 + 10  # no_vencido/vencido_preparing: plazo aun no vence (10<15)

    assert calcular_l_k2([ready, no_vencido, vencido_preparing], ahora) == Decimal("0")

    ahora2 = T0 + 16
    assert calcular_l_k2([ready, no_vencido, vencido_preparing], ahora2) == Decimal("80.0")


def test_l_k3_solo_suma_atraso_positivo_de_pedidos_abiertos():
    """L-K3 no debe sumar pedidos READY, ni pedidos abiertos que aun no
    vencieron su plazo (atraso negativo se trata como 0)."""
    ready = _pedido("ORD-000014", 20.0, "READY", T0, updated_at=T0 + 4)
    fresco = _pedido("ORD-000015", 20.0, "WAITING", T0)
    atrasado = _pedido("ORD-000016", 20.0, "PREPARING", T0 - 25)

    ahora = T0  # 'fresco' con 0s de edad, 'atrasado' con 25s de edad

    assert calcular_l_k3([ready, fresco, atrasado], ahora) == 10.0  # 25-15


def test_l_k1_incumplidos_multiples_pedidos_mezcla():
    """Mezcla de pedidos sanos, tardios y abiertos dentro de la misma
    cohorte para validar el porcentaje agregado de L-K1."""
    sano = _pedido("ORD-000017", 10.0, "READY", T0, updated_at=T0 + 4)
    tardio = _pedido("ORD-000018", 10.0, "READY", T0, updated_at=T0 + 20)
    abierto = _pedido("ORD-000019", 10.0, "WAITING", T0)
    no_vencido_aun = _pedido("ORD-000020", 10.0, "WAITING", T0)

    ahora = T0 + 30
    # no_vencido_aun tambien esta vencido a T0+30 (30>=15), asi que en
    # este ahora los 4 pedidos son elegibles. Ajustamos: para dejar uno
    # sin vencer usamos un pedido creado justo antes de ahora.
    no_vencido_aun = _pedido("ORD-000020", 10.0, "WAITING", ahora - 5)

    pedidos = [sano, tardio, abierto, no_vencido_aun]
    # Elegibles (plazo vencido): sano, tardio, abierto -> 3
    # Incumplidos: tardio, abierto -> 2
    resultado = calcular_l_k1(pedidos, ahora)
    assert resultado == (100.0 * 2 / 3)
