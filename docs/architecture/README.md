# LOGISTdragon architecture

LOGISTdragon is an independent universe focused on physical operations, logistics, restaurant/retail execution and cyber-physical systems.

## Bounded contexts

1. Inventory — stock, demand forecast and replenishment signals.
2. Distribution — fleet, route progress, ETA and cold chain.
3. Smart Operations — store equipment telemetry and operational alerts.
4. Fulfillment — order lifecycle and kitchen queue.

The platform intentionally mixes synchronous APIs, MQTT telemetry and Kafka-compatible event streaming so students can compare integration styles.
