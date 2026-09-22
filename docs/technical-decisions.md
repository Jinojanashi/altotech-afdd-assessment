# Technical decisions and tradeoffs

| Choice | Why here | Tradeoff / larger-scale direction |
|---|---|---|
| PostgreSQL relational ontology | The source is relational and required traversals fit explicit typed edges; one transactional store keeps the assessment simple. | Recursive/complex semantic queries are less expressive than RDF; at scale, add closure/materialized projections or a governed graph service only if query evidence warrants it. |
| TimescaleDB history | Hypertables retain PostgreSQL joins/transactions while optimizing observed-time data. | One node is the demo boundary; production needs chunk/retention/compression policy and HA sizing. |
| Redpanda | Kafka compatibility supports keyed, partitioned event replay with a small local operational footprint. | Single-node Compose is not resilient; production needs replicated brokers, schema governance, ACLs, lag alerts, and retention planning. |
| Separate simulator/ingestion | It proves a real event boundary and prevents a source reader from bypassing validation. | More services to operate; production would autoscale and independently deploy them. |
| Database idempotency | Stable UUIDv5 plus unique source identity protects business effects even during replay/crash. | Database contention can grow; partitioning/batching and broker transactions may be needed later. |
| `observed_at` and `received_at` | Device time drives history/rules; receipt time explains delivery and ordering. | Requires clock-quality policy in production; extreme/future skew should be quarantined explicitly. |
| Latest non-regression | A conditional upsert advances current state only for newer observation time; event ID breaks equal-time ties. | Equal-time tie-breaking is deterministic, not semantic; a source sequence would be preferable if available. |
| Platform-derived quality | Recognized, typed observations become `GOOD`; missing/stale are derived and rejected input is audited. | Rich production quality should preserve device flags and validation provenance. |
| 120-second freshness | Twice the stated 60-second cadence tolerates one delayed interval without trusting old state indefinitely. | It is a candidate policy, not source fact; production should configure it by point/source SLA. |
| Deterministic state machine | `NORMAL/QUALIFYING/OPEN` and observed-time replay make outcomes testable and explainable. | Database polling is simple but not high-throughput; production could use partitioned stream state plus checkpoints. |
| Continuous duration | Qualification opens when `observed_at - start >= 900s`, with trustworthy samples and no gap over freshness. | It assumes source cadence is meaningful; irregular sources may need coverage/availability calculations. |
| Immutable rule versions | Editing inserts a new version and activation is explicit, preserving historical meaning. | Versions accumulate; production needs lifecycle/governance and approval metadata. |
| Persisted issue evidence | Opening samples, topology, effective config, and recovery are reviewable after rules/ontology evolve. | JSON duplicates data; production may tier/archive evidence and maintain a formal schema version. |
| Property override rows | A building-scoped override is explicit, validated, and visible in preview/evidence. | Only threshold/duration are supported; broader policy inheritance would need conflict rules. |
| Dashboard read projections | Purpose-built queries keep the client thin and preserve topology semantics. | Current queries are synchronous/N+1 at portfolio scale; production would batch or materialize projections. |
| Bounded AI tools | The workflow exposes only capabilities, ontology search, validation, resolution, and preview. | It supports one DSL; new logic requires intentionally extending both validator and evaluator. |
| Server-authoritative resolution | Model labels/IDs are re-resolved against current ontology before a draft exists and again before confirmation. | Extra round trips and clarification are safer than silently guessing; production needs richer disambiguation UX. |
| Human confirmation boundary | The provider has no activation tool; only a locked confirmation endpoint creates/activates exactly once. | Adds operator friction; production should add identity, RBAC, approval policy, and audit export. |

Recovery on the first fresh trusted non-fault/OFF sample, the 2°C Building B override, six broker partitions,
and UUID/event envelope design are candidate choices. They are not claimed as source-supplied facts.
