# Acceptance test plan

A fresh Codespace is considered GOLDEN-ready only if:

1. `docker --version` and `docker compose version` succeed.
2. `docker compose config --services` returns all domain and infrastructure services.
3. `docker compose up -d --build` completes without Recovery Mode.
4. `docker compose ps` shows databases and domain APIs healthy.
5. `bash scripts/smoke.sh` prints `LOGISTPULSE smoke test OK`.
6. Port 8080 displays the interactive Operations Command Center.
7. `docker compose -f observability/compose.yaml up -d` starts Grafana, Prometheus and cAdvisor.
8. Grafana on 3000 loads the LOGISTPULSE dashboard.
9. A Pull Request triggers `.github/workflows/ci.yml` and both CI jobs pass.
