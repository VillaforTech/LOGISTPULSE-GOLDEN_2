# Analítica continua de LogistPulse — issue #2

Responsable: @DanielSalazar0710. Implementación local del componente; **Relacionado con #2**.
No cerrar el issue hasta completar la integración y evidencia compartida.

## Alcance y dependencias

Este servicio observa pedidos desde `logistpulse.fulfillment.events.v1`.
No modifica Fulfillment, su worker, inventario, frontend, el CI ni los servicios de otros integrantes.

- #1 (@nikotov): productor fiable, contrato, `readyAt`, consulta por orderId y cobertura.
- #2: cálculo independiente, proyección, deduplicación, reloj, alertas y salida recuperable.
- #3 (@oandretty010): adaptador Grafana Live y panel; puede consumir nuestra API/SSE.
- #4 (@VillaforTech): topic, volumen, red y configuración de despliegue; integración en Release gate.
- #5 (@Dmt-155lbs): oráculo independiente y pruebas de extremo a extremo.

Contrato de entrada integrado en `origin/main`, commit `2096825`,
`docs/events-deber-01.md`. La infraestructura y el overlay de #4 están integrados desde
`78f32d4`. Los tests aislados usan fixtures explícitas; la prueba
`tests/system_integration.py` acredita Fulfillment → analítica, pero no el recorrido hasta
Grafana ni sustituye la revisión de Roberto.

## Ejecución y pruebas

Desde `services/business-analytics`, en un entorno Python 3.12:

```bash
python -m pip install -r requirements-test.txt
python -m pytest tests -q
docker build -t logistpulse-business-analytics .
docker compose -f compose.test.yaml config --quiet
docker compose -f compose.test.yaml up -d --build --wait --wait-timeout 120
python tests/integration.py --output /ruta/fuera-del-repo/integration.json
```

La integración requiere que la población del laboratorio aislado esté inicialmente vacía.
El script se niega a sobrescribir datos existentes. Para repetirla use otro proyecto Compose
con un volumen nuevo y el anterior detenido; `docker compose -p ensayo2 -f compose.test.yaml ...`
requiere pasar el mismo nombre al runner mediante `COMPOSE_PROJECT_NAME=ensayo2`.
No ejecutar `down -v` sobre datos que se deban conservar.

`compose.test.yaml` crea su propio broker, topic y volumen; expone solo 127.0.0.1:18080.
El publicador del test emite hechos de fixture directamente al broker.
El runner comprueba vencimiento real sin tráfico, duplicados, READY tardío,
reinicio con deadline pendiente, corte/recuperación del broker, desorden y journal.

Pruebas generales del repositorio, desde su raíz:

```bash
docker compose config --quiet
docker compose -f observability/compose.yaml config --quiet
docker compose up -d --build
# Esperar disponibilidad real de cada API.
bash scripts/smoke.sh
docker compose -f observability/compose.yaml up -d prometheus grafana
```

Prueba integrada con el productor real, después de arrancar la raíz y el overlay:

```bash
python services/business-analytics/tests/system_integration.py \
  --output artifacts/analytics/producer-integration.json
```

Esta prueba crea un pedido por Fulfillment API, observa los eventos reales de outbox/relay
en la proyección, compara `createdAt`, `readyAt`, total, estado y versiones con el pedido
exacto de la API, reinicia Business Analytics y exige recuperación sin duplicación.

No modificar el smoke ni ocultar un fallo base para obtener verde.

## Decisión de almacenamiento (propuesta para revisión de #4)

Una instancia del servicio, un worker Uvicorn y SQLite propio en /data/analytics.sqlite
sobre volumen Docker local. WAL + synchronous=FULL; la base no se comparte con los productores.
Cada entrega persiste inbox, proyección, deadlines y checkpoint local dentro de una transacción.
El offset Kafka se confirma sincrónicamente después. Un corte en medio provoca reentrega segura.
Los snapshots/alertas se escriben en transacciones confirmadas y tienen revisión monotónica.

