// Benchmark de latencia creacion-de-pedido -> render de panel (issue #5),
// portado desde BANKPULSE (scripts/acceptance/panel-benchmark.cjs, ya en
// main de ese repo) al dominio de pedidos de LOGISTPULSE.
//
// QUE MIDE (cuando el panel exista de verdad):
//   100 operaciones SECUENCIALES. Cada una crea un pedido identificable
//   via POST /api/fulfillment/orders. El timer arranca ANTES de esa
//   llamada HTTP y termina cuando el panel de Grafana (renderizado en
//   Chromium real, nunca la respuesta de la API) muestra la revision de
//   negocio provocada por el evento `OrderAccepted` de ESE pedido
//   (mismo eventId, calidad FRESH, revision estrictamente mayor a la
//   observada antes de enviar el pedido). Un evento distinto, un timeout,
//   o una revision que no corresponde a este pedido cuentan como muestra
//   NO correcta / perdida -- nunca como exito.
//
// QUE EXIGE EL VALIDADOR (scripts/check-panel-evidence.py, ya en main):
//   measurementTarget=="grafana-render"; sin coberturaParcial*; requested
//   == observed == len(samples) == 100; lost==0 y errors vacio; 100
//   correlationId unicos; cada muestra con correlationId, rendered=True,
//   correct=True, quality=="FRESH", revision>0, latencyMs finito >=0;
//   p95Ms == sorted(latencias)[94], <=1000 y coincidente con el p95
//   recalculado (tolerancia 0.001). Este archivo escribe exactamente ese
//   esquema (measurementTarget, requested, observed, lost, errors,
//   samples[], p50Ms, p95Ms, maximumMs, environment, method).
//
// DE QUE DEPENDE Y POR QUE HOY NO PUEDE MEDIR DE VERDAD:
//   Requiere el adaptador de Grafana Live (issue #3:
//   services/grafana-live-adapter) empujando snapshots del servicio de
//   analitica del issue #2 (services/business-analytics, hoy sin
//   fusionar en feat/2-business-analytics) hacia un panel de Grafana con
//   atributos data-* de calidad/revision/eventId. NINGUNO de los dos
//   existe todavia en esta rama. Por eso, ANTES de tocar la API de
//   pedidos, este script verifica en tiempo de ejecucion si ese panel
//   esta realmente disponible (Grafana arriba, dashboard provisionado,
//   panel presente y publicando datos frescos). Si no lo esta:
//     - imprime un mensaje claro en espanol explicando la dependencia
//       (issue #3),
//     - NO crea ningun pedido de prueba,
//     - NO escribe un latency.json con measurementTarget="grafana-render",
//     - NO simula, inventa ni rellena muestras,
//     - termina con exit code 3 (SKIPPED honesto, no PASS; bajo
//       `set -euo pipefail` de scripts/team-acceptance.sh esto detiene la
//       corrida, igual que resilience_checks.py hace hoy con sus casos).
//
// TODOs para cuando el issue #3 fusione el adaptador (ajustar aqui, no en
// el wrapper Python ni en el validador):
//   - DASHBOARD_UID: uid real del dashboard de negocio que provisione #3
//     (hoy es un placeholder; ver observability/grafana/provisioning).
//   - PANEL_SELECTOR: selector data-* real que exponga el panel plugin de
//     negocio (hoy asumimos la misma convencion que BANKPULSE:
//     data-logistpulse-panel="<kpi>" con dataset quality/revision/eventId;
//     confirmar contra la implementacion real de #3).
//   - LIVE_CHANNEL / nombre del datasource: el canal de Grafana Live que
//     el adaptador empuje (placeholder 'stream/logistpulse/business',
//     analogo a 'stream/bankpulse/business' en BANKPULSE).
//   - GRAFANA_URL/usuario/password: confirmar contra la configuracion real
//     de Grafana en ese momento (hoy se usan los defaults locales de
//     observability/compose.yaml, sobreescribibles por variables de
//     entorno).
//   - outboxEventId(): confirmar el nombre de tabla/columnas del outbox si
//     el contrato de eventos (#1) cambia antes de que #3 integre.
'use strict';

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { randomUUID } = require('node:crypto');

let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (e) {
  console.error(
    '[panel-benchmark] ERROR de entorno: no se pudo cargar el modulo "playwright". ' +
      'Este benchmark necesita Chromium real (Playwright) para medir el render del panel, ' +
      'igual que en BANKPULSE. Instalalo (p.ej. como hace la CI de BANKPULSE: ' +
      '`npm install --prefix <dir> playwright && <dir>/node_modules/.bin/playwright install --with-deps chromium` ' +
      'con NODE_PATH apuntando a ese <dir>/node_modules) y vuelve a intentar.\n' +
      'Detalle: ' + String(e)
  );
  process.exit(2);
}

