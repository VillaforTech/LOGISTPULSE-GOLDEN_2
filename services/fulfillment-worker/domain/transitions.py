"""
Order status state machine
"""
from dataclasses import replace

from domain.kpis import Order


class InvalidTransition(Exception):
    pass


def start_preparation(order: Order) -> Order:
    if order.status != "WAITING":
        return order
    return replace(order, status="PREPARING")


def mark_ready(order: Order, now: float) -> Order:
    if order.status == "READY":
        return order
    if order.status != "PREPARING":
        raise InvalidTransition(f"cannot mark READY from status={order.status}")
    return replace(order, status="READY", ready_at=now)
