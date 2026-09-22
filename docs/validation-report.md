# Final validation report

Validated on 2026-09-23 with Docker Compose from a removed-volume state. The final reviewer environment was
left running with deterministic demo data.

## Commands and results

```bash
make demo-reset
make demo
make test
make lint
make demo
```

- `make demo-reset`: removed project PostgreSQL/Redpanda volumes and containers. The sandbox initially denied
  Docker socket access; the identical command succeeded after explicit permission. No repository/source file
  was removed.
- First clean `make demo`: migrations 0001–0005, both seeds, replay, ingestion, and AFDD evaluation succeeded.
  The newly added final verifier then failed non-zero because it incorrectly assumed the late record ID was
  also the deliberate duplicate. Database audit showed `src-ahu-0070-000` is the accepted late record and
  `src-ahu-0100-001` is the duplicate. The verifier was corrected to assert retained late history and latest
  non-regression separately; no product data/logic was forced to fit the check.
- Subsequent `make demo` runs: passed end to end, including service/API/web/AI-route readiness.
- `make test`: backend 34 passed with two upstream Starlette/AnyIO deprecation warnings; frontend 5 passed.
- `make lint`: Ruff passed, Python compileall passed, TypeScript typecheck plus Vite production build passed,
  `docker compose config --quiet` passed, and `git diff --check` passed. No frontend lint script is configured.

The demo itself executed these reviewer-visible stages and failed on any error:

```bash
docker compose build migrate seed simulator ingestion worker api web
docker compose up -d --wait db redpanda
docker compose run --rm migrate
docker compose --profile tools run --rm seed python -m afdd.seed --reset
docker compose --profile tools run --rm seed
docker compose up redpanda-init
docker compose up -d --wait ingestion api web
docker compose --profile telemetry run --rm simulator python -m apps.simulator.main --delay-seconds 0
docker compose exec -T api python -m afdd.demo_check --wait --timeout-seconds 180
docker compose run --rm worker python -m apps.worker.main --ensure-default-rule --reset --once
docker compose up -d worker
docker compose exec -T api python -m afdd.demo_check --verify
```

## Clean-run evidence

- Inventory: 3 buildings, 12 floors, 24 HVAC zones, 48 occupied rooms, 24 AHUs, 48 IAQ devices, and 12
  electricity meters.
- Canonical totals: 93 spaces, 84 equipment, 288 points, 465 entities, 888 relationships.
- Source replay: 30,237 deliveries; accepted 30,235, duplicate 1, rejected unknown equipment 1.
- Telemetry: 103,649 historical observations and 288 current points.
- Rule preview/evaluation: 16 matched office AHUs, 8 exclusions, 2 closed issues, 0 open; outcomes included
  one `IGNORED_LATE_OR_EQUAL` and six `UNTRUSTWORTHY_INPUT` samples.
- Hero `ahu-a-f02-east`: Critical, rule version 1, 3.0°C, 900s, qualifies 10:00, opens 10:15, closes 10:21;
  installation `building-a-plant-room`, served zone `building-a-f02-east`, affected rooms `-r01/-r02`.
  Evidence includes RUN/SAT/SAT_SP, difference, threshold, quality/freshness, and opening version.
- Override `ahu-b-f01-west`: effective 2.0°C; qualifies 11:20, opens 11:35, closes 11:41.
- Verified zero issues: `ahu-a-f03-west`, `ahu-b-f04-east`, and `ahu-a-f04-west`.
- Late `ahu-a-f01-east` observation has five point-history rows at 09:10 while all five latest values remain at
  13:59; evaluation reported one ignored late/equal transition.

## Service, API, and repository checks

TimescaleDB, Redpanda, API, ingestion, web, and worker were running; database, broker, API, and web health
checks passed. `/health`, `/openapi.json`, `/portfolio`, and the direct SPA route `/rules/new/ai` responded.
OpenAPI exposed 28 paths tagged `ai-authoring`, `issues`, `ontology`, `operations`, `rules`, and `telemetry`;
Swagger UI is `/docs`.

`git diff --exit-code -- data/candidate-starter-pack` passed and final SHA-256 hashes matched the pre-change
audit. `.env` is ignored and untracked. A tracked-file scan found no `.env`, node_modules, caches, Python bytecode,
build output, or local DB file. A filename-only scan found no tracked API-key-like value. The starter pack’s
already-supplied `.DS_Store` remains untouched because source files are immutable.

## AI evidence and blocker

Before the required clean reset, persisted failure-path evidence was inspected without exposing prompt/key data:
request `5dbd8af7-6cbd-40ad-9093-ef1da6c22ce5`, provider `openai`, model `gpt-5.6-terra`, state `FAILED`, two
model calls, one retry, 5,408 ms, HTTP 429 present, `human_confirmed_at` null, and no activation result. The
clean reset intentionally cleared local AI audit rows along with other application data; this report preserves
the non-secret result.

**Required blocker:** before submission, perform at least one successful real-model authoring run that reaches
interpretation, server validation, ontology resolution, and a non-empty `READY_FOR_REVIEW` preview without
automatic activation. The 429 failure does not satisfy that requirement.

Browser screenshot automation was unavailable. `screenshot-walkthrough.md` is therefore a precise nine-step
capture checklist; no screenshot has been fabricated. The AI review-state screenshot remains pending the same
successful real-model blocker.
