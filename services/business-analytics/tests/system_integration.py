"""Verify the real Fulfillment producer feeds the durable analytics projection.

Run this against the root Compose stack plus ``compose.analytics.yaml``. The
test creates only its own order through the public API and reads analytics
through its documented HTTP endpoint and private SQLite projection.
"""

import argparse
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = [
    "compose",
    "-f",
    str(ROOT / "compose.yaml"),
    "-f",
    str(ROOT / "compose.analytics.yaml"),
]
TIMESTAMP_SERIALIZATION_TOLERANCE_SECONDS = 0.00001


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_json(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def run_command(command, *, input_text=None):
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
        timeout=120,
    ).stdout


def analytics_json(docker, path):
    code = (
        "import json,sys,urllib.request;"
        "print(json.dumps(json.load(urllib.request.urlopen("
        "'http://localhost:8000'+sys.argv[1],timeout=5))))"
    )
    output = run_command(
        [
            docker,
            *COMPOSE,
            "exec",
            "-T",
            "business-analytics",
            "python",
            "-c",
            code,
            path,
        ]
    )
    return json.loads(output)


def projection_rows(docker, order_id):
    code = """
import json, os, sqlite3, sys
db = sqlite3.connect(os.environ['ANALYTICS_DB'])
db.row_factory = sqlite3.Row
order = db.execute('SELECT body FROM orders WHERE id=?', (sys.argv[1],)).fetchone()
events = db.execute(
    'SELECT version,body,applied FROM inbox WHERE aggregate_id=? ORDER BY version',
    (sys.argv[1],),
).fetchall()
print(json.dumps({
    'order': json.loads(order['body']) if order else None,
    'events': [dict(version=row['version'], event=json.loads(row['body']), applied=row['applied']) for row in events],
}))
"""
    output = run_command(
        [
            docker,
            *COMPOSE,
            "exec",
            "-T",
            "business-analytics",
            "python",
            "-c",
            code,
            order_id,
        ]
    )
    return json.loads(output)


def until(callback, timeout=35):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = callback()
            if last:
                return last
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(0.2)
    raise AssertionError(f"condition timed out; last observation={last!r}")


def run(docker, base_url):
    evidence = {
        "scope": "real Fulfillment API/outbox/relay -> Redpanda -> Business Analytics",
        "startedAt": utc_now(),
        "checks": [],
    }

    def record(name, observed):
        evidence["checks"].append({"name": name, "observed": observed})
        print(json.dumps({"passed": name, "observed": observed}), flush=True)

    initial = until(
        lambda: s if (s := analytics_json(docker, "/snapshot")).get("valid") else None
    )
    record("analytics starts with complete current coverage", initial["coverage"])

    created = request_json(
        f"{base_url}/api/fulfillment/orders",
        {"storeId": "STORE-042", "channel": "ANALYTICS-INTEGRATION", "total": 25.5},
    )
    order_id = created["orderId"]
    source = until(
        lambda: (
            o
            if (o := request_json(f"{base_url}/api/fulfillment/orders/{order_id}")).get(
                "status"
            )
            == "READY"
            and o.get("readyAt") is not None
            else None
        ),
        25,
    )
    projected = until(
        lambda: (
            p
            if (p := projection_rows(docker, order_id)).get("order", {}).get("version")
            == 3
            and len(p.get("events", [])) == 3
            else None
        ),
        25,
    )

    versions = [row["version"] for row in projected["events"]]
    types = [row["event"]["eventType"] for row in projected["events"]]
    assert versions == [1, 2, 3]
    assert types == ["OrderAccepted", "PreparationStarted", "OrderReady"]
    assert all(row["applied"] == 1 for row in projected["events"])
    assert all(row["event"]["aggregateId"] == order_id for row in projected["events"])
    assert all(row["event"]["schemaVersion"] == 1 for row in projected["events"])
    record(
        "real producer emitted the complete versioned event sequence",
        {"orderId": order_id, "versions": versions, "types": types},
    )

    projection = projected["order"]
    assert projection["status"] == source["status"] == "READY"
    assert (
        Decimal(projection["total"]) == Decimal(str(source["total"])) == Decimal("25.5")
    )
    assert (
        abs(projection["createdAt"] - source["createdAt"])
        <= TIMESTAMP_SERIALIZATION_TOLERANCE_SECONDS
    )
    assert (
        abs(projection["readyAt"] - source["readyAt"])
        <= TIMESTAMP_SERIALIZATION_TOLERANCE_SECONDS
    )
    assert 0 <= source["readyAt"] - source["createdAt"] <= 15
    record(
        "projection agrees with the exact source order",
        {
            "status": projection["status"],
            "total": projection["total"],
            "createdAtDeltaSeconds": abs(projection["createdAt"] - source["createdAt"]),
            "readyAtDeltaSeconds": abs(projection["readyAt"] - source["readyAt"]),
        },
    )

    before = until(
        lambda: (
            s
            if (s := analytics_json(docker, "/snapshot")).get("valid")
            and s.get("freshness", {}).get("lag") == 0
            else None
        )
    )
    duplicate_count = before["diagnostics"]["duplicates"]
    run_command([docker, *COMPOSE, "restart", "business-analytics"])
    after = until(
        lambda: (
            s
            if (s := analytics_json(docker, "/snapshot")).get("valid")
            and s["revision"] > before["revision"]
            else None
        ),
        45,
    )
    recovered = projection_rows(docker, order_id)
    assert recovered["order"] == projection
    assert len(recovered["events"]) == 3
    assert after["diagnostics"]["duplicates"] == duplicate_count
    record(
        "restart resumes from the durable checkpoint without duplication",
        {
            "revisionBefore": before["revision"],
            "revisionAfter": after["revision"],
            "duplicates": duplicate_count,
        },
    )

    evidence["finishedAt"] = utc_now()
    evidence["passed"] = True
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.docker, args.base_url.rstrip("/"))
    except Exception as error:
        result = {
            "scope": "producer to analytics",
            "finishedAt": utc_now(),
            "passed": False,
            "error": str(error),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
