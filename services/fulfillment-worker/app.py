import json
import os
import time
from datetime import datetime, timezone

import psycopg
from kafka import KafkaConsumer, KafkaProducer

from domain.events import order_ready_event, preparation_started_event
from domain.kpis import Order
from domain.transitions import mark_ready, start_preparation

DB = os.getenv('FULFILLMENT_DB_URL', 'postgresql://logist:logist_demo@postgres:5432/fulfillment_db')
KAFKA = os.getenv('KAFKA_BOOTSTRAP', 'redpanda:9092')


def conn():
    return psycopg.connect(DB)


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def bootstrap():
    for _ in range(30):
        try:
            with conn() as c:
                c.execute(
                    "CREATE TABLE IF NOT EXISTS outbox(event_id text primary key, topic text NOT NULL, aggregate_id text NOT NULL, aggregate_version integer NOT NULL, payload jsonb NOT NULL, created_at numeric NOT NULL, published_at numeric, attempts integer NOT NULL DEFAULT 0, next_attempt_at numeric NOT NULL)"
                )
                c.commit()
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError('fulfillment-worker database bootstrap failed after 30 attempts')


bootstrap()


while True:
    try:
        consumer = KafkaConsumer(
            'logistpulse.orders',
            bootstrap_servers=KAFKA,
            group_id='kitchen-worker',
            auto_offset_reset='earliest',
            enable_auto_commit=False,
            value_deserializer=lambda b: json.loads(b.decode()),
        )
        break
    except Exception as e:
        print('kafka waiting', e)
        time.sleep(2)

for msg in consumer:
    oid = msg.value.get('orderId')
    if not oid:
        consumer.commit()
        continue
    try:
        with conn() as c:
            row = c.execute(
                "SELECT order_id,store_id,channel,total,status,created_at,updated_at,ready_at,aggregate_version FROM orders WHERE order_id=%s",
                (oid,),
            ).fetchone()
        if row is None:
            consumer.commit()
            continue

        order = Order(
            order_id=row[0],
            total=float(row[3]),
            status=row[4],
            created_at=float(row[5]),
        )

        next_order = start_preparation(order)
        now = time.time()
        if next_order.status != order.status:
            preparation = preparation_started_event(next_order, iso_utc(now), iso_utc(order.created_at))
            with conn() as c:
                updated = c.execute(
                    "UPDATE orders SET status=%s,updated_at=%s,aggregate_version=2 WHERE order_id=%s AND status='WAITING'",
                    (next_order.status, now, oid),
                )
                if updated.rowcount:
                    c.execute(
                        "INSERT INTO outbox (event_id,topic,aggregate_id,aggregate_version,payload,created_at,next_attempt_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (preparation["eventId"], "logistpulse.fulfillment.events.v1", oid, 2, json.dumps(preparation), now, now),
                    )
                c.commit()

        if order.status != 'READY':
            time.sleep(4)

        with conn() as c:
            row = c.execute(
                "SELECT order_id,store_id,channel,total,status,created_at,updated_at,ready_at,aggregate_version FROM orders WHERE order_id=%s",
                (oid,),
            ).fetchone()
        if row is None:
            consumer.commit()
            continue

        persisted = Order(
            order_id=row[0],
            total=float(row[3]),
            status=row[4],
            created_at=float(row[5]),
            ready_at=float(row[7]) if row[7] is not None else None,
        )
        ready_now = time.time()
        next_ready = mark_ready(persisted, ready_now)
        if next_ready.status != persisted.status:
            ready_event = order_ready_event(next_ready, iso_utc(ready_now), iso_utc(persisted.created_at), iso_utc(ready_now))
            with conn() as c:
                updated = c.execute(
                    "UPDATE orders SET status=%s,updated_at=%s,ready_at=%s,aggregate_version=3 WHERE order_id=%s AND status='PREPARING' AND ready_at IS NULL",
                    (next_ready.status, ready_now, ready_now, oid),
                )
                if updated.rowcount:
                    c.execute(
                        "INSERT INTO outbox (event_id,topic,aggregate_id,aggregate_version,payload,created_at,next_attempt_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (ready_event["eventId"], "logistpulse.fulfillment.events.v1", oid, 3, json.dumps(ready_event), ready_now, ready_now),
                    )
                c.commit()
            consumer.commit()
    except Exception as e:
        print('worker error', e)
