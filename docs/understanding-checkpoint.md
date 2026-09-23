# Understanding Checkpoint

## 1. User problem

Property engineers need trustworthy, explainable detection of sustained HVAC performance problems across
multiple buildings, with enough topology and evidence to identify affected tenant areas and investigate.

## 2. System boundary

The implemented system replays supplied data, ingests and stores telemetry, models the portfolio relationally,
evaluates the required AFDD rule in a separate worker, and exposes APIs plus an operations dashboard. AI
assistance is limited to a human-gated draft workflow over the same rule DSL. Live device connectivity, work
orders, notifications, and autonomous control are outside scope. Historical backtesting and the read-only MCP
interface are optional, isolated bonus surfaces.

## 3. Domain interpretation

- An AHU is installed in a plant room but feeds a distinct occupied HVAC zone.
- A zone groups the rooms served together; containment does not imply the AHU is physically in the zone.
- A device owns typed telemetry points; observations are time-stamped values of those points.
- Missing, blank, invalid, or stale input is unknown quality, never equivalent to normal operation.

## 4. Proposed telemetry event

The versioned event includes `event_id`, `source`, `source_record_id`, `equipment_id`, `equipment_type`,
`observed_at`, `received_at`, source file, and named measurement values. A deterministic event
UUID derived from source identity plus a uniqueness constraint provides idempotency; a separate attempt log
keeps duplicate deliveries visible. Observation time drives history and AFDD, while receipt time shows
platform latency. Ingestion resolves canonical point identity, unit, and `GOOD` quality from the registry.

## 5. Proposed ontology representation

PostgreSQL tables store common entities plus space/equipment/point subtypes. Brick classes and the predicates
`hasPart`, `hasLocation`, `feeds`, and `hasPoint` carry shared semantics; source IDs, expected intervals,
value types, and ingestion metadata remain application data. Measurement scope links meters/sensors to the
represented floor or room with `meters`. No relationship is inferred by parsing an ID.

## 6. AFDD interpretation

For eligible office tenant AHUs, a window starts on the first fresh ON observation with absolute SAT error
over threshold and continues only with trusted qualifying observations. OFF or unusable input resets it.
At 15 continuous minutes it opens one Critical issue. A fresh normal observation closes it; recurrence starts
a new occurrence. The default freshness is 120 seconds, and one property may override duration or threshold.

## 7. Architecture and risks

CSV simulator -> Redpanda -> ingestion -> TimescaleDB; the independent AFDD worker evaluates accepted stored
events deterministically. FastAPI and React read PostgreSQL projections. AI interpretation is untrusted until
server validation, ontology resolution, preview, and human confirmation. The primary risks are event
ordering/idempotency, incorrect topology, and misleading conclusions from absent or stale data; mitigations
are detailed in `architecture.md`.

## 8. Assumptions and clarification questions

- A trusted normal reading closes an issue immediately; there is no recovery delay in the stated requirement.
- The two-minute freshness limit is a documented default and should be configurable.
- Property-specific means a building-level override selected through an explicit ontology relationship.
- Before product completion, confirm whether operators need acknowledgement states in addition to open/closed;
  this does not affect the required initial lifecycle.
