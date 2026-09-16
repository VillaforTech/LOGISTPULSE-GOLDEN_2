"""
KPIs logic

No DB, no Kafka, no I/O — everything takes plain Order objects and an
explicit `now` timestamp, so it can be unit tested with a fake clock
per docs/kpis-deber-01.md.

Order shape (timestamps are epoch seconds, matching time.time() as
already used in services/fulfillment-api/app.py):
    order_id:   str
    total:      float   (unidades monetarias demo — no currency implied)
    status:     "WAITING" | "PREPARING" | "READY"
    created_at: float
    ready_at:   float | None   (persisted exactly once, when READY)
"""
from dataclasses import dataclass
from typing import Iterable, Optional, Union

DEADLINE_SECONDS = 15
COHORT_WINDOW_SECONDS = 15 * 60  # 15 minutes

SIN_MUESTRA = "SIN MUESTRA"


@dataclass(frozen=True)
class Order:
    order_id: str
    total: float
    status: str
    created_at: float
    ready_at: Optional[float] = None

    @property
    def deadline(self) -> float:
        return self.created_at + DEADLINE_SECONDS

    def is_open(self) -> bool:
        return self.status in ("WAITING", "PREPARING")

    def missed_deadline(self, now: float) -> bool:
        """True if this order is (or was) late against its own deadline."""
        if self.status == "READY":
            if self.ready_at is None:
                raise ValueError(
                    f"order {self.order_id} is READY but has no ready_at — "
                    "data integrity bug upstream, not a business case"
                )
            # readyAt == deadline counts as on-time (contract choice,
            # see docs/kpis-deber-01.md case 4).
            return self.ready_at > self.deadline
        return now > self.deadline


def compute_lk1(orders: Iterable[Order], now: float) -> Union[float, str]:
    """
    L-K1 — Compromisos de preparación incumplidos.
    100 * incumplidos / elegibles, sobre la cohorte de pedidos creados
    en los últimos 15 min Y cuyo plazo ya venció. SIN_MUESTRA si vacío.
    """
    cohort_start = now - COHORT_WINDOW_SECONDS
    eligible = [
        o for o in orders
        if cohort_start < o.created_at <= now and o.deadline <= now
    ]
    if not eligible:
        return SIN_MUESTRA

    missed = [o for o in eligible if o.missed_deadline(now)]
    return 100.0 * len(missed) / len(eligible)


def compute_lk2(orders: Iterable[Order], now: float) -> float:
    """
    L-K2 — Valor comprometido en pedidos vencidos.
    Foto completa del backlog abierto y vencido (NO limitado a 15 min).
    """
    return sum(o.total for o in orders if o.is_open() and o.deadline < now)


def compute_lk3(orders: Iterable[Order], now: float) -> float:
    """
    L-K3 — Deuda acumulada de preparación, en pedido-segundos.
    """
    return sum(
        max(0.0, now - o.created_at - DEADLINE_SECONDS)
        for o in orders
        if o.is_open()
    )