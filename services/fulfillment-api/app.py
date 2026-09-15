from datetime import datetime, timezone
import json
import os
import time
import uuid

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from kafka import KafkaProducer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

from domain.events import order_accepted_event
from domain.kpis import Order

REQ = Counter("logistpulse_http_requests_total", "HTTP requests", ["service", "method", "path", "status"])
LAT = Histogram("logistpulse_http_request_duration_seconds", "HTTP latency", ["service", "path"])


def instrument(app, service):
    @app.middleware("http")
    async def metrics(request: Request, call_next):
        started = time.time()
        response = await call_next(request)
        elapsed = time.time() - started
        path = request.url.path
        REQ.labels(service, request.method, path, str(response.status_code)).inc()
        LAT.labels(service, path).observe(elapsed)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics_endpoint():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app = FastAPI(title="LOGISTPULSE Fulfillment API", version="1.0.0")
instrument(app, "fulfillment-api")
DB = os.getenv("FULFILLMENT_DB_URL", "postgresql://logist:logist_demo@postgres:5432/fulfillment_db")
KAFKA = os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
OUTBOX_TABLE = "outbox"


def conn():
    return psycopg.connect(DB)


def bootstrap():
    if os.getenv("SKIP_DB_BOOTSTRAP", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    for _ in range(5):
        try:
            with conn() as c:
                c.execute(
                    "CREATE TABLE IF NOT EXISTS orders(order_id text primary key, store_id text, channel text, total numeric, status text, created_at numeric, updated_at numeric, ready_at numeric, aggregate_version integer NOT NULL DEFAULT 1)"
                )
                c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS ready_at numeric")
                c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS aggregate_version integer NOT NULL DEFAULT 1")
                c.execute(
                    "CREATE TABLE IF NOT EXISTS outbox(event_id text primary key, topic text NOT NULL, aggregate_id text NOT NULL, aggregate_version integer NOT NULL, payload jsonb NOT NULL, created_at numeric NOT NULL, published_at numeric, attempts integer NOT NULL DEFAULT 0, next_attempt_at numeric NOT NULL)"
                )
                c.commit()
                return
        except Exception:
            time.sleep(1)


@app.on_event("startup")
def startup():
    bootstrap()


if __name__ == "__main__":
    bootstrap()


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NewOrder(BaseModel):
    storeId: str = "STORE-042"
    channel: str = "MOBILE"
    total: float = 18.50


@app.get('/health')
def health():
    return {'status': 'UP', 'service': 'fulfillment-api'}


@app.get('/api/fulfillment/orders')
def orders():
    with conn() as c:
        rows = c.execute(
            "SELECT order_id,store_id,channel,total,status,created_at,updated_at,ready_at,aggregate_version FROM orders ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return [
        {'orderId': r[0], 'storeId': r[1], 'channel': r[2], 'total': float(r[3]), 'status': r[4], 'createdAt': r[5], 'updatedAt': r[6], 'readyAt': r[7], 'aggregateVersion': r[8]}
        for r in rows
    ]


@app.get('/api/fulfillment/orders/{order_id}')
def order_by_id(order_id: str):
    with conn() as c:
        row = c.execute(
            "SELECT order_id,store_id,channel,total,status,created_at,updated_at,ready_at,aggregate_version FROM orders WHERE order_id=%s",
            (order_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Order not found')
    return {'orderId': row[0], 'storeId': row[1], 'channel': row[2], 'total': float(row[3]), 'status': row[4], 'createdAt': row[5], 'updatedAt': row[6], 'readyAt': row[7], 'aggregateVersion': row[8]}


@app.post('/api/fulfillment/orders', status_code=201)
def create(o: NewOrder):
    oid = 'ORD-' + uuid.uuid4().hex[:6].upper()
    now = time.time()
    order = Order(order_id=oid, total=float(o.total), status='WAITING', created_at=now)
    accepted = order_accepted_event(order, iso_utc(now))
    command = {
        "eventId": str(uuid.uuid4()),
        "orderId": oid,
        "event": "ORDER_CREATED",
        "storeId": o.storeId,
    }
    with conn() as c:
        c.execute(
            "INSERT INTO orders (order_id,store_id,channel,total,status,created_at,updated_at,ready_at,aggregate_version) VALUES (%s,%s,%s,%s,'WAITING',%s,%s,NULL,1)",
            (oid, o.storeId, o.channel, o.total, now, now),
        )
        c.execute(
            "INSERT INTO outbox (event_id,topic,aggregate_id,aggregate_version,payload,created_at,next_attempt_at) VALUES (%s,%s,%s,%s,%s,%s,%s),(%s,%s,%s,%s,%s,%s,%s)",
            (command["eventId"], "logistpulse.orders", oid, 1, json.dumps(command), now, now,
             accepted["eventId"], "logistpulse.fulfillment.events.v1", oid, 1, json.dumps(accepted), now, now),
        )
        c.commit()
    return {'orderId': oid, 'status': 'WAITING', 'aggregateVersion': 1}

