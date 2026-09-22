# AFDD Assessment

Initial project skeleton for the Senior Full Stack Engineer AFDD assessment.

## Services

- `simulator`: replays the supplied CSV snapshots into Redpanda.
- `ingestion`: validates and persists telemetry events.
- `worker`: evaluates AFDD rules from accepted telemetry.
- `api`: FastAPI application for platform APIs.
- `web`: React and TypeScript operations dashboard.
- `db`: PostgreSQL with TimescaleDB.
- `redpanda`: Kafka-compatible event broker.

The dashboard, ingestion pipeline, and deterministic AFDD evaluator are implemented as focused assessment
milestones. AI-assisted rule authoring is intentionally out of scope.

## Local setup

```bash
cp .env.example .env
docker compose up --build
```

The API health endpoint is available at `http://localhost:8000/health` and the web shell at
`http://localhost:3000`. Database migrations run once before the application services start.

See [`docs/architecture.md`](docs/architecture.md) for the design and
[`docs/understanding-checkpoint.md`](docs/understanding-checkpoint.md) for the assessment checkpoint.

## Database inventory

Run the canonical inventory migration and seed it from the supplied registers:

```bash
docker compose up -d db
docker compose run --rm migrate
docker compose --profile tools run --rm seed
```

The seed is idempotent: rerunning the last command updates the same canonical entities and does not create
duplicate edges. For a local review reset, which clears canonical inventory and all dependent local data,
run:

```bash
docker compose --profile tools run --rm seed python -m afdd.seed --reset
```

Ontology inspection endpoints are `GET /properties`, `GET /entities/{source_id}`,
`GET /entities/{source_id}/relationships`, `GET /equipment/{source_id}/datapoints`, and
`GET /equipment/{source_id}/topology`.

The relational ontology preserves separate concepts for where an AHU is installed (`hasLocation`) and the
HVAC zone it serves (`feeds`); affected rooms are reached through the served zone's explicit containment
edges, never from a readable identifier.

## Telemetry pipeline

The simulator publishes one versioned device-snapshot event per CSV row to the six-partition
`telemetry.raw.v1` Redpanda topic. File order is deterministic (`ahu`, `iaq`, then `power`) and row order
within each source file is preserved, including the deliberate late and duplicate rows. Blank measurements
are omitted; the platform never interpolates gaps or creates synthetic `GOOD` observations.

```bash
docker compose up -d db redpanda
docker compose run --rm migrate
docker compose --profile tools run --rm seed
docker compose up -d ingestion
docker compose --profile telemetry run --rm simulator python -m apps.simulator.main --delay-seconds 0
```

Replay uses stable UUIDv5 event IDs derived from `(source, source_record_id)`. The consumer commits a Kafka
offset only after its database transaction succeeds. Canonical history is protected by database uniqueness;
each later delivery is recorded as `DUPLICATE` without another observation. Current state advances only for
a greater device `observed_at` (equal timestamps use event ID as a deterministic tie-breaker), never receipt
order.

Transport events contain `schema_version`, `event_id`, `source`, `source_record_id`, `equipment_id`,
`equipment_type`, `observed_at`, `received_at`, `source_file`, and a measurement list. Ingestion resolves
point identity, data type, ownership, and engineering unit from the canonical registry. Valid reported values
are `GOOD`; invalid/unknown events are audited as `REJECTED`. Missing and stale values are derived on read or
evaluation and are not persisted as fake observations.

Useful inspection commands:

```bash
docker compose exec redpanda rpk topic describe telemetry.raw.v1
docker compose exec db psql -U afdd -d afdd -c "SELECT processing_status, count(*) FROM ingestion_events GROUP BY 1"
curl http://localhost:8000/ingestion/status
curl http://localhost:8000/telemetry/equipment/ahu-a-f01-east/latest
```

## AFDD rule evaluation

The supplied SAT-deviation rule is a validated, versioned DSL with ontology-based target preview. Rule
versions and their property overrides are immutable. The default demonstration scope selects the eight
office floors in Buildings A and B; Building B has an explicit 2.0°C threshold override while all other
targets use 3.0°C. See [docs/afdd.md](docs/afdd.md) for exact timing, freshness, recovery, recurrence, and
evidence semantics.

After telemetry ingestion, create/activate the default rule, clear prior evaluation results, and replay all
accepted events deterministically:

```bash
docker compose run --rm worker python -m apps.worker.main \
  --ensure-default-rule --reset --once
curl http://localhost:8000/rules
curl http://localhost:8000/issues
```

Rule validation and preview are available through `POST /rules/validate` and `POST /rules/preview`. Stored
versions can be previewed at `GET /rules/{rule_id}/versions/{version}/preview`; evaluation remains in the
separate worker and is never performed by an API request.
# AFDD assessment

## Operations dashboard

Start the full local demo with `docker compose up --build`, then open [http://localhost:3000/portfolio](http://localhost:3000/portfolio). The API is available at [http://localhost:8000](http://localhost:8000).

The focused routes are `/portfolio`, `/issues/{issueId}`, and `/rules/{ruleId}`. Portfolio uses the read-only `/portfolio` projection for canonical building/floor/zone/AHU navigation and operational health; `/equipment/{sourceId}/context` exposes room IAQ and floor-meter context without treating a floor meter as an AHU point.

For the hero journey, open Building A in Portfolio, select `ahu-a-f02-east`, then select its Critical recent issue. The investigation explicitly shows its plant-room installation separately from the served HVAC zone and potentially affected rooms, then links to the rule preview where the Building B override is visible.

## AI-assisted rule authoring

Open `http://localhost:3000/rules/new/ai` for the safe authoring workflow. Configure `OPENAI_API_KEY` and optionally `OPENAI_MODEL` in `.env`; without a key the request fails safely and records the reason. The model only proposes structured intent. Server-side ontology discovery, DSL validation, target preview, human review, and explicit confirmation are mandatory.

Run one real-model interpretation and preview without activation with:

```bash
docker compose run --rm api python -m afdd.ai_demo
```

See [docs/ai-authoring.md](docs/ai-authoring.md) for states, trust boundaries, bounded tools, retries, limitations, and the AI-assistance disclosure.