Esta es una decisión acotada al laboratorio. SQLite no habilita múltiples réplicas:
el consumidor asigna todas las particiones, no reparte trabajo entre instancias.
Si #4 requiere PostgreSQL o múltiples réplicas, adaptar almacenamiento/asignación antes de
integrar. No poner el archivo SQLite en una carpeta de OneDrive ni en un filesystem de red:
el Compose aislado usa un volumen Linux; los tests unitarios usan directorios temporales.

El cálculo recorre la proyección completa en cada tick de 100–250 ms (200 ms por defecto).
Sirve para la población del laboratorio, no es una garantía de capacidad en producción.
Las revisiones se conservan sin poda para que #3 recupere frames perdidos.
El volumen crece durante la ejecución; detener el laboratorio cuando no se use.
Para respaldo en ejecución usar la API backup de SQLite; no copiar solo el archivo .sqlite.

## Semántica temporal

- Se usan tiempos UTC con zona explícita y un reloj inyectable en el cálculo.
- `OrderAccepted.createdAt` queda como instante canónico. Las transiciones toleran hasta
  10 microsegundos de diferencia por la conversión PostgreSQL numeric → float → ISO del
  productor integrado; una diferencia mayor se registra como error de esquema.
- Deadline: createdAt + 15 s; READY exactamente en el deadline es puntual.
- Un pedido abierto es incumplido cuando ahora > deadline.
- L-K1: pedidos creados en la cohorte vigente y deadline vencido; cuenta READY tardío.
- Expiración elegida: cohorte semiabierta [createdAt, createdAt + 900 s).
  Al cumplir 900 s sale del denominador, aun sin tráfico.
  El borrador #1 escribe una ventana inclusiva: confirmar este borde al integrar.
  Esta elección sigue el requisito de #2 de programar salida a createdAt + 15 min.
- L-K2: suma Decimal de total de todo WAITING/PREPARING vencido, sin ventana de 15 min.
- L-K3: suma ahora-deadline de ese backlog; se recalcula, nunca se acumula por tick.
- READY a los 18 s deja L-K1 incumplido pero elimina L-K2/L-K3 del pedido.
- OrderReady recibido tarde con readyAt puntual corrige la lectura provisional.
  El journal conserva ambas revisiones, lastEventId y cambios de alertas.
- Dinero se serializa como string decimal; unidades demo, sin asumir USD.
- Sin elegibles L-K1 devuelve value=null y state=SIN MUESTRA.
- Un hecho tardío de negocio válido se contabiliza aunque incumpla; no se consulta valid=true.

## Eventos, errores y recuperación

Sobre v1 con eventId, eventType, schemaVersion, aggregateId, aggregateVersion, occurredAt, payload.
Acepta OrderAccepted/WAITING/1, PreparationStarted/PREPARING/2, OrderReady/READY/3.
Kafka usa aggregateId como clave. createdAt y total son inmutables.
readyAt coincide con occurredAt en la transición READY. Nunca se sustituye por updatedAt.

Inbox guarda eventos pendientes; un salto de revisión produce INCOMPLETO.
Al llegar la revisión faltante se aplican todas las consecutivas.
Reentregar el mismo eventId y contenido incrementa el contador de duplicados, sin otro efecto.
Identidades/versiones conflictivas y errores de esquema se conservan en errors con el raw.
Se confirma su recepción después de persistir el error; jamás se convierten en cero sano.
Un error requiere corregir el contrato/versión y reconciliar mediante replay en otra base;
no se borra automáticamente para presentar salud. Los datos de error quedan internos.

El checkpoint local manda al reabrir; no se confía en un offset Kafka que pertenezca
a una base perdida. Sin checkpoint se recorre el historial desde el offset inicial.
Si hubo retención que dejó el inicio >0, o pasó el checkpoint, se marca historyMissing.
Un topic truncado/recreado requiere reconciliación explícita; no declarar cobertura completa
solo por alcanzar su final. Conservar el topic durante el laboratorio.

## Contrato para #3 y #5

