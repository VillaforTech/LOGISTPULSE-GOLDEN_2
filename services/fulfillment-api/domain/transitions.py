"""
Order status state machine

Pure — no DB, no Kafka. Given an Order and a requested transition,
returns the new order state (or the same state, or raises), so tests
can drive it entirely with a fake clock. This is the logic
services/fulfillment-worker/app.py should call instead of blindly
UPDATE-ing status after a fixed sleep(4).
"""
from dataclasses import replace

from domain.kpis import Order


class InvalidTransition(Exception):
    pass


def start_preparation(order: Order) -> Order:
    """WAITING -> PREPARING. A duplicate/late command on a non-WAITING
    order is ignored (no-op), never raises — the contract says
    duplicates don't reopen or reprocess."""
    if order.status != "WAITING":
        return order
    return replace(order, status="PREPARING")


def mark_ready(order: Order, now: float) -> Order:
    """
    PREPARING -> READY, stamping ready_at exactly once.

    readyAt is a stopwatch you can only stop once: a duplicate call on
    an order that's already READY is a no-op and must NOT overwrite
    ready_at or re-emit the transition.
    """
    if order.status == "READY":
        return order
    if order.status != "PREPARING":
        raise InvalidTransition(f"cannot mark READY from status={order.status}")
    return replace(order, status="READY", ready_at=now)