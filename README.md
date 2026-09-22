# AFDD assessment

A reviewable full-stack Automatic Fault Detection and Diagnostics system for the supplied three-building
portfolio. It replays source snapshots through Redpanda, resolves them against a PostgreSQL relational
ontology, stores history in TimescaleDB, evaluates a versioned rule in a separate worker, and exposes an
operations dashboard plus a human-gated AI rule-authoring workflow.

The hero case is `ahu-a-f02-east`: a sustained supply-air temperature deviation qualifies at 10:00 UTC,
opens a Critical issue at 10:15, and recovers at 10:21. Its installation room, served HVAC zone, affected
occupied rooms, exact rule version, and opening evidence remain inspectable.

## Quick start

Requirements: Docker with Compose v2 and Make. No API key is required for the core product.

```bash
cp .env.example .env
make demo
```

`make demo` builds the images, starts healthy dependencies, migrates, resets/reseeds the application data,
seeds a second time to prove idempotency, replays the complete source data, waits for exact ingestion counts,
runs deterministic AFDD evaluation, verifies evidence, and checks the API/web routes. Any failed stage exits
non-zero. Re-running it produces the same business results; generated UUIDs and receipt timestamps may differ.

Reviewer commands:

```bash
make demo          # create the complete deterministic demo state
make verify-demo   # verify the already-running demo without resetting/replaying
make test          # run backend and frontend deterministic suites
make reset         # clear/reseed application state while preserving named volumes
make ai-live-demo  # real provider attempt; requires OPENAI_API_KEY only here
```

Open:

- Dashboard: <http://localhost:3000/portfolio>
- AI authoring: <http://localhost:3000/rules/new/ai>
- Swagger UI: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/openapi.json>

Expected verified result: 465 canonical entities (93 spaces, 84 equipment, 288 points), 888 explicit
relationships, 30,235 accepted deliveries, one duplicate, one rejected unknown device, 103,649 historical
observations, 288 current points, and two recovered issues (`ahu-a-f02-east` plus the Building B override
case `ahu-b-f01-west`).

## Reviewer journey

Use the 5–10 minute [demonstration guide](docs/demonstration-guide.md). It covers system health, the hero
issue and evidence timeline, installation versus affected spaces, rule preview/exclusions, the Building B
override, non-trigger cases, ingestion exceptions, and the AI trust boundary. A precise evidence-capture
sequence is in [the screenshot walkthrough](docs/screenshot-walkthrough.md).
Exact commands and observed results are recorded in the [final validation report](docs/validation-report.md).

## Architecture and stack

```text
source CSVs -> simulator -> Redpanda -> ingestion -> PostgreSQL/TimescaleDB
                                                        ^          ^
                                                        |          |
                                               FastAPI API    AFDD worker
                                                    ^
                                              React + TypeScript
```

Python 3.12, FastAPI, React/TypeScript, PostgreSQL with TimescaleDB, Redpanda, Alembic, and Docker Compose
are used. Simulator, ingestion, worker, API, and web are separate services. The ontology is relational;
Neo4j/RDF infrastructure is intentionally absent.

Key paths are `apps/` (service entry points/web), `src/afdd/` (domain logic), `db/migrations/`, `tests/`,
`docs/`, and the immutable `data/candidate-starter-pack/` input. See [architecture](docs/architecture.md),
[technical decisions](docs/technical-decisions.md), and the [requirement matrix](docs/requirements-checklist.md).

## Commands

```bash
make demo          # deterministic end-to-end reviewer environment
make verify-demo   # fail-fast health and deterministic output verification
make reset         # reset/reseed application data; keeps Docker volumes
make test          # complete backend and frontend tests
make ai-live-demo  # safe real-model run; never confirms or activates
make lint          # Ruff, compileall, TS production build, Compose config, diff check
make demo-reset    # destructive: stop services and remove local demo volumes
```

Manual migration/seed commands, if needed:

```bash
docker compose up -d --wait db
docker compose run --rm migrate
docker compose --profile tools run --rm seed
docker compose --profile tools run --rm seed python -m afdd.seed --reset
```

The last command clears local canonical, telemetry, rule, issue, and AI audit data before reseeding. It never
changes starter-pack files.

## Source facts versus implementation decisions

Source-supplied facts include 3 buildings, 12 floors, 24 zones, 48 occupied rooms, 24 AHUs, 48 IAQ sensors,
12 floor meters, 288 datapoints, 60-second expected samples, explicit source relationships, and deliberate
duplicate/late/gap/blank/unknown/fault scenarios. The assessment also requires a >3°C, continuous 15-minute
AHU condition and one local override.

Candidate decisions include a 120-second freshness allowance, UUIDv5 transport identity, database-enforced
idempotency, observed-time evaluation, immediate trusted recovery, immutable rule versions, persisted issue
evidence, a 2°C Building B override, Redpanda topic/partition settings, and Brick-aligned relationships stored
in PostgreSQL. Missing input remains missing; it is never interpolated into a normal reading.

`hasLocation` means physical installation, `feeds` means the HVAC zone served, `hasPart` traverses to affected
rooms, `hasPoint` means device point ownership, and `meters` means measurement scope. Thus a plant room is
not an affected tenant room, and a floor meter is contextual to a floor rather than owned by an AHU.

Full AFDD timing/lifecycle semantics are in [AFDD rule engine](docs/afdd.md). API groups cover operations,
ontology, telemetry, rules/preview, issues, portfolio projections, and AI authoring.

## AI-assisted authoring

The model can only return a constrained interpretation. Server code resolves current ontology IDs, validates
the existing rule DSL, previews targets/exclusions, and requires explicit human confirmation before creating
or activating anything. Bounded tools cannot execute arbitrary SQL/code, create assets, or activate rules.
Fake-provider tests cover supported/paraphrased prompts, clarification, injection/unsupported logic, invented
assets, ontology changes, malformed output/retry, missing provider, and idempotent confirmation.

For a later real-provider review-state run, first run `make demo`, then place a key only in ignored `.env`
and set `OPENAI_MODEL`. Run:

```bash
make ai-live-demo
```

This target verifies the running demo first, invokes the existing authoring orchestration, prints a sanitized
evidence summary, never confirms or activates, and exits non-zero unless it reaches `READY_FOR_REVIEW`.

A real `openai` request with `gpt-5.6-terra` reached the provider but failed safely with HTTP 429 after two
calls/one bounded retry (5,408 ms); no confirmation or activation occurred. This is failure-path evidence
only. **Required before submission:** complete one successful real-model run through interpretation, server
validation, ontology resolution, and non-empty preview to `READY_FOR_REVIEW`, without activation.

See [AI authoring](docs/ai-authoring.md) and [AI-assistance disclosure](docs/ai-assistance.md).

## Known limitations

- The successful real-model evidence above remains a required blocker until provider capacity/quota permits.
- The demo uses one broker node and synchronous database-backed evaluation; production would add HA,
  observability, secret management, retention policies, and horizontally partitioned workers.
- Screenshots are supplied as an exact capture checklist because browser capture was unavailable in this
  environment; no images are fabricated.
- Acknowledgement/work-order workflows and all bonus requirements are intentionally out of scope.
