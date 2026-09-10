# Trabajo en equipo — LogistPulse

Todos trabajamos en este repositorio compartido, con una rama por tarea y un Pull Request (PR) hacia `main`. Roberto (`@VillaforTech`) revisa los cambios del equipo. Una issue asignada define el trabajo; un PR contiene la implementación y su evidencia.

## Reparto del Deber 01

| Issue | Responsable | Entrega |
| --- | --- | --- |
| [#1](https://github.com/VillaforTech/LOGISTPULSE-GOLDEN_2/issues/1) | `@nikotov` | Contrato de eventos, outbox del ciclo del pedido y definición de KPIs propios. |
| [#2](https://github.com/VillaforTech/LOGISTPULSE-GOLDEN_2/issues/2) | `@DanielSalazar0710` | Analítica continua, deduplicación, estado persistente y temporizadores. |
| [#3](https://github.com/VillaforTech/LOGISTPULSE-GOLDEN_2/issues/3) | `@oandretty010` | Grafana Live, paneles, alertas y reconexión. |
| [#4](https://github.com/VillaforTech/LOGISTPULSE-GOLDEN_2/issues/4) | `@VillaforTech` | Compose, streaming, integración y Release Gate del deber. |
| [#5](https://github.com/VillaforTech/LOGISTPULSE-GOLDEN_2/issues/5) | `@Dmt-155lbs` | Pruebas de extremo a extremo, resiliencia y evidencia del falso verde. |

Las issues contienen los criterios completos y las dependencias. Acordar el contrato de #1 antes de integrar #2 y #3. #4 integra los componentes; #5 valida el conjunto. Se puede preparar trabajo en paralelo usando ese contrato, sin presentar una simulación como integración terminada.

## Crear una contribución

Con el árbol de trabajo limpio, por ejemplo para la issue #2:

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/2-business-analytics

# Implementar y ejecutar las comprobaciones del cambio.
git diff --check
git add ruta/al/archivo
git commit -m "feat(analytics): persist order projections"
git push -u origin feat/2-business-analytics
```

Usar prefijos `feat/`, `fix/`, `docs/` o `chore/` y el número de issue. Mantener los PR pequeños y con un objetivo revisable. No modificar la rama de otro compañero sin coordinarlo.

Abrir el PR contra `main`, completar la plantilla y vincular la issue. Usar **Draft** mientras el trabajo esté incompleto. Usar `Closes #2` solo cuando ese PR complete toda la issue; para avances parciales, usar `Relacionado con #2`.

Al marcar **Ready for review**, GitHub solicita a Roberto la revisión mediante [CODEOWNERS](.github/CODEOWNERS). Los borradores no solicitan automáticamente revisión al propietario del código. Si GitHub pide actualizar la rama, integrar `origin/main` en la rama de trabajo y repetir las comprobaciones antes de solicitar aprobación.

## Condiciones para integrar

La protección de `main` exige:

- Un PR y al menos una aprobación, con revisión del propietario del código (`@VillaforTech`).
- Una aprobación vigente: los cambios nuevos invalidan las aprobaciones anteriores.
- Todas las conversaciones de revisión resueltas.
- La rama actualizada con `main` y estos checks de GitHub Actions en verde: `architecture-contract`, `integration` y `Release gate`.
- Historial lineal mediante **Squash and merge**; GitHub elimina la rama remota después de integrar.

Las reglas también se aplican al administrador. Los pushes directos, force pushes y la eliminación de `main` están bloqueados. No hay una excepción permanente para saltar las revisiones o los checks. No desactivar las reglas para resolver un CI rojo.

GitHub no permite aprobar un PR propio. Si el autor es Roberto, debe pedir revisión a otro colaborador antes de integrar sus cambios. Esto también afecta a PR creados por una herramienta autenticada con su cuenta.

## Validar y revisar

Seguir el [README](README.md) para preparar el entorno. Antes de solicitar revisión de cambios de aplicación:

```bash
docker compose config --quiet
docker compose -f observability/compose.yaml config --quiet
docker compose up -d --build
# Esperar a que todas las APIs estén listas antes de ejecutar el smoke.
bash scripts/smoke.sh
```

Registrar comandos y resultados reales en el PR. Para eventos y KPIs, agregar las pruebas de duplicados, reinicio, temporizadores sin eventos, recuperación y frescura que correspondan a la issue. Un cambio solo documental debe indicar que las pruebas de aplicación no aplican y describir su validación documental.

Roberto revisa **Files changed**, las pruebas y los resultados de **Checks**. Puede usar **Review changes → Request changes** para pedir correcciones y **Approve** cuando el cambio esté listo. Un comentario o una casilla marcada en la plantilla no equivalen a una aprobación.

Con aprobación vigente y checks correctos, integrar con **Squash and merge**. El título del PR será el título del commit; escribirlo como una descripción del cambio. Una vez integrado, cada compañero actualiza su `main` local antes de comenzar otra tarea.

## Alcance del gate inicial

El `Release gate` de configuración comprueba que las etapas actuales de arquitectura e integración hayan terminado con `success`. Un fallo, una etapa omitida o una cancelación no producen un gate verde.

Este gate todavía no implementa la prueba de negocio del Deber 01 ni las verificaciones de analítica en tiempo real. #4 debe incorporar esas etapas y añadirlas a las dependencias y comprobaciones del gate. #5 debe demostrar un caso correcto, una regresión controlada con infraestructura sana que bloquee el merge y su corrección. La regresión se demuestra en un PR y nunca se integra en `main`.

Al configurar el equipo el 9 de septiembre de 2026, el CI base fallaba al consultar inventario con HTTP 502 durante el arranque. Corregir y demostrar la espera de disponibilidad de todas las APIs dentro de #4 antes de integrar trabajo dependiente; no debilitar la prueba para obtener un resultado verde.

## Configuración y datos

No subir `.env`, tokens ni credenciales reales. Usar datos de laboratorio en pruebas y evidencias. Revisar migraciones, contratos y cambios de ownership de datos explícitamente en el PR.

La configuración inicial de `CODEOWNERS`, plantilla y gate se instala antes de activar la protección para que GitHub pueda leer la política desde `main`. Los cambios posteriores a esta configuración siguen el mismo proceso de PR y revisión que el resto del código.
