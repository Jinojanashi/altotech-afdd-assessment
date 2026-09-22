# AFDD rule engine

## Rule contract and versioning

A rule identity (`afdd_rules`) owns immutable numbered rows in `afdd_rule_versions`. An active edit always
inserts the next version; it does not change the active version until explicit activation. Database triggers
reject updates to version and override rows. Issues reference both the rule identity and exact opening
version, and keep a JSON evidence snapshot so later edits cannot rewrite history.

The validated DSL has two independent sections:

```json
{
  "scope": {
    "equipment_type": "AHU",
    "property_type": "Office",
    "property_ids": ["building-a", "building-b"],
    "floor_ids": ["building-a-f01", "..."],
    "served_zone_usage_types": ["Tenant Area"],
    "occupied_room_usage_types": ["Office Room"],
    "required_points": ["RUN", "SAT", "SAT_SP"]
  },
  "logic": {
    "kind": "SAT_ABSOLUTE_DEVIATION",
    "operator": ">",
    "threshold": 3.0,
    "duration_seconds": 900,
    "freshness_seconds": 120
  },
  "overrides": [{"property_id": "building-b", "threshold": 2.0}]
}
```

The demonstration override intentionally changes Building B's threshold to 2.0°C. It is resolved from the
explicit building relationship and affects only that property's targets.

## Ontology targeting and preview

Targeting traverses stored edges: AHU `feeds` HVAC zone, zone `isPartOf` floor, floor `isPartOf` building,
zone `hasPart` rooms, AHU `hasLocation` installation room, and AHU `hasPoint` required points. It never
parses a readable ID. The installation room is operational context and is not an affected tenant room.

Preview reports matching and excluded AHUs with property, floor, installation, served zone, occupied rooms,
effective threshold/duration, required point IDs, override, and exclusion reasons. Supported reasons are
`OUTSIDE_SELECTED_SCOPE`, `NOT_SERVING_TENANT_AREA`, and `REQUIRED_POINT_MISSING`.

## Deterministic timing

Evaluation uses device `observed_at`; broker/receipt time only establishes live delivery order. Per rule
version and equipment, state is `NORMAL`, `QUALIFYING`, or `OPEN`.

- `abs(SAT - SAT_SP) > threshold` is strict; equality does not qualify.
- RUN, SAT, and SAT_SP must all be `GOOD`, present, and no more than 120 seconds old. The allowance is twice
  the source's nominal 60-second interval.
- No interpolation occurs. Missing, invalid, future-dated, or stale input resets `QUALIFYING` to `NORMAL`.
- A gap greater than 120 seconds breaks continuity. A later qualifying sample starts a new window.
- OFF and a trusted non-fault value reset `QUALIFYING`.
- The issue opens when `current observed_at - qualifying start >= duration`; 10:00 through 10:15 opens at
  10:15 for a 900-second rule.
- Equal or older timestamps are retained by ingestion but ignored for forward state transitions.
- While an issue is open, missing/stale input does not falsely close it. A fresh OFF or trusted value at or
  below threshold closes it immediately.
- A later qualifying interval creates a new occurrence; observations during one open fault never create
  duplicate issues.

Resetting `afdd_evaluation_states` and `afdd_issues`, then replaying the same accepted events produces the
same equipment, occurrence, device-time boundaries, and evidence. Database-generated issue UUIDs may differ.

## Evidence

Opening evidence contains rule identity/version/severity and logic, effective threshold/duration/freshness,
the applied override, canonical equipment identity, property/floor, physical installation, served zone,
potentially affected occupied rooms, qualifying start/trigger times, and every RUN/SAT/SAT_SP sample in the
triggering window with timestamp, quality, age, freshness, and calculated difference. Closure appends the
recovery reason and trusted recovery sample.

## Operations and APIs

The worker is separate from ingestion and API. `--once` is the deterministic review/backfill mode; without
it, the worker polls accepted database events and advances only unseen device timestamps.

```bash
docker compose run --rm worker python -m apps.worker.main \
  --ensure-default-rule --reset --once
```

Rules: `GET/POST /rules`, `POST /rules/validate`, `POST /rules/preview`, version get/create/activate, and
disable. Issues: `GET /issues` and `GET /issues/{issue_id}`. API requests never execute the telemetry replay
or full AFDD evaluation.
