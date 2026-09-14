# Contrato de eventos — Deber 01: El Falso Verde

## Topic

- **Nombre:** `logistpulse.fulfillment.events.v1`
- **Clave de partición:** `aggregateId` (= `orderId`) — garantiza orden de los eventos de un mismo pedido.
- **Separado** del topic de comandos de cocina (`logistpulse.orders`, grupo `kitchen-worker`). Los comandos de cocina y los hechos de analítica son cosas distintas: no reutilizar el mismo canal.

## Sobre común (envelope)

Todos los eventos comparten esta estructura:

```json
{
  "eventId": "uuid-v4",
  "eventType": "OrderAccepted | PreparationStarted | OrderReady",
  "schemaVersion": 1,
  "aggregateId": "orderId",
  "aggregateVersion": 1,
  "occurredAt": "2026-09-14T00:00:04.120Z",
  "payload": { }
}
```

- **`eventId`**: usado para idempotencia. El relay reintenta publicaciones fallidas con el **mismo** `eventId` — nunca genera uno nuevo para el mismo hecho.
- **`aggregateVersion`**: se incrementa con cada transición válida del pedido (1 = `OrderAccepted`, 2 = `PreparationStarted`, 3 = `OrderReady`). Permite detectar eventos duplicados o fuera de orden.
- **`occurredAt`**: tiempo de negocio en UTC — cuándo pasó el hecho, no cuándo se publicó el mensaje.

## OrderAccepted (aggregateVersion = 1)

```json
{
  "eventType": "OrderAccepted",
  "aggregateVersion": 1,
  "payload": {
    "orderId": "ord-0001",
    "total": 25.5,
    "createdAt": "2026-09-14T00:00:00Z",
    "status": "WAITING"
  }
}
```

## PreparationStarted (aggregateVersion = 2)

```json
{
  "eventType": "PreparationStarted",
  "aggregateVersion": 2,
  "payload": {
    "orderId": "ord-0001",
    "createdAt": "2026-09-14T00:00:00Z",
    "status": "PREPARING"
  }
}
```

## OrderReady (aggregateVersion = 3)

```json
{
  "eventType": "OrderReady",
  "aggregateVersion": 3,
  "payload": {
    "orderId": "ord-0001",
    "createdAt": "2026-09-14T00:00:00Z",
    "readyAt": "2026-09-14T00:00:04Z",
    "total": 25.5,
    "status": "READY"
  }
}
```

## Transiciones válidas

`WAITING → PREPARING → READY`, una sola dirección.

Un comando duplicado sobre un pedido ya `READY` se **ignora**: no reabre el pedido, no vuelve a emitir `OrderReady`, no cambia `readyAt`.

## Garantías de entrega (outbox transaccional)

- El cambio de estado del pedido y el registro en la tabla outbox se graban en **la misma transacción de negocio**, tanto en la API como en el worker.
- Si la transacción falla (rollback), **no existe** ni el pedido ni su evento — no hay "pedido fantasma".
- El relay publica **después** del commit, espera confirmación (`ack`) del broker, y reintenta con el mismo `eventId` si falla la publicación.
- El endpoint `POST` **no debe** responder como aceptado (201) si falló la persistencia del pedido o de su registro en outbox.

## Regla de verdad del evento

El evento describe **solo lo efectivamente persistido**. Si una mutación deja un pedido en `PREPARING` sin llegar nunca a `READY`, **ningún evento debe fingir `OrderReady`**. El vencimiento se detecta por temporizador (ausencia de `READY` a tiempo) — nunca por haber consumido un mensaje, ni por el código `201` de respuesta de la API.

## Compatibilidad y correlación

- El `aggregateVersion` debe exponerse de forma compatible con las respuestas HTTP actuales del servicio, para que #2/#3 puedan reconciliar lo que ven por API contra lo que consumen del topic de eventos.

## Versionado de esquema

- `schemaVersion` se incrementa ante cualquier cambio incompatible del `payload`.
- Los consumidores deben validar la versión recibida y **rechazar o registrar como error** una versión desconocida — nunca asumir compatibilidad silenciosa.

## Deduplicación entre comandos de cocina y eventos de analítica

- El comando de preparación hacia cocina (`logistpulse.orders` / `kitchen-worker`) y el evento de analítica (`logistpulse.fulfillment.events.v1`) son publicaciones **independientes**, aunque describan el mismo hecho de negocio.
- Ambos deben ser fiables (usar el mismo mecanismo de outbox/retry), pero un consumidor de analítica nunca debe depender de haber recibido el comando de cocina, y viceversa.
