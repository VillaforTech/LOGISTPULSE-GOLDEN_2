# Codespaces quick start

```bash
docker --version
docker compose version
docker compose config --services
docker compose up -d --build
docker compose ps
bash scripts/smoke.sh
```

Observability:

```bash
docker compose -f observability/compose.yaml up -d
```

Open forwarded ports 8080, 3000, 9090 and 8088.