const base = (process.argv[2] || 'http://localhost:8080').replace(/\/$/, '');
const output = process.argv[3] || 'artifacts/acceptance/latency.json';

// --- Configuracion del panel/adaptador (TODO: ajustar cuando #3 exista) ---
const GRAFANA_URL = (process.env.GRAFANA_URL || 'http://localhost:3000').replace(/\/$/, '');
// Defaults locales de observability/compose.yaml (no son un secreto de
// produccion: son el usuario/clave demo del Grafana local del laboratorio,
// igual que BANKPULSE hace en sus propios scripts de aceptacion).
const GRAFANA_USER = process.env.GRAFANA_USER || 'admin';
const GRAFANA_PASSWORD = process.env.GRAFANA_PASSWORD || 'logistpulse_demo';
// TODO(#3): reemplazar por el uid real del dashboard de negocio que
// provisione el issue #3 (observability/grafana/provisioning/dashboards).
const DASHBOARD_UID = process.env.LOGISTPULSE_DASHBOARD_UID || 'logistpulse-deber-01';
// TODO(#3): reemplazar por el selector real que exponga el panel plugin de
// negocio (nombre del panel custom, atributo data-*).
const PANEL_SELECTOR = process.env.LOGISTPULSE_PANEL_SELECTOR || '[data-logistpulse-panel="missed_commitments_percent"]';
// TODO(#3): confirmar el canal/datasource real de Grafana Live usado por
// el adaptador (documentado aqui solo para trazabilidad del mensaje de
// error; no se usa directamente via HTTP).
const LIVE_CHANNEL = process.env.LOGISTPULSE_LIVE_CHANNEL || 'stream/logistpulse/business';
// Cuanto esperamos, como maximo, a que el panel de un dashboard ya
// provisionado empiece a publicar datos frescos antes de rendirnos y
// reportar "adaptador no disponible". No es el timeout por-muestra del
// benchmark real (ese es de 10s, como en BANKPULSE); es solo el sondeo de
// disponibilidad inicial.
const PROBE_TIMEOUT_MS = Number(process.env.LOGISTPULSE_PANEL_PROBE_TIMEOUT_MS || 15000);

const DB_SERVICE = process.env.LOGISTPULSE_DB_SERVICE || 'postgres';
const DB_NAME = process.env.FULFILLMENT_DB_NAME || 'fulfillment_db';
const DB_USER = process.env.POSTGRES_USER || 'logist';

function log(msg) {
  console.log(`[panel-benchmark] ${msg}`);
}

function database(query) {
  // Las credenciales quedan dentro del contenedor (via $POSTGRES_USER de su
  // propio entorno); aqui solo pasamos el nombre de la base y la consulta.
  return execFileSync(
    'docker',
    ['compose', 'exec', '-T', DB_SERVICE, 'sh', '-c',
      `exec psql -U "${DB_USER}" -d "${DB_NAME}" -Atc "$1"`, 'sh', query],
    { encoding: 'utf8' }
  ).trim();
}

function outboxEventId(orderId, eventType) {
  // Solo IDs generados por este mismo benchmark entran aqui (ver el regex
  // mas abajo antes de invocar esta funcion): nunca interpolamos entrada
  // externa sin validar en el SQL.
  if (!/^ORD-[0-9A-F]{6}$/.test(orderId)) {
    throw new Error(`orderId con formato inesperado, me niego a consultarlo: ${orderId}`);
  }
  if (!/^[A-Za-z]+$/.test(eventType)) {
    throw new Error(`eventType con formato inesperado: ${eventType}`);
  }
  // TODO(#1/#3): ajustar tabla/columnas si el contrato de outbox cambia.
  // Hoy: outbox(event_id, topic, aggregate_id, aggregate_version, payload jsonb, ...)
  // y el eventType real vive en payload->>'eventType' (ver
  // services/fulfillment-api/domain/events.py).
  const sql = `select event_id from outbox where aggregate_id='${orderId}' and payload->>'eventType'='${eventType}' limit 1`;
  return database(sql);
}

async function grafanaLogin(page) {
  const response = await page.request.post(`${GRAFANA_URL}/login`, {
    data: { user: GRAFANA_USER, password: GRAFANA_PASSWORD },
    timeout: 5000,
  });
  return response.ok();
}

