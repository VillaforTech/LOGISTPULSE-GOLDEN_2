#!/usr/bin/env bash
# Orquestador de la evidencia de aceptacion del issue #5.
#
# Ejecuta, en orden: prueba de negocio -> benchmark de latencia ->
# verificaciones de resiliencia. Al final imprime una tabla resumen con
# el codigo de salida real de cada etapa y un veredicto agregado.
#
# Codigos de salida por etapa (ver cada script para el detalle):
#   business_test_fulfillment.py : 0=PASS 1=FAIL 2=ERROR
#   latency_benchmark.py         : 0=PASS 1=FAIL 2=ERROR
#   resilience_checks.py         : 0=PASS 1=FAIL 3=SKIPPED
#
# Un SKIPPED (exit 3, esperado hoy en resilience_checks.py mientras el
# issue #1/#4 no exista) NUNCA se cuenta como verde. Este orquestador
# solo devuelve 0 si TODAS las etapas obligatorias (negocio y
# benchmark) devolvieron PASS; resiliencia puede quedar SKIPPED sin
# tumbar el gate agregado (ya que hoy es estructuralmente imposible que
# pase), pero se reporta siempre en la tabla y nunca como PASS.
set -euo pipefail

DIR_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${1:-http://localhost:8080}"

echo "=== LOGISTPULSE - evidencia de aceptacion (issue #5) ==="
echo "Base URL: ${BASE_URL}"
echo

declare -a NOMBRES
declare -a CODIGOS
declare -a VEREDICTOS

registrar_resultado() {
  local nombre="$1"
  local codigo="$2"
  local veredicto="$3"
  NOMBRES+=("$nombre")
  CODIGOS+=("$codigo")
  VEREDICTOS+=("$veredicto")
}

veredicto_desde_codigo() {
  # $1 = nombre de la etapa, $2 = codigo de salida real
  local etapa="$1" codigo="$2"
  case "$etapa" in
    negocio|benchmark)
      case "$codigo" in
        0) echo "PASS" ;;
        1) echo "FAIL" ;;
        2) echo "ERROR" ;;
        *) echo "ERROR" ;;
      esac
      ;;
    resiliencia)
      case "$codigo" in
        0) echo "PASS" ;;
        1) echo "FAIL" ;;
        3) echo "SKIPPED" ;;
        *) echo "ERROR" ;;
      esac
      ;;
  esac
}

echo "[1/3] Prueba de negocio (business_test_fulfillment.py)"
set +e
python3 "${DIR_SCRIPT}/business_test_fulfillment.py" --base-url "${BASE_URL}"
codigo_negocio=$?
set -e
registrar_resultado "negocio" "$codigo_negocio" "$(veredicto_desde_codigo negocio "$codigo_negocio")"
echo

echo "[2/3] Benchmark de latencia (latency_benchmark.py)"
set +e
python3 "${DIR_SCRIPT}/latency_benchmark.py" --base-url "${BASE_URL}"
codigo_benchmark=$?
set -e
registrar_resultado "benchmark" "$codigo_benchmark" "$(veredicto_desde_codigo benchmark "$codigo_benchmark")"
echo

echo "[3/3] Verificaciones de resiliencia (resilience_checks.py)"
set +e
python3 "${DIR_SCRIPT}/resilience_checks.py" --base-url "${BASE_URL}"
codigo_resiliencia=$?
set -e
registrar_resultado "resiliencia" "$codigo_resiliencia" "$(veredicto_desde_codigo resiliencia "$codigo_resiliencia")"
echo

echo "=== Resumen ==="
printf '%-15s %-10s %s\n' "ETAPA" "EXIT_CODE" "VEREDICTO"
for i in "${!NOMBRES[@]}"; do
  printf '%-15s %-10s %s\n' "${NOMBRES[$i]}" "${CODIGOS[$i]}" "${VEREDICTOS[$i]}"
done
echo

# Gate agregado: las etapas obligatorias (negocio, benchmark) deben ser
# PASS. La etapa de resiliencia puede quedar SKIPPED (esperado hoy,
# depende de #1/#4) sin tumbar el gate agregado, pero un FAIL o ERROR en
# resiliencia SI lo tumba. SKIPPED nunca se imprime ni se cuenta como
# PASS en ningun caso.
gate_ok=1
for i in "${!NOMBRES[@]}"; do
  nombre="${NOMBRES[$i]}"
  veredicto="${VEREDICTOS[$i]}"
  if [[ "$nombre" == "resiliencia" ]]; then
    if [[ "$veredicto" == "FAIL" || "$veredicto" == "ERROR" ]]; then
      gate_ok=0
    fi
    # SKIPPED en resiliencia no tumba el gate agregado (dependencia
    # ausente conocida), pero tampoco cuenta como verde: queda
    # explicito en la tabla de arriba.
  else
    if [[ "$veredicto" != "PASS" ]]; then
      gate_ok=0
    fi
  fi
done

if [[ "$gate_ok" -eq 1 ]]; then
  echo "GATE AGREGADO: PASS (etapas obligatorias en verde; resiliencia SKIPPED no cuenta como verde pero no bloquea mientras dependa de #1/#4)"
  exit 0
else
  echo "GATE AGREGADO: FAIL (alguna etapa obligatoria no fue PASS, o resiliencia fallo/erroro)"
  exit 1
fi
