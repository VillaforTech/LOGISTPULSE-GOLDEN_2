# KPIs — Deber 01: El Falso Verde

## Contexto de negocio

- Un pedido **aceptado** debe llegar a `READY` **antes de vencer su plazo**.
- **Plazo** = `createdAt + 15s` (propuesta de laboratorio para fixtures secuenciales; el worker real tarda ~4s por preparación).
- Estados válidos: `WAITING → PREPARING → READY` (una sola dirección, sin retrocesos).
- **"Falso verde"**: un pedido aceptado que queda `WAITING`/`PREPARING` mientras la infraestructura (health checks, uptime) se ve "sana" en el dashboard. El sistema *parece* estar bien pero el negocio está incumpliendo.

Fuente de verdad para todos los KPIs: los eventos publicados + el estado persistido del pedido. Nunca el listado parcial de 20 pedidos del endpoint actual — ese listado no es la población de los KPIs.

---

## L-K1 — Compromisos de preparación incumplidos

**Fórmula:**
```
L-K1 = 100 × (pedidos incumplidos) / (pedidos elegibles)
```

- **Población (denominador):** pedidos cuyo `createdAt` cae dentro de la ventana `[ahora - 15min, ahora]` **y** cuyo plazo (`createdAt + 15s`) ya venció.
- **Incumplido (numerador):** dentro de esa población, un pedido que:
  - sigue abierto (`WAITING`/`PREPARING`) después de su plazo, **o**
  - llegó a `READY` pero tarde (`readyAt > createdAt + 15s`).
- **Sin pedidos elegibles:** el resultado es `SIN MUESTRA` (nunca `0%`, nunca error).
- **Umbral de laboratorio:** `0%` (con `SIN MUESTRA` como resultado aceptable, no como incumplimiento).
- Un pedido que llega a `READY` tarde **no se borra** del cómputo de su cohorte: sigue contando como incumplido mientras pertenezca a la ventana de 15 min medida desde su `createdAt`.
- La ventana de 15 min también "vence" sin tráfico nuevo — debe recalcularse por temporizador, no solo al llegar un evento nuevo.

---

## L-K2 — Valor comprometido en pedidos vencidos

**Fórmula:**
```
L-K2 = Σ total, para todo pedido WAITING/PREPARING cuyo plazo ya venció
```

- **No se limita a la ventana de 15 min** — es una foto de **todo** el backlog abierto vencido en este instante.
- **Unidad:** "unidades monetarias demo". `total` no declara moneda; nunca mostrar esto como "ingresos perdidos" ni como USD.
- **Umbral de laboratorio:** `0`.

---

## L-K3 — Deuda acumulada de preparación

**Fórmula:**
```
L-K3 = Σ max(0, ahora - createdAt - 15s), para todo pedido todavía WAITING/PREPARING
```

- **Unidad:** pedido-segundos (segundos de atraso acumulados, sumados entre todos los pedidos abiertos).
- **Umbral de laboratorio:** `0`.

---

## Fixture de referencia (compartida con #2/#3/#4/#5)

Pedido único, `total = 25.5`, `createdAt = T0`.

- **Caso sano:** `readyAt = T0 + 4s` → dentro del plazo. No incumplido. No aporta a L-K2/L-K3.
- **Caso mutado (worker se cuelga, infraestructura sigue UP):** el pedido queda en `PREPARING` y nunca llega a `READY`.
  - En `T0 + 20s` (ya venció el plazo de `T0+15s`, sigue abierto):
    - Cohorte elegible = 1 pedido, incumplido = 1 → **L-K1 = 100%**
    - **L-K2 = 25.5**
    - **L-K3 ≈ 5** pedido-segundos (`20 - 15 = 5`)

```json
{
  "schemaVersion": 1,
  "orderId": "ord-0001",
  "total": 25.5,
  "createdAt": "2026-09-14T00:00:00Z",
  "deadlineSeconds": 15,
  "expectedResultAt20s": {
    "status": "PREPARING",
    "L-K1": "100%",
    "L-K2": 25.5,
    "L-K3": 5
  }
}
```

---

## Reglas de cálculo compartidas

- `readyAt` se persiste **una sola vez**, exactamente cuando el pedido pasa a `READY`. `updatedAt` puede cambiar por otras razones y **no** sustituye a `readyAt`.
- Los KPIs se calculan consultando pedidos individualmente por `orderId` (o recorriendo toda la población relevante), nunca sobre un listado paginado/parcial.
- No calcular KPIs globales sobre el listado parcial de 20 pedidos.

---

## Política de corrección de eventos tardíos

- Si un `OrderReady` llega después de que ya se publicó una lectura de KPI, se recalcula la cohorte correspondiente al recibirlo, siempre que el pedido aún pertenezca a la ventana de 15 min de su cohorte.
- Fuera de esa ventana, el hecho tardío se sigue reflejando en tiempo real en L-K2/L-K3 (que no son ventanas de 15 min), pero ya no cambia el numerador histórico de una cohorte de L-K1 ya cerrada.

---

## Casos de prueba obligatorios (reloj controlado)

1. **Sano:** `createdAt=T0`, `readyAt=T0+4s` → no incumplido.
2. **Tardío:** `readyAt=T0+18s` → incumplido en L-K1 si su cohorte sigue vigente.
3. **Abierto vencido:** sigue `PREPARING` en `T0+20s` → incumplido; aporta a L-K2 y L-K3.
4. **Borde de 15s exacto:** `readyAt=T0+15.000s` → definir explícitamente `<=` o `<` y documentarlo aquí (recomendado: `<=` cuenta como a tiempo).
5. **Duplicado:** un segundo comando de "READY" sobre un pedido ya `READY` no reabre, no reprocesa, no cambia `readyAt`.
6. **Rollback:** si la transacción de negocio falla, no debe existir ni el pedido ni su evento.
7. **Sin muestra:** ninguna cohorte elegible en la ventana → `L-K1 = SIN MUESTRA`.

## Cobertura y bootstrap

La cobertura de KPIs y eventos comienza en el inicio de una sesión limpia de Codespace. Para datos previos a ese arranque, no se inventan `readyAt` ni se consultan otras bases para “completar” la historia; se usa una instantánea consistente con un corte explícito o se marca la medición como `INCOMPLETO` hasta reconciliarla. El punto de partida del sistema es el momento en que la sesión queda en estado limpio, no la historia oculta de otra base o despliegue. Cualquier dato preexistente que no pueda verificarse con ese corte se considera no elegible para la métrica hasta ser reconciliado.
