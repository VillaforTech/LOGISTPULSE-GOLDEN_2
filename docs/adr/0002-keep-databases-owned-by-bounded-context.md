# 2. Keep databases owned by bounded context

Date: 2026-09-13

## Status

Accepted

## Context

LogistPulse separa inventario, distribución, operaciones y fulfillment. Este
registro documenta retrospectivamente la regla de la
[matriz de ownership](../architecture/DATA-OWNERSHIP.md) y la
[arquitectura actual](../architecture/README.md). La fecha corresponde al
registro; no implica una migración de datos nueva.

## Decision

Mantener la escritura de los datos de cada contexto en su servicio propietario:

| Contexto | Datos propios | Persistencia |
| --- | --- | --- |
| Inventory | Stock, forecast y señal de reposición | PostgreSQL `inventory_db` |
| Distribution | Camiones, rutas, ETA y cadena de frío | PostgreSQL `logistics_db` |
| Smart Operations | Telemetría y estado de dispositivos | MongoDB `operations` |
| Fulfillment | Pedidos, estado de cocina y timestamps | PostgreSQL `fulfillment_db` |

Integrar mediante las APIs y los canales de mensajería del laboratorio. MQTT
transporta telemetría y Redpanda los mensajes del flujo de pedidos; ninguno
sustituye la base autoritativa de negocio. Ningún servicio escribe directamente
la base de otro contexto.

Se descarta una base compartida con escritura libre: ahorraría contratos de
integración, pero mezclaría ownership y acoplaría cambios de esquema. Tampoco
se toma el estado del broker como reemplazo del estado persistente del pedido.

## Consequences

Cada contexto controla su modelo y migraciones. Los consumidores deben tolerar
retrasos, mensajes repetidos y caídas de dependencias; las proyecciones pueden
estar atrasadas respecto de la fuente de verdad. Estas garantías requieren
políticas y pruebas explícitas del flujo correspondiente.

El seguimiento de pedidos combina HTTP y trabajo asíncrono, por lo que un health
check o un broker disponible no demuestran que el pedido terminó. La validación
de este ADR revisa su documentación; no implementa ni sustituye las pruebas de
negocio, deduplicación o recuperación pendientes del equipo.
