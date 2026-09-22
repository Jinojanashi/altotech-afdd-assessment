#!/usr/bin/env bash
set -eEuo pipefail
trap 'echo "[verify-demo] FAIL" >&2' ERR

echo "[verify-demo] Checking API health and OpenAPI"
docker compose exec -T api python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5); urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=5)"
echo "[verify-demo] PASS API health and OpenAPI"

echo "[verify-demo] Checking frontend and direct AI authoring route"
docker compose exec -T web wget -q -T 5 -O /dev/null http://127.0.0.1/portfolio
docker compose exec -T web wget -q -T 5 -O /dev/null http://127.0.0.1/rules/new/ai
echo "[verify-demo] PASS frontend routes"

echo "[verify-demo] Checking deterministic demo outputs"
docker compose exec -T api python -m afdd.demo_check --verify --quiet
echo "[verify-demo] PASS all running-demo checks"
