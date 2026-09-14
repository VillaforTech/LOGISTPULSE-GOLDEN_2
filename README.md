# LOGISTPULSE-GOLDEN V1.0

**Independent LOGISTdragon universe — Operations, Logistics, IoT and Platform Engineering laboratory.**

**Team:** see [CONTRIBUTING.md](CONTRIBUTING.md) for Deber 01 assignments, the branch workflow and Roberto's required review before merging into `main`.

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

The final **Release gate** requires both CI stages to succeed; failed, skipped or cancelled stages block integration. The Deber 01 business regression and real-time checks remain work assigned in the team issues; this repository setup does not implement them.

## Academic ownership

Design of Systems teams own frontend/backend product evolution. Software Development teams act as DevOps/Platform teams: Codespaces, CI/CD, containerization, integration readiness, observability and later DevSecOps security gates.

See `docs/` for C4, data ownership, missions and incident runbooks.

## Registros de decisiones de arquitectura (ADR)

ADR-Tools está incluido en el proyecto y sus registros se validan dentro de
`architecture-contract`. Ver [instalación, comandos y alcance del control](docs/adr/README.md).