/**
 * Determina, EN TIEMPO DE EJECUCION y sin fabricar nada, si el panel de
 * negocio (issue #3: grafana-live-adapter + panel plugin) esta realmente
 * disponible hoy. Devuelve {available:true} o {available:false, reason}.
 * Nunca lanza para el caso "no disponible": ese es un resultado esperado
 * hoy, no una excepcion.
 */
async function detectarDisponibilidadDelPanel(page) {
  // 1) Grafana en si mismo debe responder.
  let health;
  try {
    health = await page.request.get(`${GRAFANA_URL}/api/health`, { timeout: 5000 });
  } catch (e) {
    return {
      available: false,
      reason: `Grafana no responde en ${GRAFANA_URL} (${e}). El panel de negocio del issue #3 depende de que Grafana este arriba.`,
    };
  }
  if (!health.ok()) {
    return {
      available: false,
      reason: `Grafana respondio ${health.status()} en ${GRAFANA_URL}/api/health.`,
    };
  }

  // 2) Login (necesario para navegar el dashboard como en BANKPULSE).
  let logueado = false;
  try {
    logueado = await grafanaLogin(page);
  } catch (e) {
    return { available: false, reason: `No se pudo autenticar contra Grafana: ${e}` };
  }
  if (!logueado) {
    return {
      available: false,
      reason: 'Grafana rechazo el login local del laboratorio (ver GRAFANA_USER/GRAFANA_PASSWORD).',
    };
  }

  // 3) El dashboard del panel de negocio debe estar provisionado. Hoy NO
  //    lo esta: el issue #3 (grafana-live-adapter) no ha entregado su
  //    dashboard/panel, y el #2 (business-analytics) sigue sin fusionar.
  let dashboardResp;
  try {
    dashboardResp = await page.request.get(`${GRAFANA_URL}/api/dashboards/uid/${DASHBOARD_UID}`, { timeout: 5000 });
  } catch (e) {
    return { available: false, reason: `No se pudo consultar el dashboard '${DASHBOARD_UID}' en Grafana: ${e}` };
  }
  if (!dashboardResp.ok()) {
    return {
      available: false,
      reason:
        `El dashboard de negocio '${DASHBOARD_UID}' no existe en Grafana (HTTP ${dashboardResp.status()}). ` +
        'Este dashboard y su panel de negocio los entrega el issue #3 (grafana-live-adapter), ' +
        'que ademas depende del servicio de analitica del issue #2 (services/business-analytics, ' +
        'hoy sin fusionar en feat/2-business-analytics). Ninguno de los dos existe todavia en esta rama.',
    };
  }

  // 4) El panel debe estar presente en el DOM y publicando datos frescos
  //    (es decir, el adaptador debe estar corriendo y empujando a Grafana
  //    Live). Se sondea con un timeout acotado: si nunca aparece, es una
  //    ausencia real, no un error transitorio.
  try {
    await page.goto(`${GRAFANA_URL}/d/${DASHBOARD_UID}`, { timeout: PROBE_TIMEOUT_MS });
    await page.waitForFunction(
      (sel) => {
        const el = document.querySelector(sel);
        return !!el && !!el.dataset && !!el.dataset.quality;
      },
      PANEL_SELECTOR,
      { timeout: PROBE_TIMEOUT_MS, polling: 250 }
    );
  } catch (e) {
    return {
      available: false,
      reason:
        `El panel de negocio (selector '${PANEL_SELECTOR}') no aparece publicando datos en el dashboard ` +
        `'${DASHBOARD_UID}' dentro de ${PROBE_TIMEOUT_MS}ms. Esto indica que el adaptador de Grafana Live ` +
        '(issue #3) no esta corriendo o no esta empujando snapshots todavia. Detalle: ' + String(e),
    };
  }

  return { available: true };
}

