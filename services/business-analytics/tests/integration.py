"""Real broker/API/restart acceptance for the isolated compose.test.yaml only.
Run after compose up, against an empty component test volume. Does not touch the shared lab.
"""

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]


def iso(value):
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def event(order_id, version, created, ready=None):
    kind, status = {
        1: ("OrderAccepted", "WAITING"),
        2: ("PreparationStarted", "PREPARING"),
        3: ("OrderReady", "READY"),
    }[version]
    payload = {"orderId": order_id, "createdAt": iso(created), "status": status}
    if version != 2:
        payload["total"] = "25.5"
    if version == 3:
        payload["readyAt"] = iso(ready)
    return {
        "eventId": f"{order_id}-{version}",
        "aggregateId": order_id,
        "aggregateVersion": version,
        "eventType": kind,
        "schemaVersion": 1,
        "occurredAt": iso(created if version != 3 else ready),
        "payload": payload,
    }


def run(docker):
    evidence = {
        "scope": "isolated component; fixture publisher, not Fulfillment API or Grafana",
        "startedAt": iso(time.time()),
        "checks": [],
    }
    compose_args = [docker, "compose", "-f", str(ROOT / "compose.test.yaml")]

    def compose(*args, data=None):
        return subprocess.run(
            compose_args + list(args),
            input=data,
            text=True,
            capture_output=True,
            check=True,
            timeout=90,
        )

    def snapshot():
        with urllib.request.urlopen(
            "http://127.0.0.1:18080/snapshot", timeout=3
        ) as response:
            return json.load(response)

    def until(predicate, timeout=35):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = snapshot()
                if predicate(last):
                    return last
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        raise AssertionError(f"condition timed out, last snapshot: {last}")

    def send(events):
        code = (
            "import sys,json; from kafka import KafkaProducer; "
            "p=KafkaProducer(bootstrap_servers='broker:9092',acks='all',"
            "value_serializer=lambda v:json.dumps(v).encode()); "
            "events=json.load(sys.stdin); "
            "[p.send('logistpulse.fulfillment.events.v1',key=e['aggregateId'].encode(),"
            "value=e).get(timeout=10) for e in events]; p.close()"
        )
        compose(
            "exec", "-T", "analytics", "python", "-c", code, data=json.dumps(events)
        )

    def record(name, data):
        evidence["checks"].append({"name": name, "observed": data})
        print(json.dumps({"passed": name, "observed": data}), flush=True)

    initial = until(lambda s: s.get("valid"))
    if initial["kpis"]["counts"]["orders"]:
        raise AssertionError(
            "requires an empty dedicated test volume; existing data is preserved"
        )
    record("fresh empty population", initial["kpis"]["L-K1"])
    created = time.time()
    accepted = event("integration-open", 1, created)
    preparing = event("integration-open", 2, created)
    send([accepted, preparing])
    overdue = until(
        lambda s: s.get("valid") and s["kpis"]["counts"]["breached"] == 1, 25
    )
    observed_at = datetime.fromisoformat(
        overdue["generatedAt"].replace("Z", "+00:00")
    ).timestamp()
    delay = observed_at - created - 15
    assert 0 < delay <= 1, delay
    record("deadline without new events within one second", {"delaySeconds": delay})
    sample = until(
        lambda s: datetime.fromisoformat(
            s["generatedAt"].replace("Z", "+00:00")
        ).timestamp()
        >= created + 20
    )
    at = datetime.fromisoformat(
        sample["generatedAt"].replace("Z", "+00:00")
    ).timestamp()
    assert sample["kpis"]["L-K1"]["value"] == 100
    assert Decimal(sample["kpis"]["L-K2"]["value"]) == Decimal("25.5")
    assert abs(float(sample["kpis"]["L-K3"]["value"]) - (at - created - 15)) < 0.001
    record("25.5 overdue fixture at >=20s", sample["kpis"])

    send([accepted, preparing])
    duplicated = until(lambda s: s["diagnostics"]["duplicates"] == 2)
    assert duplicated["kpis"]["counts"]["orders"] == 1
    record("broker duplicate delivery", duplicated["diagnostics"])

    send([event("integration-open", 3, created, created + 18)])
    completed = until(lambda s: s["kpis"]["counts"]["overdue"] == 0)
    assert completed["kpis"]["L-K1"]["value"] == 100
    record("late READY preserves breach, clears backlog", completed["kpis"])

    created2 = time.time()
    send([event("integration-restart", 1, created2)])
    persisted = until(lambda s: s["kpis"]["counts"]["orders"] == 2)
    compose("restart", "analytics")
    restarted = until(
        lambda s: s.get("valid") and s["revision"] > persisted["revision"]
    )
    assert restarted["kpis"]["counts"]["orders"] == 2
    timed = until(lambda s: s.get("valid") and s["kpis"]["counts"]["overdue"] == 1, 25)
    record(
        "restart restores pending deadline and revisions",
        {
            "before": persisted["revision"],
            "after": timed["revision"],
            "kpis": timed["kpis"],
        },
    )

    compose("stop", "broker")
    try:
        stale = until(lambda s: s["quality"] == "DESACTUALIZADO", 20)
        assert stale["valid"] is False
        assert stale["alerts"]["L-K1"]["active"] is None
        record("broker outage is visibly stale", stale["quality"])
    finally:
        compose("start", "broker")
    recovered = until(lambda s: s.get("valid"), 45)
    assert recovered["kpis"]["counts"]["orders"] == 2
    record("broker recovery has no double count", recovered["kpis"]["counts"])

    # Fill the missing revision only after observing INCOMPLETO.
    created3 = time.time() - 5
    send([event("integration-reordered", 3, created3, created3 + 4)])
    incomplete = until(lambda s: s["quality"] == "INCOMPLETO")
    assert incomplete["coverage"]["pendingEvents"] == 1
    send(
        [
            event("integration-reordered", 1, created3),
            event("integration-reordered", 2, created3),
        ]
    )
    repaired = until(lambda s: s.get("valid") and s["kpis"]["counts"]["orders"] == 3)
    record("out-of-order history repaired", repaired["coverage"])
    with urllib.request.urlopen(
        "http://127.0.0.1:18080/updates?after="
        + str(persisted["revision"])
        + "&limit=1000"
    ) as response:
        revisions = [s["revision"] for s in json.load(response)["snapshots"]]
    assert revisions and revisions[0] == persisted["revision"] + 1
    assert revisions == list(range(revisions[0], revisions[-1] + 1))
    record(
        "adapter can recover uninterrupted revision journal",
        {"revisions": len(revisions)},
    )
    evidence["finishedAt"] = iso(time.time())
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.docker)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
