"""One-process SQLite projection. Each delivery is durable before Kafka acknowledgement."""

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager

from .domain import calculate, iso, project, timestamp, validate


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path, coverage_from=None):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inbox(
              id TEXT PRIMARY KEY, aggregate_id TEXT NOT NULL, version INTEGER NOT NULL,
              body TEXT NOT NULL, applied INTEGER NOT NULL DEFAULT 0,
              UNIQUE(aggregate_id,version));
            CREATE TABLE IF NOT EXISTS errors(id TEXT PRIMARY KEY, raw TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints(partition_id INTEGER PRIMARY KEY, next_offset INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots(revision INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('duplicates','0')")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('dataRevision','0')")
            self.db.execute(
                "INSERT OR IGNORE INTO metadata VALUES('coverageFrom',?)",
                (coverage_from or "",),
            )
            stored = self.meta("coverageFrom")
            if coverage_from and stored != coverage_from:
                raise ValueError(
                    "coverageFrom is immutable: use a separate database for a new population"
                )
            if stored:
                timestamp(stored)

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def meta(self, key, default=""):
        row = self.db.execute(
            "SELECT value FROM metadata WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else default

    def put_meta(self, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, str(value))
        )

    def increment(self, key):
        self.put_meta(key, int(self.meta(key, "0")) + 1)

    def checkpoint(self, partition):
        with self.lock:
            row = self.db.execute(
                "SELECT next_offset FROM checkpoints WHERE partition_id=?", (partition,)
            ).fetchone()
            return row[0] if row else None

    def mark_history_missing(self):
        with self.transaction():
            self.put_meta("historyMissing", "true")

    def ingest(self, raw, partition=0, offset=None, key=None):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        raw = raw if isinstance(raw, str) else encode(raw)
        error_id = hashlib.sha256(raw.encode()).hexdigest()
        with self.transaction():
            try:
                event = validate(json.loads(raw, parse_float=str))
                if key is not None and key != event["aggregateId"]:
                    raise ValueError("Kafka key does not match aggregateId")
                canonical = encode(event)
                existing = self.db.execute(
                    "SELECT body FROM inbox WHERE id=?", (event["eventId"],)
                ).fetchone()
                if existing:
                    if existing[0] != canonical:
                        raise ValueError("eventId reused with different content")
                    self.increment("duplicates")
                    self._drain(event["aggregateId"])
                else:
                    conflict = self.db.execute(
                        "SELECT id FROM inbox WHERE aggregate_id=? AND version=?",
                        (event["aggregateId"], event["aggregateVersion"]),
                    ).fetchone()
                    if conflict:
                        raise ValueError(
                            "aggregate version has conflicting event identities"
                        )
                    self.db.execute(
                        "INSERT INTO inbox(id,aggregate_id,version,body) VALUES(?,?,?,?)",
                        (
                            event["eventId"],
                            event["aggregateId"],
                            event["aggregateVersion"],
                            canonical,
                        ),
                    )
                    self.increment("dataRevision")
                    self.put_meta("lastEventId", event["eventId"])
                    self.put_meta("lastEventOccurredAt", timestamp(event["occurredAt"]))
                    self._drain(event["aggregateId"])
                self.db.execute("DELETE FROM errors WHERE id=?", (error_id,))
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                self.db.execute(
                    "INSERT OR REPLACE INTO errors VALUES(?,?,?)",
                    (error_id, raw, str(exc)),
                )
            if offset is not None:
                self.db.execute(
                    """INSERT INTO checkpoints VALUES(?,?)
                    ON CONFLICT(partition_id) DO UPDATE
                    SET next_offset=max(next_offset, excluded.next_offset)""",
                    (partition, offset + 1),
                )
        # Caller may crash here, before Kafka commit. Re-delivery is harmless.

    def _drain(self, aggregate_id):
        row = self.db.execute(
            "SELECT body FROM orders WHERE id=?", (aggregate_id,)
        ).fetchone()
        order = json.loads(row[0]) if row else None
        while True:
            version = order["version"] + 1 if order else 1
            pending = self.db.execute(
                "SELECT id,body FROM inbox WHERE aggregate_id=? AND version=?",
                (aggregate_id, version),
            ).fetchone()
            if pending is None:
                return
            event = json.loads(pending["body"])
            order = project(order, event)
            self.db.execute(
                "INSERT OR REPLACE INTO orders VALUES(?,?)",
                (aggregate_id, encode(order)),
            )
            self.db.execute("UPDATE inbox SET applied=1 WHERE id=?", (pending["id"],))

    def publish(
        self,
        now,
        connected=False,
        caught_up=False,
        last_poll=None,
        lag=None,
        stale_seconds=3,
        timer_delay=0,
    ):
        with self.transaction():
            orders = [
                json.loads(r[0])
                for r in self.db.execute("SELECT body FROM orders ORDER BY id")
            ]
            pending = self.db.execute(
                "SELECT count(*) FROM inbox WHERE applied=0"
            ).fetchone()[0]
            errors = self.db.execute("SELECT count(*) FROM errors").fetchone()[0]
            start = self.meta("coverageFrom")
            future = any(o["occurredAt"] > now for o in orders)
            complete = (
                bool(start)
                and timestamp(start) <= now
                and not (pending or errors or future or self.meta("historyMissing"))
            )
            fresh = (
                connected
                and caught_up
                and last_poll is not None
                and 0 <= now - last_poll <= stale_seconds
            )
            quality = (
                "INCOMPLETO"
                if not complete
                else "ACTUAL"
                if fresh
                else "DESACTUALIZADO"
            )
            kpis = calculate(orders, now)
            previous = self._latest()
            alerts = {}
            for name in ("L-K1", "L-K2", "L-K3"):
                active = (
                    kpis[name]["state"] == "INCUMPLIDO" if quality == "ACTUAL" else None
                )
                old = previous.get("alerts", {}).get(name, {})
                alerts[name] = {
                    "active": active,
                    "changedAt": old.get("changedAt")
                    if old.get("active") == active and old
                    else iso(now),
                    "quality": quality,
                }
            # Values remain available as provisional estimates, never labelled valid.
            result = {
                "schemaVersion": 1,
                "generatedAt": iso(now),
                "dataRevision": int(self.meta("dataRevision", "0")),
                "lastEventId": self.meta("lastEventId") or None,
                "quality": quality,
                "valid": quality == "ACTUAL",
                "kpis": kpis,
                "alerts": alerts,
                "coverage": {
                    "from": start or None,
                    "population": "all retained accepted orders",
                    "complete": complete,
                    "pendingEvents": pending,
                    "schemaErrors": errors,
                    "futureEvents": future,
                    "historyMissing": bool(self.meta("historyMissing")),
                },
                "freshness": {
                    "connected": connected,
                    "caughtUp": caught_up,
                    "lastPollAt": iso(last_poll) if last_poll is not None else None,
                    "lag": lag,
                    "maxAgeSeconds": stale_seconds,
                },
                "diagnostics": {
                    "duplicates": int(self.meta("duplicates", "0")),
                    "lastEventOccurredAt": (
                        iso(float(self.meta("lastEventOccurredAt")))
                        if self.meta("lastEventOccurredAt")
                        else None
                    ),
                    "timerDelaySeconds": max(0, timer_delay),
                },
            }
            cursor = self.db.execute(
                "INSERT INTO snapshots(body) VALUES(?)", (encode(result),)
            )
            result["revision"] = cursor.lastrowid
            self.db.execute(
                "UPDATE snapshots SET body=? WHERE revision=?",
                (encode(result), cursor.lastrowid),
            )
            return result

    def _latest(self):
        row = self.db.execute(
            "SELECT body FROM snapshots ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else {}

    def latest(self):
        with self.lock:
            return self._latest()

    def updates(self, after, limit=100):
        with self.lock:
            return [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT body FROM snapshots WHERE revision>? ORDER BY revision LIMIT ?",
                    (after, limit),
                )
            ]

    def close(self):
        with self.lock:
            self.db.close()
