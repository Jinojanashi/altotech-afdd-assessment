# AFDD Assessment

Initial project skeleton for the Senior Full Stack Engineer AFDD assessment.

## Services

- `simulator`: replays the supplied CSV snapshots into Redpanda.
- `ingestion`: validates and persists telemetry events.
- `worker`: evaluates AFDD rules from accepted telemetry.
- `api`: FastAPI application for platform APIs.
- `web`: React and TypeScript application shell.
- `db`: PostgreSQL with TimescaleDB.
- `redpanda`: Kafka-compatible event broker.

The Python services are intentionally thin placeholders. The dashboard, complete ingestion pipeline,
AFDD evaluator, and AI-assisted rule authoring are not part of this initial skeleton.

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
