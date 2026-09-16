"""
Event envelope builders for the logistpulse.fulfillment.events.v1 contract
(see docs/events-deber-01.md). Pure functions — building a dict isn't I/O,
so these are unit-testable without a running Redpanda broker. The actual
KafkaProducer.send(TOPIC, event) call belongs in app.py/worker, not here.
"""
import uuid
from typing import Optional

from domain.kpis import Order

SCHEMA_VERSION = 1
TOPIC = "logistpulse.fulfillment.events.v1"


def _envelope(event_type: str, order: Order, aggregate_version: int,
              occurred_at_iso: str, payload: dict,
              event_id: Optional[str] = None) -> dict:
    return {
        "eventId": event_id or str(uuid.uuid4()),
        "eventType": event_type,
        "schemaVersion": SCHEMA_VERSION,
        "aggregateId": order.order_id,
        "aggregateVersion": aggregate_version,
        "occurredAt": occurred_at_iso,
        "payload": payload,
    }


def order_accepted_event(order: Order, occurred_at_iso: str,
                          event_id: Optional[str] = None) -> dict:
    return _envelope("OrderAccepted", order, 1, occurred_at_iso, {
        "orderId": order.order_id,
        "total": order.total,
        "createdAt": occurred_at_iso,
        "status": "WAITING",
    }, event_id)


def preparation_started_event(order: Order, occurred_at_iso: str,
                               created_at_iso: str,
                               event_id: Optional[str] = None) -> dict:
    return _envelope("PreparationStarted", order, 2, occurred_at_iso, {
        "orderId": order.order_id,
        "createdAt": created_at_iso,
        "status": "PREPARING",
    }, event_id)


def order_ready_event(order: Order, occurred_at_iso: str, created_at_iso: str,
                       ready_at_iso: str, event_id: Optional[str] = None) -> dict:
    """
    Refuses to build an OrderReady event unless the order is actually,
    persistently READY. An event describes only what was persisted —
    never fabricate a READY because a message was consumed or a 201
    was returned.
    """
    if order.status != "READY" or order.ready_at is None:
        raise ValueError("cannot build OrderReady for an order that isn't actually READY")
    return _envelope("OrderReady", order, 3, occurred_at_iso, {
        "orderId": order.order_id,
        "createdAt": created_at_iso,
        "readyAt": ready_at_iso,
        "total": order.total,
        "status": "READY",
    }, event_id)