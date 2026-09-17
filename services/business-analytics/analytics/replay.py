"""Replay NDJSON into a NEW projection database, never reset a shared Kafka group."""

import argparse
import json
from pathlib import Path

from .domain import timestamp
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--coverage-from", required=True)
    parser.add_argument("--at", required=True, help="Controlled UTC evaluation time")
    args = parser.parse_args()
    if args.db.exists():
        parser.error("output database already exists; choose a new path")
    now = timestamp(args.at)
    store = Store(str(args.db), args.coverage_from)
    try:
        for line in args.events.read_text(encoding="utf-8").splitlines():
            if line.strip():
                store.ingest(line)
        result = store.publish(
            now, connected=True, caught_up=True, last_poll=now, lag=0
        )
        # Offline fixture completeness is not proof of live broker health.
        result["source"] = "offline-replay"
        print(json.dumps(result, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
