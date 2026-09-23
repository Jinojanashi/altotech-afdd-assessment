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
make ai-live-demo  # real provider demo; requires OPENAI_API_KEY only here
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
override, non-trigger cases, historical backtesting, ingestion exceptions, and the AI trust boundary. Captured
review evidence is indexed in [the screenshot gallery](docs/screenshots/README.md).
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
the [documentation guide](docs/README.md), and the [validation/requirement report](docs/validation-report.md).

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

## Historical Backtesting (Bonus)

The Rule Detail screen can run a historical what-if simulation for an immutable rule version and selected
UTC window. An engineer may override threshold and duration for the simulation; without those values,
property-specific overrides from that version remain effective. The response identifies matched/excluded
targets, hypothetical qualification/open/recovery times, effective values, and useful non-trigger reasons.

Backtesting reuses the production ontology resolver and deterministic AFDD state transition. It is explicitly
read-only: it does not activate a rule, create issues, update evaluator state, or change telemetry. The first
implementation is intentionally limited to the existing SAT absolute-deviation DSL and evaluates only
observations inside the requested window; it does not carry qualification state in from before the window.

## MCP Interface (Optional Bonus)

The optional MCP service provides a narrow interoperability interface for an MCP-compatible local client; it
is not needed by `make demo`, the API, the dashboard, or AFDD evaluation. Start its standard stdio transport
only when needed:

```bash
docker compose --profile mcp run --rm -i mcp
```

It exposes only `get_portfolio_summary`, `get_equipment_context`, `get_issue_detail`, and
`preview_rule_targets`. These tools call existing read/query and rule-preview functions, returning
canonical IDs and explicit topology rather than guessing from names. There are deliberately no MCP tools for
activation, confirmation, creation, telemetry writes, ontology changes, raw SQL, shell/filesystem access, or
secrets. The interface has no authentication and is intended only for local assessment review; it uses stdio
and has no network listener.

## AI-assisted authoring

The model can only return a constrained interpretation. Server code resolves current ontology IDs, validates
the existing rule DSL, previews targets/exclusions, and requires explicit human confirmation before creating
or activating anything. Bounded tools cannot execute arbitrary SQL/code, create assets, or activate rules.
Fake-provider tests cover supported/paraphrased prompts, clarification, injection/unsupported logic, invented
assets, ontology changes, malformed output/retry, missing provider, and idempotent confirmation.

For a real-provider review-state run, first run `make demo`, then place a key only in ignored `.env`
and set `OPENAI_MODEL`. Run:

```bash
make ai-live-demo
```

This target invokes the existing authoring orchestration, prints a sanitized evidence summary, never confirms or
activates, and exits non-zero unless it reaches `READY_FOR_REVIEW`.

A successful OpenAI `gpt-5.6-terra` run reached `READY_FOR_REVIEW`: validation passed, the ontology-backed
preview matched 8 targets and excluded 16, and no human confirmation or activation occurred. The earlier HTTP
429 result (two calls/one bounded retry; 5,408 ms) remains additional failure-path evidence only.

See [AI authoring](docs/ai-authoring.md) and the preserved [raw evidence](docs/evidence/).

The required AI-use disclosure is in [AI assistance](docs/ai-assistance.md).

## Documentation

The short [documentation guide](docs/README.md) gives the recommended review order. Detailed material is split
by concern: [architecture](docs/architecture.md), [AFDD semantics](docs/afdd.md), [AI safety](docs/ai-authoring.md),
[demo steps](docs/demonstration-guide.md), and [validation evidence](docs/validation-report.md).

## Known limitations

- The demo uses one broker node and synchronous database-backed evaluation; production would add HA,
  observability, secret management, retention policies, and horizontally partitioned workers.
- Local browser screenshots are evidence of the captured run; generated IDs and browser-local timestamp
  rendering may differ on a fresh replay.
- Acknowledgement/work-order workflows, additional rule types, and production cloud infrastructure are out of scope.
