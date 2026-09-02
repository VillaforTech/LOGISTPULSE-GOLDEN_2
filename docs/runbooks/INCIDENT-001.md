# Incident drill — Kitchen backlog

**Scenario:** Store-042 reaches 80 pending orders. CPU is normal, PostgreSQL is healthy, but Kafka consumer lag grows rapidly.

Students must determine whether the fault is producer throughput, broker health or kitchen-worker consumption. Evidence must include `docker compose ps`, service logs, Prometheus/Grafana data and a corrective action proposal.
