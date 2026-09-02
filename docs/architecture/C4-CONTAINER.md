# C4 Container View

```text
Operator Browser
      |
      v
Nginx Edge / Interactive Console :8080
      |
      +--> Inventory API ------> PostgreSQL inventory_db
      +--> Distribution API ---> PostgreSQL logistics_db
      +--> Operations API -----> MongoDB operations
      |          ^
      |          |
      |        MQTT <--- Telemetry Simulator
      +--> Fulfillment API ----> PostgreSQL fulfillment_db
                 |
              Redpanda ---> Fulfillment Worker

All APIs ---> Prometheus ---> Grafana
Docker ----> cAdvisor ------> Prometheus
```
