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