- GET /health: liveness del proceso y estado de la proyección; UP no acredita negocio.
- GET /ready: 200 solo con cobertura completa y consumidor al día; en otro caso 503.
- GET /snapshot: bootstrap completo, incluida revisión.
- GET /updates?after=N&limit=100: revisiones confirmadas, ordenadas, hasta 1000 por página;
  continuar con nextRevision hasta alcanzar la revisión actual.
- GET /stream?after=N: SSE con event=snapshot, id=revision y data=snapshot completo.
  El adaptador persiste el último id recibido y lo envía como after al reconectar.
  Los comentarios keepalive no renuevan la frescura del negocio.
- GET /metrics: gauges para Prometheus; sin IDs como labels.

Snapshot: schemaVersion, revision, dataRevision, generatedAt, lastEventId, quality, valid,
kpis (value/unit/sample/state), counts, alerts (active/changedAt/quality),
coverage y freshness. La revisión de salida aumenta también sin negocio: reloj y heartbeat.
Una revisión antigua nunca reemplaza una nueva en el consumidor del snapshot.

quality es ACTUAL, INCOMPLETO o DESACTUALIZADO. Las cifras incompletas son provisionales;
valid=false y alert.active=null significan desconocido, no alerta resuelta.
#3 debe mostrar calidad/frescura aparte del estado de negocio y marcar desactualizado
si generatedAt supera 3 segundos aunque la pantalla conserve el último snapshot.
Si el reloj del proceso se detiene, /snapshot también invalida la vista vieja.
El journal histórico se conserva tal como fue calculado.

Métricas: logistpulse_orders_due_window, logistpulse_orders_breached_window,
logistpulse_overdue_order_value, logistpulse_preparation_debt_seconds; además
analytics_valid, analytics_revision, analytics_duplicates, analytics_pending_events,
analytics_schema_errors, analytics_timer_delay_seconds, analytics_lag, con prefijo logistpulse_.
También expone analytics_last_event_timestamp_seconds como último avance de negocio observado.
Los gauges de negocio son NaN cuando no hay cálculo válido.

## Configuración para #4

- KAFKA_BOOTSTRAP: redpanda:9092 en la red compartida.
- ANALYTICS_DB: /data/analytics.sqlite; volumen dedicado escribible por UID 10001.
- ANALYTICS_TICK_SECONDS: 0.1 a 0.25; predeterminado 0.2.
- ANALYTICS_COVERAGE_FROM: UTC explícito del inicio de una población conocida.
  Sin valor el servicio funciona pero muestra INCOMPLETO. Se fija al crear la base
  y no puede cambiarse sobre datos existentes. No inventar cobertura de pedidos previos.
- Grupo fijo logistpulse-business-analytics-v1; topic fijo logistpulse.fulfillment.events.v1.
- HTTP interno 8000; una instancia. Scrape /metrics y consumir /snapshot + /stream.
- No hay credenciales productivas: el broker PLAINTEXT solo pertenece a la red del laboratorio.

## Replay reproducible

```bash
python -m analytics.replay tests/fixtures/overdue.ndjson \
  --db /ruta/nueva/replay.sqlite \
  --coverage-from 2026-01-01T00:00:00Z --at 2026-01-01T00:00:20Z
```

Exige una ruta de DB inexistente; no borra archivos ni resetea el grupo Kafka compartido.
La salida está marcada offline-replay. La fixture de un pedido produce 100%, 25.5 y 5.
No importar el calculador del productor ni sustituir el oráculo independiente de #5.

## Cierre y PR

Usar feat/2-business-analytics, PR contra main y plantilla del repositorio.
Registrar comandos y resultados observados, revisión de Roberto y checks requeridos.
Pendientes compartidos fuera de #2: adaptador/panel #3 y medición extremo a extremo de
>=100 operaciones con #3/#5. Para cerrar #2 todavía se exige CI verde del nuevo SHA y
revisión de Roberto. No afirmar p95 del navegador a partir de nuestros tests.
No cerrar #2 por haber completado solo las pruebas aisladas.
