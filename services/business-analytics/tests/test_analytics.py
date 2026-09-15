import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from analytics.app import create_app, fresh_view, metrics
from analytics.domain import iso, timestamp
from analytics.store import Store

T0 = timestamp("2026-01-01T00:00:00Z")


def event(version=1, order_id="one", ready=4, total="25.5"):
    kind, status = {
        1: ("OrderAccepted", "WAITING"),
        2: ("PreparationStarted", "PREPARING"),
        3: ("OrderReady", "READY"),
    }[version]
    payload = {"orderId": order_id, "createdAt": iso(T0), "status": status}
    if version != 2:
        payload["total"] = total
    if version == 3:
        payload["readyAt"] = iso(T0 + ready)
    return {
        "eventId": f"{order_id}-{version}",
        "eventType": kind,
        "schemaVersion": 1,
        "aggregateId": order_id,
        "aggregateVersion": version,
        "occurredAt": iso(T0 + (0 if version == 1 else 1 if version == 2 else ready)),
        "payload": payload,
    }


@pytest.fixture
def store(tmp_path):
    db = Store(str(tmp_path / "state.sqlite"), iso(T0))
    yield db
    db.close()


def publish(store, elapsed=20, **kwargs):
    return store.publish(
        T0 + elapsed,
        connected=True,
        caught_up=True,
        last_poll=T0 + elapsed,
        lag=0,
        **kwargs,
    )


def values(snapshot):
    return [snapshot["kpis"][k]["value"] for k in ("L-K1", "L-K2", "L-K3")]


def test_acceptance_open_order_and_time_only_expiration(store):
    store.ingest(event())
    assert values(publish(store, 10)) == [None, "0", "0"]
    assert values(publish(store, 20)) == [100, "25.5", "5.0"]
    expired = publish(store, 900)
    assert expired["kpis"]["L-K1"]["state"] == "SIN MUESTRA"
    assert values(expired)[1:] == ["25.5", "885.0"]


@pytest.mark.parametrize(
    "ready,expected", [(4, 0), (15, 0), (15.000001, 100), (18, 100)]
)
def test_ready_boundary_and_late_completion(store, ready, expected):
    for version in (1, 2, 3):
        store.ingest(event(version, ready=ready))
    assert values(publish(store, 20)) == [expected, "0", "0"]


@pytest.mark.parametrize(
    "elapsed,expected", [(14.999, None), (15, None), (15.001, 100)]
)
def test_open_deadline_boundary(store, elapsed, expected):
    store.ingest(event())
    assert values(publish(store, elapsed))[0] == expected


def test_late_delivery_corrects_provisional_alert_and_keeps_journal(store):
    store.ingest(event(1))
    store.ingest(event(2))
    before = publish(store, 20)
    assert before["alerts"]["L-K1"]["active"] is True
    store.ingest(event(3, ready=4))
    after = publish(store, 21)
    assert values(after) == [0, "0", "0"]
    assert after["alerts"]["L-K1"]["active"] is False
    assert after["lastEventId"] == "one-3"
    assert after["diagnostics"]["lastEventOccurredAt"] == iso(T0 + 4)
    assert after["revision"] > before["revision"]
    assert store.updates(0) == [before, after]


def test_out_of_order_is_incomplete_then_recovers(store):
    store.ingest(event(3))
    first = publish(store)
    assert first["quality"] == "INCOMPLETO"
    assert first["coverage"]["pendingEvents"] == 1
    store.ingest(event(1))
    assert publish(store)["quality"] == "INCOMPLETO"
    store.ingest(event(2))
    final = publish(store)
    assert final["quality"] == "ACTUAL"
    assert values(final) == [0, "0", "0"]


def test_duplicates_and_old_versions_do_not_reopen_order(store):
    for version in (1, 2, 3, 1, 3, 2):
        store.ingest(event(version))
    result = publish(store)
    assert result["diagnostics"]["duplicates"] == 3
    assert result["kpis"]["counts"]["orders"] == 1
    assert values(result) == [0, "0", "0"]


def test_same_event_id_changed_content_is_visible(store):
    store.ingest(event())
    changed = event(total="99")
    store.ingest(changed)
    result = publish(store)
    assert result["quality"] == "INCOMPLETO"
    assert result["coverage"]["schemaErrors"] == 1
    assert values(result)[1] == "25.5"


def test_conflicting_version_different_identity_is_visible(store):
    store.ingest(event())
    changed = event()
    changed["eventId"] = "different"
    store.ingest(changed)
    assert publish(store)["coverage"]["schemaErrors"] == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(schemaVersion=2),
        lambda e: e.update(schemaVersion=True),
        lambda e: e.update(aggregateVersion=True),
        lambda e: e.update(eventType="Other"),
        lambda e: e["payload"].update(orderId="wrong"),
        lambda e: e["payload"].update(createdAt="2026-01-01"),
        lambda e: e["payload"].update(total="NaN"),
        lambda e: e["payload"].update(total=True),
    ],
)
def test_schema_failure_is_durable_and_never_healthy(store, mutate):
    changed = event()
    mutate(changed)
    store.ingest(changed, partition=2, offset=42)
    result = publish(store)
    assert result["coverage"]["schemaErrors"] == 1
    assert result["quality"] == "INCOMPLETO"
    assert result["alerts"]["L-K1"]["active"] is None
    assert store.checkpoint(2) == 43


def test_malformed_json_and_kafka_key(store):
    store.ingest("{broken")
    store.ingest(event(), key="wrong")
    assert publish(store)["coverage"]["schemaErrors"] == 2