(async () => {
  fs.mkdirSync(path.dirname(output), { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ locale: 'es-EC', viewport: { width: 1440, height: 1100 } });

  let disponibilidad;
  try {
    disponibilidad = await detectarDisponibilidadDelPanel(page);
  } finally {
    // Nada que limpiar todavia; el browser se cierra mas abajo en ambos casos.
  }

  if (!disponibilidad.available) {
    console.error('');
    console.error('========================================================================');
    console.error('MEDICION DE PANEL NO DISPONIBLE (issue #3 pendiente) -- SKIPPED, no PASS');
    console.error('========================================================================');
    console.error(disponibilidad.reason);
    console.error('');
    console.error(
      'Este benchmark mide desde el envio del pedido (POST /api/fulfillment/orders) hasta que ' +
        'Grafana Live renderiza esa revision de negocio en un panel real (Chromium). Esa medicion ' +
        'depende del adaptador de Grafana Live (issue #3, services/grafana-live-adapter) y del ' +
        'servicio de analitica del issue #2 (services/business-analytics), y ninguno de los dos ' +
        'esta integrado en esta rama todavia.'
    );
    console.error(
      'No se creo ningun pedido de prueba, no se escribio ' + output + ' con measurementTarget=' +
        '"grafana-render", y no se genero ninguna muestra sintetica o simulada: eso produciria un ' +
        'falso verde, que es exactamente lo que scripts/check-panel-evidence.py existe para impedir.'
    );
    console.error('Vuelve a correr este script cuando el issue #3 este fusionado.');
    console.error('========================================================================');
    console.error('');
    await browser.close();
    process.exitCode = 3;
    return;
  }

  // --- A partir de aqui, el panel de negocio SI esta disponible: medicion real. ---
  log(`panel de negocio disponible en '${DASHBOARD_UID}' (${PANEL_SELECTOR}); iniciando 100 mediciones secuenciales...`);

  const report = {
    measurementTarget: 'grafana-render',
    requested: 100,
    observed: 0,
    lost: 0,
    errors: [],
    samples: [],
    environment: {
      node: process.version,
      cpus: os.cpus().length,
      memoryBytes: os.totalmem(),
      platform: os.platform(),
      sha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
      concurrency: 1,
    },
    method:
      '100 pedidos secuenciales; timer antes del POST de creacion hasta que el panel de Grafana ' +
      'muestra el evento OrderAccepted de ese pedido con calidad FRESH y revision estrictamente ' +
      'mayor a la observada antes de enviarlo; p95 por nearest-rank; muestras fallidas retenidas en >= 10000ms.',
  };

  try {
    for (let i = 0; i < 100; i++) {
      const sample = { index: i, correlationId: randomUUID(), rendered: false, correct: false, latencyMs: 10000 };
      let start;
      try {
        const before = await page.locator(PANEL_SELECTOR).evaluate((e) => ({ ...e.dataset }));
        start = performance.now();
        const response = await page.request.post(`${base}/api/fulfillment/orders`, {
          data: { storeId: 'STORE-042', channel: `LATENCY-BENCH-${sample.correlationId}`, total: 18.5 },
          timeout: 10000,
        });
        if (!response.ok()) throw new Error(`HTTP ${response.status()} creando el pedido`);
        const body = await response.json();
        const orderId = body.orderId;
        if (!orderId) throw new Error('respuesta de creacion sin orderId');
        const eventId = outboxEventId(orderId, 'OrderAccepted');
        if (!eventId) throw new Error(`no se encontro el evento OrderAccepted en el outbox para ${orderId}`);
        const handle = await page.waitForFunction(
          ({ sel, prevRevision, id }) => {
            const e = document.querySelector(sel);
            if (!e || !e.dataset) return false;
            const ok =
              e.dataset.quality === 'FRESH' &&
              e.dataset.eventId === id &&
              Number(e.dataset.revision) > Number(prevRevision || 0);
            return ok && { ...e.dataset };
          },
          { sel: PANEL_SELECTOR, prevRevision: before.revision, id: eventId },
          { timeout: 10000, polling: 'raf' }
        );
        sample.latencyMs = performance.now() - start;
        const rendered = await handle.jsonValue();
        Object.assign(sample, {
          orderId,
          eventId,
          rendered: true,
          correct: rendered.eventId === eventId,
          quality: rendered.quality,
          revision: Number(rendered.revision),
        });
        report.observed++;
      } catch (e) {
        sample.latencyMs = Math.max(10000, start ? performance.now() - start : 0);
        sample.error = String(e);
        report.errors.push({ index: i, error: String(e) });
        report.lost++;
      }
      report.samples.push(sample);
      console.log(JSON.stringify(sample));
    }
    await page.screenshot({ path: path.join(path.dirname(output), 'panel-benchmark.png'), fullPage: true });
  } catch (e) {
    report.errors.push({ error: String(e) });
    throw e;
  } finally {
    const sorted = report.samples.map((s) => s.latencyMs).sort((a, b) => a - b);
    report.maximumMs = sorted.at(-1) ?? null;
    report.p50Ms = sorted[49] ?? null;
    report.p95Ms = sorted[94] ?? null;
    report.lost = 100 - report.observed;
    fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }

  if (report.observed !== 100 || report.errors.length || report.p95Ms > 1000) {
    throw new Error(`Benchmark de panel fallo: observed=${report.observed} errors=${report.errors.length} p95Ms=${report.p95Ms}`);
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = process.exitCode || 1;
});
