"""A single consumer and an independent clock thread; neither uses producer databases."""

import logging
import os
import threading
import time

from kafka import KafkaConsumer, TopicPartition
from kafka.structs import OffsetAndMetadata

LOG = logging.getLogger(__name__)
TOPIC = "logistpulse.fulfillment.events.v1"
GROUP = "logistpulse-business-analytics-v1"


class Runtime:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.state_lock = threading.Lock()
        self.health = dict(connected=False, caught_up=False, last_poll=None, lag=None)
        self.tick = float(os.getenv("ANALYTICS_TICK_SECONDS", "0.2"))
        if not 0.1 <= self.tick <= 0.25:
            raise ValueError("ANALYTICS_TICK_SECONDS must be between 0.1 and 0.25")
        self.threads = []

    def start(self):
        self.store.publish(time.time())
        for target in (self.consume, self.clock):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def set_health(self, **values):
        with self.state_lock:
            self.health.update(values)

    def clock(self):
        target = time.monotonic()
        while not self.stop.is_set():
            with self.state_lock:
                health = dict(self.health)
            try:
                self.store.publish(
                    time.time(), **health, timer_delay=max(0, time.monotonic() - target)
                )
            except Exception:
                LOG.exception("projection tick failed")
            target += self.tick
            if target < time.monotonic():
                target = time.monotonic()
            self.stop.wait(max(0, target - time.monotonic()))

    def consume(self):
        while not self.stop.is_set():
            consumer = None
            try:
                consumer = KafkaConsumer(
                    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092"),
                    group_id=GROUP,
                    enable_auto_commit=False,
                    auto_offset_reset="none",
                    fetch_max_wait_ms=100,
                    request_timeout_ms=10000,
                    session_timeout_ms=6000,
                    api_version_auto_timeout_ms=3000,
                    max_poll_records=100,
                )
                partitions = consumer.partitions_for_topic(TOPIC)
                if not partitions:
                    raise RuntimeError("event topic is not provisioned by #4")
                assigned = [TopicPartition(TOPIC, p) for p in sorted(partitions)]
                consumer.assign(assigned)
                beginnings = consumer.beginning_offsets(assigned)
                for tp in assigned:
                    checkpoint = self.store.checkpoint(tp.partition)
                    if checkpoint is None:
                        checkpoint = beginnings[tp]
                        if checkpoint != 0:
                            self.store.mark_history_missing()
                    if checkpoint < beginnings[tp]:
                        self.store.mark_history_missing()
                        checkpoint = beginnings[tp]
                    consumer.seek(tp, checkpoint)
                while not self.stop.is_set():
                    records = consumer.poll(timeout_ms=100, max_records=100)
                    if records:
                        self.set_health(caught_up=False)
                    for tp, batch in records.items():
                        for message in batch:
                            key = (
                                message.key.decode("utf-8", errors="replace")
                                if message.key
                                else ""
                            )
                            self.store.ingest(
                                message.value, tp.partition, message.offset, key=key
                            )
                            # Explicit, synchronous acknowledgement AFTER the durable transaction.
                            consumer.commit(
                                {tp: OffsetAndMetadata(message.offset + 1, "")}
                            )
                    ends = consumer.end_offsets(assigned)
                    lag = sum(
                        max(0, ends[tp] - consumer.position(tp)) for tp in assigned
                    )
                    if any(consumer.position(tp) > ends[tp] for tp in assigned):
                        self.store.mark_history_missing()
                    self.set_health(
                        connected=True,
                        caught_up=lag == 0,
                        last_poll=time.time(),
                        lag=lag,
                    )
                    # A partition-count change needs fresh assignment and coverage verification.
                    current = consumer.partitions_for_topic(TOPIC)
                    if current != partitions:
                        raise RuntimeError(
                            "topic partitions changed; rebuilding assignment"
                        )
            except Exception:
                self.set_health(connected=False, caught_up=False)
                LOG.exception("consumer unavailable; projection is not fresh")
            finally:
                if consumer is not None:
                    consumer.close(autocommit=False)
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=15)
        if any(t.is_alive() for t in self.threads):
            raise RuntimeError("consumer did not stop; database must remain open")
