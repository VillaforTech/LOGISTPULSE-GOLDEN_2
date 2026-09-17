"""
Unit tests

No Kafka, no Postgres — every test drives plain Order objects with an
explicit `now` you control. Mirrors the 7 mandatory cases in
docs/kpis-deber-01.md and the event rules in docs/events-deber-01.md.

Run from services/fulfillment-api/:
    pytest tests/domain_test.py -v
"""
import os

os.environ.setdefault("SKIP_DB_BOOTSTRAP", "1")

import pytest
from fastapi.testclient import TestClient

from app import app
from domain.kpis import Order, compute_lk1, compute_lk2, compute_lk3, SIN_MUESTRA
from domain.transitions import start_preparation, mark_ready, InvalidTransition
from domain.events import order_ready_event

T0 = 1_757_000_000.0  # arbitrary fixed epoch anchor, just for readability


def make_order(order_id="ord-0001", total=25.5, status="WAITING",
               created_at=T0, ready_at=None):
    return Order(order_id, total, status, created_at, ready_at)


# ---------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------

def test_happy_path_transitions():
    o = make_order(status="WAITING")
    o = start_preparation(o)
    assert o.status == "PREPARING"
    o = mark_ready(o, now=T0 + 4)
    assert o.status == "READY"
    assert o.ready_at == T0 + 4


def test_duplicate_ready_command_is_idempotent():
    """Case 5 — a second READY command must not reopen or restamp."""
    o = make_order(status="PREPARING")
    o = mark_ready(o, now=T0 + 4)
    o_again = mark_ready(o, now=T0 + 999)  # duplicate, arrives much later
    assert o_again == o  # ready_at untouched, no re-transition


def test_cannot_jump_waiting_to_ready():
    o = make_order(status="WAITING")
    with pytest.raises(InvalidTransition):
        mark_ready(o, now=T0 + 4)


def test_duplicate_start_preparation_is_ignored():
    o = make_order(status="PREPARING")
    assert start_preparation(o) == o  # no-op, doesn't raise


# ---------------------------------------------------------------------
# KPI cases — numbered to match docs/kpis-deber-01.md
# ---------------------------------------------------------------------

def test_case_1_healthy_order_not_missed():
    o = make_order(status="READY", ready_at=T0 + 4)
    now = T0 + 20
    assert compute_lk1([o], now) == 0.0
    assert compute_lk2([o], now) == 0
    assert compute_lk3([o], now) == 0


def test_case_2_late_ready_still_counts_as_missed():
    o = make_order(status="READY", ready_at=T0 + 18)  # past the 15s deadline
    assert compute_lk1([o], now=T0 + 20) == 100.0


def test_case_3_open_past_deadline_is_missed_and_costs_money():
    """Matches the reference fixture: 25.5 order, still open at T0+20s
    -> L-K1=100%, L-K2=25.5, L-K3≈5."""
    o = make_order(status="PREPARING", total=25.5)
    now = T0 + 20
    assert compute_lk1([o], now) == 100.0
    assert compute_lk2([o], now) == 25.5
    assert compute_lk3([o], now) == pytest.approx(5.0)


def test_case_4_exact_15s_boundary_counts_as_on_time():
    o = make_order(status="READY", ready_at=T0 + 15.0)
    assert compute_lk1([o], now=T0 + 15.0) == 0.0


def test_case_6_rollback_leaves_no_order():
    """Rollback means the order never existed for KPI purposes — there's
    no domain object to construct, so the "test" is that an empty
    order list behaves correctly."""
    assert compute_lk1([], now=T0) == SIN_MUESTRA
    assert compute_lk2([], now=T0) == 0
    assert compute_lk3([], now=T0) == 0


def test_case_7_no_eligible_orders_returns_sin_muestra():
    o = make_order(status="WAITING", created_at=T0)
    # deadline (T0+15) hasn't hit yet -> nothing eligible for the cohort
    assert compute_lk1([o], now=T0 + 5) == SIN_MUESTRA


def test_lk1_excludes_orders_outside_the_15min_cohort_window():
    """An order created over an hour ago is still open/late, so it must
    show up in L-K2/L-K3, but L-K1's cohort only looks at the last 15
    minutes of createdAt — so it's excluded there."""
    stale = make_order(order_id="ord-old", status="PREPARING", created_at=T0 - 3600)
    now = T0
    assert compute_lk1([stale], now) == SIN_MUESTRA
    assert compute_lk2([stale], now) == 25.5
    assert compute_lk3([stale], now) == pytest.approx(3585.0)


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------

def test_order_ready_event_refuses_to_lie():
    """An order stuck in PREPARING must never produce an OrderReady —
    this is the core 'falso verde' guard."""
    o = make_order(status="PREPARING")
    with pytest.raises(ValueError):
        order_ready_event(o, occurred_at_iso="x", created_at_iso="x", ready_at_iso="x")


def test_lk1_expires_order_at_900_second_cohort_boundary():
    expired = make_order(status="PREPARING", created_at=T0 - 900)
    assert compute_lk1([expired], now=T0) == SIN_MUESTRA


def test_lk1_includes_order_just_inside_900_second_cohort_boundary():
    current = make_order(status="PREPARING", created_at=T0 - 899.999)
    assert compute_lk1([current], now=T0) == 100.0


def test_order_ready_event_shape():
    o = make_order(status="READY", ready_at=T0 + 4)
    evt = order_ready_event(
        o,
        occurred_at_iso="2026-09-14T00:00:04Z",
        created_at_iso="2026-09-14T00:00:00Z",
        ready_at_iso="2026-09-14T00:00:04Z",
    )
    assert evt["eventType"] == "OrderReady"
    assert evt["aggregateId"] == o.order_id
    assert evt["aggregateVersion"] == 3
    assert evt["schemaVersion"] == 1
    assert evt["payload"]["total"] == 25.5
    assert evt["payload"]["readyAt"] == "2026-09-14T00:00:04Z"


def test_create_order_emits_domain_event_contract(monkeypatch):
    class FakeConn:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            self.statements.append((args, kwargs))
            return None

        def commit(self):
            return None

    connection = FakeConn()
    monkeypatch.setattr("app.conn", lambda: connection)

    client = TestClient(app)
    resp = client.post("/api/fulfillment/orders", json={"storeId": "STORE-042", "channel": "CI", "total": 25.5})

    assert resp.status_code == 201
    outbox_args = next(args for args, _ in connection.statements if "INSERT INTO outbox" in args[0])
    outbox_values = outbox_args[1]
    assert len(outbox_values) == 14
    assert outbox_values[1] == "logistpulse.orders"
    assert outbox_values[8] == "logistpulse.fulfillment.events.v1"
    assert outbox_values[0] != outbox_values[7]


def test_get_order_by_id_returns_persistent_ready_at_and_version(monkeypatch):
    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            return self

        def fetchone(self):
            return ("ORD-0001", "STORE-042", "CI", 25.5, "READY", T0, T0 + 4, T0 + 4, 3)

    monkeypatch.setattr("app.conn", lambda: FakeConn())

    response = TestClient(app).get("/api/fulfillment/orders/ORD-0001")

    assert response.status_code == 200
    assert response.json() == {
        "orderId": "ORD-0001",
        "storeId": "STORE-042",
        "channel": "CI",
        "total": 25.5,
        "status": "READY",
        "createdAt": T0,
        "updatedAt": T0 + 4,
        "readyAt": T0 + 4,
        "aggregateVersion": 3,
    }