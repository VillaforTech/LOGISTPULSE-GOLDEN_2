import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import (
    CollectorRegistry,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

from .domain import timestamp
from .runtime import Runtime
from .store import Store


def fresh_view(store, now=None):
    result = store.latest()
    now = time.time() if now is None else now
    if result and now - timestamp(result["generatedAt"]) > 3:
        result["quality"] = "DESACTUALIZADO"
        result["valid"] = False
        for alert in result["alerts"].values():
            alert.update(active=None, quality="DESACTUALIZADO")
    return result


def metrics(snapshot):
    registry = CollectorRegistry()
    valid = snapshot.get("valid", False)
    kpis = snapshot.get("kpis", {})
    counts = kpis.get("counts", {})
    values = {
        "logistpulse_orders_due_window": counts.get("due", 0),
        "logistpulse_orders_breached_window": counts.get("breached", 0),
        "logistpulse_overdue_order_value": kpis.get("L-K2", {}).get("value", 0),
        "logistpulse_preparation_debt_seconds": kpis.get("L-K3", {}).get("value", 0),
    }
    for name, value in values.items():
        Gauge(
            name,
            "Derived business value; NaN when projection is not valid",
            registry=registry,
        ).set(float(value) if valid else float("nan"))
    diagnostics = snapshot.get("diagnostics", {})
    coverage = snapshot.get("coverage", {})
    operational = {
        "logistpulse_analytics_valid": int(valid),
        "logistpulse_analytics_revision": snapshot.get("revision", 0),
        "logistpulse_analytics_duplicates": diagnostics.get("duplicates", 0),
        "logistpulse_analytics_pending_events": coverage.get("pendingEvents", 0),
        "logistpulse_analytics_schema_errors": coverage.get("schemaErrors", 0),
        "logistpulse_analytics_timer_delay_seconds": diagnostics.get(
            "timerDelaySeconds", 0
        ),
        "logistpulse_analytics_last_event_timestamp_seconds": (
            timestamp(diagnostics["lastEventOccurredAt"])
            if diagnostics.get("lastEventOccurredAt")
            else None
        ),
        "logistpulse_analytics_lag": snapshot.get("freshness", {}).get("lag"),
    }
    for name, value in operational.items():
        Gauge(name, name, registry=registry).set(
            float(value) if value is not None else float("nan")
        )
    return generate_latest(registry)


def create_app(existing_store=None, run_consumer=True):
    @asynccontextmanager
    async def lifespan(app):
        store = existing_store or Store(
            os.getenv("ANALYTICS_DB", "/data/analytics.sqlite"),
            os.getenv("ANALYTICS_COVERAGE_FROM"),
        )
        runtime = Runtime(store) if run_consumer else None
        app.state.store = store
        if runtime:
            runtime.start()
        try:
            yield
        finally:
            if runtime:
                runtime.close()
            if existing_store is None:
                store.close()

    app = FastAPI(
        title="LogistPulse Business Analytics", version="1.0.0", lifespan=lifespan
    )

    @app.get("/health")
    def health():
        snapshot = fresh_view(app.state.store)
        return {
            "status": "UP",
            "service": "business-analytics",
            "projection": snapshot.get("quality", "INCOMPLETO"),
        }

    @app.get("/ready")
    def ready():
        snapshot = fresh_view(app.state.store)
        return JSONResponse(
            {
                "status": "UP" if snapshot.get("valid") else "NOT_READY",
                "projection": snapshot.get("quality", "INCOMPLETO"),
            },
            status_code=200 if snapshot.get("valid") else 503,
        )

    @app.get("/snapshot")
    def snapshot():
        return fresh_view(app.state.store)

    @app.get("/updates")
    def updates(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
        batch = app.state.store.updates(after, limit)
        return {
            "snapshots": batch,
            "nextRevision": batch[-1]["revision"] if batch else after,
        }

    @app.get("/stream")
    async def stream(after: int = Query(0, ge=0)):
        async def frames():
            cursor = after
            while True:
                batch = app.state.store.updates(cursor)
                for snapshot in batch:
                    cursor = snapshot["revision"]
                    yield f"id: {cursor}\nevent: snapshot\ndata: {json.dumps(snapshot)}\n\n"
                if not batch:
                    yield ": keepalive; freshness comes from generatedAt\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/metrics")
    def prometheus():
        return Response(
            metrics(fresh_view(app.state.store)), media_type=CONTENT_TYPE_LATEST
        )

    return app


app = create_app()
