"""Independent order KPI calculations. Business time is always supplied by the caller."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string with timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone is required")
    return result.timestamp()


def iso(value):
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def amount(value):
    if isinstance(value, bool):
        raise ValueError("boolean amount")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("amount must be finite and nonnegative")
    return result


def validate(event):
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    for key in ("eventId", "aggregateId"):
        if not isinstance(event.get(key), str) or not event[key].strip():
            raise ValueError(f"{key} is required")
    if type(event.get("schemaVersion")) is not int or event["schemaVersion"] != 1:
        raise ValueError("unsupported schemaVersion")
    transitions = {
        "OrderAccepted": (1, "WAITING"),
        "PreparationStarted": (2, "PREPARING"),
        "OrderReady": (3, "READY"),
    }
    kind = event.get("eventType")
    if kind not in transitions:
        raise ValueError("unknown eventType")
    version, status = transitions[kind]
    if (
        type(event.get("aggregateVersion")) is not int
        or event["aggregateVersion"] != version
    ):
        raise ValueError("aggregateVersion does not match v1 transition")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if (
        payload.get("orderId") != event["aggregateId"]
        or payload.get("status") != status
    ):
        raise ValueError("payload identity/state mismatch")
    created = timestamp(payload.get("createdAt"))
    occurred = timestamp(event.get("occurredAt"))
    if occurred < created:
        raise ValueError("event precedes creation")
    if kind in ("OrderAccepted", "OrderReady"):
        amount(payload.get("total"))
    if kind == "OrderAccepted" and occurred != created:
        raise ValueError("acceptance must use createdAt")
    if kind == "OrderReady":
        ready = timestamp(payload.get("readyAt"))
        if ready < created or ready != occurred:
            raise ValueError("readyAt must match the persisted transition")
    return event


def project(previous, event):
    payload = event["payload"]
    created = timestamp(payload["createdAt"])
    if previous is None:
        if event["aggregateVersion"] != 1:
            raise ValueError("missing acceptance")
        return {
            "orderId": event["aggregateId"],
            "version": 1,
            "status": "WAITING",
            "createdAt": created,
            "readyAt": None,
            "total": str(amount(payload["total"])),
            "deadline": created + 15,
            "expiresAt": created + 900,
            "occurredAt": timestamp(event["occurredAt"]),
        }
    if created != previous["createdAt"]:
        raise ValueError("createdAt changed")
    if "total" in payload and amount(payload["total"]) != amount(previous["total"]):
        raise ValueError("total changed")
    occurred = timestamp(event["occurredAt"])
    if occurred < previous["occurredAt"]:
        raise ValueError("transition time moved backwards")
    return dict(
        previous,
        version=event["aggregateVersion"],
        status=payload["status"],
        occurredAt=occurred,
        readyAt=timestamp(payload["readyAt"]) if "readyAt" in payload else None,
    )


def calculate(orders, now):
    # Half-open cohort: expires exactly at createdAt + 900.
    # An open order breaches strictly AFTER deadline; READY exactly at 15 is on time.
    eligible = [
        o
        for o in orders
        if o["createdAt"] <= now < o["expiresAt"] and now > o["deadline"]
    ]
    breached = [
        o for o in eligible if o["readyAt"] is None or o["readyAt"] > o["deadline"]
    ]
    overdue = [
        o
        for o in orders
        if o["status"] in ("WAITING", "PREPARING") and now > o["deadline"]
    ]
    value = sum((amount(o["total"]) for o in overdue), Decimal(0))
    debt = sum(
        (Decimal(str(now)) - Decimal(str(o["deadline"])) for o in overdue), Decimal(0)
    )
    return {
        "L-K1": {
            "value": None if not eligible else 100 * len(breached) / len(eligible),
            "unit": "percent",
            "sample": len(eligible),
            "state": "SIN MUESTRA"
            if not eligible
            else "INCUMPLIDO"
            if breached
            else "SANO",
        },
        "L-K2": {
            "value": str(value),
            "unit": "demo_money",
            "sample": len(overdue),
            "state": "INCUMPLIDO" if value > 0 else "SANO",
        },
        "L-K3": {
            "value": str(debt),
            "unit": "order_seconds",
            "sample": len(overdue),
            "state": "INCUMPLIDO" if debt > 0 else "SANO",
        },
        "counts": {
            "orders": len(orders),
            "due": len(eligible),
            "breached": len(breached),
            "overdue": len(overdue),
        },
    }
