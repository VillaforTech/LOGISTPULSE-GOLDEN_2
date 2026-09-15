import json
import os
import time

import psycopg
from kafka import KafkaProducer

DB = os.getenv("FULFILLMENT_DB_URL", "postgresql://logist:logist_demo@postgres:5432/fulfillment_db")
KAFKA = os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
POLL_SECONDS = float(os.getenv("OUTBOX_POLL_SECONDS", "0.25"))


def conn():
    return psycopg.connect(DB)


def bootstrap():
    while True:
        try:
            with conn() as c:
                c.execute(
                    "CREATE TABLE IF NOT EXISTS outbox(event_id text primary key, topic text NOT NULL, aggregate_id text NOT NULL, aggregate_version integer NOT NULL, payload jsonb NOT NULL, created_at numeric NOT NULL, published_at numeric, attempts integer NOT NULL DEFAULT 0, next_attempt_at numeric NOT NULL)"
                )
                c.commit()
                return
        except Exception as error:
            print("database waiting", error)
            time.sleep(1)


def producer():
    while True:
        try:
            return KafkaProducer(
                bootstrap_servers=KAFKA,
                key_serializer=lambda value: value.encode(),
                value_serializer=lambda value: json.dumps(value).encode(),
                acks="all",
                retries=10,
            )
        except Exception as error:
            print("kafka waiting", error)
            time.sleep(2)


def publish_pending():
    now = time.time()
    with conn() as c:
        rows = c.execute(
            "SELECT event_id,topic,aggregate_id,payload,attempts FROM outbox WHERE published_at IS NULL AND next_attempt_at <= %s ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 50",
            (now,),
        ).fetchall()
        for event_id, topic, aggregate_id, payload, attempts in rows:
            try:
                producer = producer_for_batch
                producer.send(topic, key=aggregate_id, value=payload).get(timeout=10)
                c.execute(
                    "UPDATE outbox SET published_at=%s,attempts=attempts+1 WHERE event_id=%s AND published_at IS NULL",
                    (time.time(), event_id),
                )
            except Exception as error:
                print("publish failed", event_id, error)
                c.execute(
                    "UPDATE outbox SET attempts=attempts+1,next_attempt_at=%s WHERE event_id=%s",
                    (time.time() + min(60, 2 ** min(6, attempts)), event_id),
                )
        c.commit()


bootstrap()
producer_for_batch = producer()
while True:
    publish_pending()
    time.sleep(POLL_SECONDS)