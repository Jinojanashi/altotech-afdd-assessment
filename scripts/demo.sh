#!/usr/bin/env bash
set -euo pipefail

echo "[demo] Building application images"
docker compose build migrate seed simulator ingestion worker api web

echo "[demo] Stopping application consumers before deterministic reset"
docker compose stop ingestion worker api web >/dev/null 2>&1 || true

echo "[demo] Starting TimescaleDB and Redpanda"
docker compose up -d --wait db redpanda

echo "[demo] Applying migrations"
docker compose run --rm migrate

echo "[demo] Resetting and seeding canonical inventory"
docker compose --profile tools run --rm seed python -m afdd.seed --reset

echo "[demo] Repeating seed to prove idempotency"
docker compose --profile tools run --rm seed

echo "[demo] Ensuring telemetry topic exists"
docker compose up redpanda-init

echo "[demo] Starting ingestion, API, and web services"
docker compose up -d --wait ingestion api web

echo "[demo] Replaying all supplied telemetry without wall-clock delay"
docker compose --profile telemetry run --rm simulator \
  python -m apps.simulator.main --delay-seconds 0

echo "[demo] Waiting for exact ingestion completion"
docker compose exec -T api python -m afdd.demo_check --wait --timeout-seconds 180

echo "[demo] Creating the default rule and evaluating deterministically"
docker compose run --rm worker python -m apps.worker.main \
  --ensure-default-rule --reset --once

echo "[demo] Starting the independent AFDD worker service"
docker compose up -d worker

echo "[demo] Verifying system health and deterministic outputs"
bash scripts/verify-demo.sh

docker compose ps
echo "[demo] Ready: dashboard http://localhost:3000/portfolio | API http://localhost:8000/docs"