def test_atomic_rollback_before_checkpoint(store):
    with patch.object(
        store, "_drain", side_effect=RuntimeError("simulated disk error")
    ):
        with pytest.raises(RuntimeError):
            store.ingest(event(), partition=0, offset=7)
    assert store.checkpoint(0) is None
    assert publish(store)["kpis"]["counts"]["orders"] == 0
    store.ingest(event(), offset=7)
    assert store.checkpoint(0) == 8


def test_restart_after_persistence_before_kafka_commit(tmp_path):
    path = str(tmp_path / "restart.sqlite")
    original = Store(path, iso(T0))
    original.ingest(event(), offset=0)
    initial = publish(original, 10)
    original.close()
    resumed = Store(path, iso(T0))
    try:
        assert resumed.checkpoint(0) == 1
        resumed.ingest(event(), offset=0)
        result = publish(resumed, 20)
        assert values(result) == [100, "25.5", "5.0"]
        assert result["revision"] > initial["revision"]
        assert result["diagnostics"]["duplicates"] == 1
    finally:
        resumed.close()


def test_replay_new_database_matches_independent_expected_population(tmp_path, store):
    data = [
        event(1, "a"),
        event(2, "a"),
        event(3, "a", ready=18),
        event(1, "b", total="0.10"),
        event(1, "c", total="0.20"),
    ]
    for item in data:
        store.ingest(item)
    baseline = publish(store)
    other = Store(str(tmp_path / "replay.sqlite"), iso(T0))
    try:
        for item in reversed(data + data):
            other.ingest(item)
        replayed = publish(other)
        assert replayed["kpis"] == baseline["kpis"]
        # Independent oracle: all three due, all breached; only b+c still open.
        assert values(replayed) == [100, "0.30", "10.0"]
    finally:
        other.close()


def test_no_coverage_is_not_empty_healthy_population(tmp_path):
    db = Store(str(tmp_path / "unknown.sqlite"))
    try:
        assert publish(db)["quality"] == "INCOMPLETO"
    finally:
        db.close()


def test_coverage_identity_cannot_silently_change(tmp_path):
    path = str(tmp_path / "fixed.sqlite")
    db = Store(path, iso(T0))
    db.close()
    with pytest.raises(ValueError, match="immutable"):
        Store(path, iso(T0 + 1))


def test_history_loss_stays_visible_after_restart(tmp_path):
    path = str(tmp_path / "missing.sqlite")
    db = Store(path, iso(T0))
    db.mark_history_missing()
    db.close()
    db = Store(path)
    try:
        assert publish(db)["quality"] == "INCOMPLETO"
        assert publish(db)["coverage"]["historyMissing"]
    finally:
        db.close()


def test_stale_or_disconnected_does_not_resolve_business_alert(store):
    store.ingest(event())
    publish(store)
    result = store.publish(T0 + 21, connected=False)
    assert result["quality"] == "DESACTUALIZADO"
    assert result["alerts"]["L-K1"]["active"] is None
    assert "logistpulse_overdue_order_value NaN" in metrics(result).decode()


def test_future_transition_not_healthy(store):
    store.ingest(event())
    assert publish(store, -1)["quality"] == "INCOMPLETO"


def test_exact_decimal_and_more_than_twenty_orders(store):
    for i in range(25):
        store.ingest(event(order_id=str(i), total="0.01"))
    result = publish(store)
    assert values(result) == [100, "0.25", "125.0"]
    assert result["kpis"]["counts"]["due"] == 25


def test_liveness_readiness_bootstrap_and_paged_updates(store):
    store.ingest(event())
    first = publish(store)
    second = publish(store, 21)
    with patch("analytics.app.time.time", return_value=T0 + 21):
        with TestClient(create_app(store, run_consumer=False)) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/ready").status_code == 200
            assert client.get("/snapshot").json() == second
            assert client.get("/updates?after=0&limit=1").json()["snapshots"] == [first]
            assert client.get(f"/updates?after={first['revision']}").json()[
                "snapshots"
            ] == [second]
            assert client.get("/updates?after=-1").status_code == 422
            assert client.get("/metrics").status_code == 200
    stale = fresh_view(store, T0 + 25)
    assert not stale["valid"]
    assert stale["quality"] == "DESACTUALIZADO"
    assert store.latest()["valid"]  # The persisted revision is immutable.


def test_health_up_does_not_imply_ready(store):
    store.publish(T0)
    with patch("analytics.app.time.time", return_value=T0):
        with TestClient(create_app(store, run_consumer=False)) as client:
            assert client.get("/health").json()["status"] == "UP"
            assert client.get("/ready").status_code == 503


def test_real_process_exit_after_commit_before_acknowledgement(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    path = str(tmp_path / "crash.sqlite")
    payload = json.dumps(event())
    program = (
        "import os,sys,json; from analytics.store import Store; "
        "s=Store(sys.argv[1],sys.argv[2]); "
        "s.ingest(json.loads(sys.argv[3]),offset=12); os._exit(23)"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, path, iso(T0), payload],
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 23
    recovered = Store(path, iso(T0))
    try:
        assert recovered.checkpoint(0) == 13
        recovered.ingest(event(), offset=12)
        snapshot = publish(recovered)
        assert values(snapshot) == [100, "25.5", "5.0"]
        assert snapshot["diagnostics"]["duplicates"] == 1
    finally:
        recovered.close()


def test_invalid_pending_transition_remains_visible_after_redelivery(store):
    ready = event(3)
    ready["payload"]["total"] = "99"
    for item in (ready, event(1), event(2)):
        store.ingest(item)
    first = publish(store)
    assert first["quality"] == "INCOMPLETO"
    assert first["dataRevision"] == 3
    store.ingest(ready)
    second = publish(store)
    assert second["quality"] == "INCOMPLETO"
    assert second["coverage"]["schemaErrors"] > 0
    assert second["kpis"]["counts"]["overdue"] == 1
