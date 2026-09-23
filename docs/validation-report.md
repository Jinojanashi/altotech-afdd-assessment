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
- `make test`: backend 42 passed with two upstream FastAPI/Starlette deprecation warnings; frontend 5 passed.
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

## AI evidence

Before the required clean reset, persisted failure-path evidence was inspected without exposing prompt/key data:
request `5dbd8af7-6cbd-40ad-9093-ef1da6c22ce5`, provider `openai`, model `gpt-5.6-terra`, state `FAILED`, two
model calls, one retry, 5,408 ms, HTTP 429 present, `human_confirmed_at` null, and no activation result. The
clean reset intentionally cleared local AI audit rows along with other application data; this report preserves
the non-secret result.

The successful real-model requirement is complete. OpenAI `gpt-5.6-terra` request
`5bb1b689-0d7d-4a0b-8465-3b879aeecc2c` reached `READY_FOR_REVIEW` in one call with zero retries and 4,601 ms
latency. Validation passed; the ontology-backed preview matched 8 targets and excluded 16. Human confirmation
and activation were both absent. Additional sanitized provider outputs are preserved under
[`evidence/`](evidence/). The earlier HTTP 429 remains failure-path evidence only.

## Optional bonus validation

- Historical backtest tests prove deterministic repeated results and unchanged issue, rule activation,
  evaluator-state, telemetry, and latest-value counts. The default hero case and Building B 3.0°C versus 2.0°C
  what-if behavior match live semantics.
- MCP tests cover all four read-only tools plus an explicit mutation-surface audit. The stdio service is optional
  and absent from the normal demo profile.
- Seven captured reviewer screenshots are indexed in [`screenshots/README.md`](screenshots/README.md), including
  the real-model `READY_FOR_REVIEW` state before confirmation.

## Requirement coverage

| Area | Status | Primary implementation/evidence |
|---|---|---|
| Simulator and Kafka-compatible event boundary | Covered | separate simulator, Redpanda topic, replay tests |
| Ingestion, idempotency, late data, and quality visibility | Covered | telemetry pipeline tests and deterministic counts |
| Canonical relational ontology and explicit topology | Covered | migrations/seed suite and equipment context APIs |
| TimescaleDB history and latest-state non-regression | Covered | history/current tests and demo verification |
| Versioned AFDD rule, preview, exclusions, and override | Covered | rule/evaluator suite and dashboard rule detail |
| Continuous observed-time evaluation and issue lifecycle | Covered | hero, recovery, recurrence, OFF/missing/stale tests |
| Portfolio and issue-investigation dashboard | Covered | frontend/API tests and captured screenshots |
| AI interpretation, ontology validation, and preview | Covered | AI suite and successful real-provider evidence |
| Human-only confirmation and exactly-once activation | Covered | guarded confirmation tests; no model activation tool |
| Provider retry/failure handling and audit trace | Covered | deterministic tests plus real HTTP 429 evidence |
| One-command demo, reset, verification, and tests | Covered | Make targets and clean-volume validation |
| Historical backtest bonus | Covered | read-only backtest tests and rule-detail UI |
| Optional MCP bonus | Covered | four read-only tools and MCP test suite |
| AI-assistance disclosure and checkpoint | Covered | dedicated assessment documents |

## Remaining non-blocking limitations

- Compose uses single-node PostgreSQL/TimescaleDB and Redpanda; it is a local assessment topology, not HA.
- The worker polls database-backed state and dashboard projections are synchronous; production scale would add
  partitioned/checkpointed processing, batching/materialization, and observability.
- Authentication, RBAC, multi-user approvals, work orders, and cloud deployment are intentionally out of scope.
- AI authoring supports only the existing SAT absolute-deviation DSL.
