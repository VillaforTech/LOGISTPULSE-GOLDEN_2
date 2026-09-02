# Data ownership matrix

| Context | Owner data | Persistence | External consumers |
|---|---|---|---|
| Inventory | stock, forecast, replenishment signal | PostgreSQL `inventory_db` | Frontend, future replenishment engine |
| Distribution | truck, route, ETA, cold-chain status | PostgreSQL `logistics_db` | Operations console |
| Smart Operations | device telemetry, device state | MongoDB `operations` | Alerting/observability |
| Fulfillment | order, kitchen state, order timestamps | PostgreSQL `fulfillment_db` | Kitchen worker, frontend |

Rules: no service writes another service's database. MQTT and Redpanda are integration channels, not authoritative business databases.
