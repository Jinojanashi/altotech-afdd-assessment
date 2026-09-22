# Architecture

## Scope

This repository provides the deployable foundation for replaying the supplied telemetry, ingesting it,
evaluating the required AHU fault rule, and exposing results through an API and web application. It does
not yet implement the dashboard, production ingestion/evaluation logic, or AI rule authoring. Source CSVs
remain immutable inputs.

## Components

```text
candidate CSVs -> simulator -> telemetry.raw.v1 -> ingestion -> TimescaleDB
                                      Redpanda          |
                                                        +-> telemetry.accepted.v1 -> AFDD worker
                                                                                         |
web -> FastAPI API ----------------------------------------------------------> PostgreSQL/TimescaleDB
```

- **Simulator:** converts each source snapshot into a versioned device event. Playback uses source time,
  a configurable output interval, and an acceleration factor.
- **Ingestion consumer:** validates identity and ontology references, records every event disposition,
  writes history idempotently, and only updates current state when `observed_at` is newer.
- **AFDD worker:** consumes accepted observations and maintains deterministic per-equipment evaluation
  state and issue lifecycle.
- **API/web:** FastAPI is the service boundary; React/TypeScript is currently an application shell.
- **Storage:** PostgreSQL stores application state and a relational Brick-aligned ontology. TimescaleDB
  hypertables store time-series readings. Neo4j is intentionally not used.

## Event and delivery decisions

`TelemetryEvent` carries a deterministic UUID event ID derived from source identity, upstream
`source_record_id`, source and receipt timestamps,
equipment ID, point values/units/quality, and schema version. Ingestion uniqueness on
`(source_system, source_record_id)` makes Redpanda's at-least-once delivery safe, while a separate attempt
log keeps duplicate deliveries visible without repeating a business effect. Raw events use a topic key of
equipment source ID so per-equipment order is stable within a partition. Replaying uses a new consumer
group while database idempotency prevents duplicate business effects. Late history is retained but cannot
replace a newer current value.

The simulator retains source-file row order and publishes snapshots through Redpanda; it never writes to the
database. Ingestion performs canonical equipment/point resolution in one transaction and manually commits
the broker offset afterward. Event and source-record uniqueness makes replay idempotent. Observation history
uses source time, while the current table advances only when source time is newer. Empty measurements and
absent device intervals create no rows; freshness/staleness is computed later rather than synthesized.

## Relational ontology

`ontology_entities` gives spaces, equipment, and points a common identity and Brick class.
`ontology_relationships` stores Brick-style predicates. `hasPart` represents containment, `hasLocation`
the installed location, `feeds` the AHU-to-served-zone relationship, and `hasPoint` point ownership.
Measurement scope is represented by a `meters` relationship from sensor or meter to the room or floor
supplied by the register. Subtype tables retain application fields and constraints. Relationships are loaded from the
registers rather than inferred from readable IDs.

The seed importer uses the CSV source IDs as canonical external identifiers. It validates all supplied
references before writing, upserts entities and subtype rows, and adds relationships with conflict-safe
inserts. `hasLocation` records physical installation, while `feeds` records the AHU's served zone; these are
intentionally never conflated. The only reset option truncates canonical entities with dependent local data
and is limited to local development/review.

## AFDD lifecycle defaults

Inputs are fresh for 120 seconds (twice the expected 60-second interval). A qualifying window requires
the AHU to remain ON and all required points to be valid and fresh; OFF, missing, invalid, or stale input
resets the window. A continuous absolute SAT error over 3°C for 15 minutes opens one Critical issue. The
issue closes on the first trusted normal observation. A later sustained deviation creates a new occurrence.
Each issue references the immutable rule version and stores opening evidence. One property-scoped override
may change threshold or duration without affecting other properties.

## Main risks

1. Out-of-order and duplicate events could corrupt current state or timers; event uniqueness and conditional
   current-state updates are mandatory.
2. Incorrect ontology edges could evaluate the wrong tenant spaces; imports must validate source references
   and expose unresolved entities.
3. Missing or stale data could look like recovery or a fault; quality/disposition data must remain visible
   and evaluation must fail safe.
