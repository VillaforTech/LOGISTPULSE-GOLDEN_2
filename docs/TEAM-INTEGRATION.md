# Base de integración — LogistPulse

Responsable #4: Roberto. Esta rama recupera la base; no acredita que los componentes #1/#2/#3/#5 estén terminados.

## Arranque y pruebas

```bash
docker compose up --build -d --wait --wait-timeout 300
python3 scripts/wait-ready.py && bash scripts/smoke.sh
docker compose -f observability/compose.yaml up -d prometheus grafana
python3 -m unittest discover -s tests/infrastructure -v
```

Los repos comparten puertos publicados: usar Codespaces distintos o detener una plataforma antes de arrancar la otra. `docker compose down` conserva datos; no usar `down -v` sobre trabajo que se deba conservar.

## Contrato de infraestructura para el equipo

- Broker: `redpanda:9092`, topic `logistpulse.fulfillment.events.v1`, clave `aggregateId`, una partición y retención de 24 h para el laboratorio. El bootstrap es idempotente y no recrea topics existentes.
- Analítica #2: se acepta SQLite propio con WAL, volumen Linux y **una sola instancia** para este laboratorio. No necesita migrar a PostgreSQL para integrar. No lee tablas del productor. El gemelo usa otro almacenamiento; adaptar interfaces, no copiar su stack completo.
- Después de incluir el PR de #2, usar `docker compose -f compose.yaml -f compose.analytics.yaml up --build -d --wait`. `ANALYTICS_COVERAGE_FROM` debe ser el inicio UTC real de una población conocida. No cambiarlo sobre una base existente ni inventar cobertura para datos previos.
- Analítica interna: `http://business-analytics:8000`, `/health`, `/ready`, `/snapshot`, `/updates?after=N`, `/stream?after=N`, `/metrics`. El volumen es exclusivo y persiste durante reinicios.
- #1 conserva su outbox y publica después del commit con eventId estable y aggregateVersion consecutiva. UTC debe conservar microsegundos. Deadline exactamente alcanzado es puntual; una cohorte expira al llegar a 900 s (ventana semiabierta). Coordinar estas decisiones con la documentación del productor y los tests del consumidor.
- #3 conecta su adaptador a snapshot/SSE; persiste la última revisión, recupera huecos y muestra calidad obsoleta tras 3 s sin actualización. Prometheus no sustituye Grafana Live.

## Gate y entrega de #5

El CI ejecuta unidades, compilación, despliegue, smoke, observabilidad y conserva artifacts antes de detener. Si se incluye `scripts/acceptance/`, `scripts/team-acceptance.sh` se vuelve obligatorio dentro del check de integración y por tanto de `Release gate`. **Error, SKIPPED y medición parcial bloquean.** Sin ese directorio, el verde solo acredita la base, no la aceptación del deber.

El benchmark de #5 conserva `--base-url` y `--out`; debe producir `measurementTarget=grafana-render`, requested/observed=100, lost=0, errors=[], p95Ms recalculable y 100 samples con correlationId único, rendered=true, correct=true, quality=FRESH, revision>0, latencyMs finito. El oráculo verifica los valores y la identidad de los tres paneles antes de escribir cada sample. El checker no convierte un booleano declarado en prueba visual: adjuntar captura y mediciones crudas del navegador. El prototipo API-only actual falla deliberadamente este contrato.

No usar el agregado anterior que permitía resiliencia SKIPPED. Implementar los escenarios reales y devolver 0 solo cuando todos pasen. Registrar fixtures y resultados, no importar el calculador del productor como oráculo.

## Orden para integrar

1. Aplicar este PR como base de trabajo y ejecutar CI. Los compañeros pueden fusionar esta rama en su rama de feature sin esperar cambios a main.
2. #1 y #2 confirman el envelope, precisión y bordes temporales; #1 completa producción/outbox y #2 consume el topic aprovisionado.
3. #3 entrega adaptador/panel y #5 entrega medición real y resiliencia. Conectar sus servicios en Compose antes de activar el harness.
4. Ejecutar la demostración sano → negocio rojo con servicios UP → gate bloqueado → corregido verde; conservar SHAs y runs.
5. Obtener revisión elegible y reproducir en Codespace limpio. El CODEOWNERS actual solo lista a Roberto; un PR propio no se autoaprueba. No se modificaron permisos ni protecciones.

Referencia: [gemelo](https://github.com/VillaforTech/LOGISTPULSE-GOLDEN_2-REFERENCE). Código de referencia asistido por Codex; cada integrante conserva autoría y evidencia de su implementación.
