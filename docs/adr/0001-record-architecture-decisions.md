# 1. Record architecture decisions

Date: 2026-09-13

## Status

Proposed

## Context

El repositorio tiene documentación de arquitectura y una plantilla, pero falta
un registro numerado que explique por qué elegimos cada opción. La tarea
«Instala ADR tools» pide implementar ADR-Tools e incorporar los registros en CI.

## Decision

Usar [ADR-Tools 3.0.0](../../tools/adr-tools/UPSTREAM.md) desde `./scripts/adr`,
con las fuentes oficiales fijadas dentro del repositorio. Guardar decisiones
numeradas en `docs/adr`, con fecha, estado, contexto, decisión y consecuencias.
Una decisión nueva inicia como `Proposed` y se revisa en el PR; este registro
permanece propuesto hasta esa revisión.

Agregar al job `architecture-contract` la validación del formato y enlaces
locales, además de pruebas que demuestren el rechazo de registros incompletos.
El Release gate existente ya exige que ese job termine correctamente.
Se conserva la [matriz de ownership](../architecture/DATA-OWNERSHIP.md)
como referencia para justificar datos, consistencia e integración.

Descartamos una instalación global sin versión fijada porque cada integrante
podría usar una versión distinta. Un documento fuera del repositorio tampoco
pasaría por la misma revisión del cambio.

## Consequences

El clon trae la herramienta y CI no necesita descargarla. Debemos conservar
sus licencias y revisar cualquier actualización de la copia oficial.
La validación comprueba estructura y referencias; la calidad de la decisión
requiere revisión humana. No demuestra invariantes de negocio ni sustituye
los checks de integración existentes.

Para cambiar una decisión aceptada, crear otra con `./scripts/adr new -s N`
y conservar el historial. Ver [uso y validación](README.md).
