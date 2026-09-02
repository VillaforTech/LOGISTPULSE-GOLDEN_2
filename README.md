# LOGISTPULSE-GOLDEN V1.0

**Independent LOGISTdragon universe — Operations, Logistics, IoT and Platform Engineering laboratory.**

LOGISTPULSE simulates a national restaurant/retail operation with 300 stores, distribution centers, fleet telemetry, kitchen equipment and event-driven order fulfillment. It is intentionally independent from BANKdragon/BANKPULSE.

## Product domains

- **Smart Inventory** — stock, forecast and stockout risk.
- **Supply & Distribution** — trucks, ETA and cold chain.
- **Smart Operations** — MQTT equipment telemetry and operational state.
- **Order Fulfillment** — event-driven kitchen queue using Kafka-compatible Redpanda.

## Architecture

```text
Browser / Operations Console :8080
          |
       Nginx Edge
          |
  +-------+---------+-----------+
  |       |         |           |
Inventory Distribution Operations Fulfillment
  |       |         |           |
Postgres Postgres  MongoDB    Postgres
                    ^           |
                    |           v
                  MQTT       Redpanda
                    ^           |
              Telemetry      Worker
              Simulator

Prometheus + Grafana + cAdvisor observe the runtime.
```

## Start

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
bash scripts/smoke.sh
```

Open Codespaces port **8080**.

## Observability

```bash
docker compose -f observability/compose.yaml up -d
```

- Grafana `3000` — `admin / logistpulse_demo`
- Prometheus `9090`
- cAdvisor `8088`

## Git/CI model

Work through feature branches and Pull Requests. `.github/workflows/ci.yml` validates the architecture contract, Compose configuration, builds the distributed stack and runs smoke tests before merge.

## Academic ownership

Design of Systems teams own frontend/backend product evolution. Software Development teams act as DevOps/Platform teams: Codespaces, CI/CD, containerization, integration readiness, observability and later DevSecOps security gates.

See `docs/` for C4, data ownership, missions and incident runbooks.
