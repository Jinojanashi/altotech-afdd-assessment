# Reviewer interview notes

1. **Why relational ontology, not Neo4j?** The supplied registers and required traversals map cleanly to
   `ontology_entities` plus unique `(subject, predicate, object)` rows in PostgreSQL. It keeps seed, telemetry,
   rules, and topology transactional without adding an assessment-only datastore.
2. **Why Redpanda?** It supplies the required Kafka-compatible event boundary locally. The six-partition
   `telemetry.raw.v1` topic is keyed by equipment, so equipment ordering is stable while services stay separate.
3. **How does idempotency work?** The simulator derives UUIDv5 from source and `source_record_id`; database
   uniqueness protects both event ID and source identity. Offset commit occurs only after the DB transaction.
4. **Exact duplicate?** A new `ingestion_attempts` row is `DUPLICATE`; canonical event, observations, current
   state, and evaluator business effects are not written again.
5. **`observed_at` vs `received_at`?** Source/device time drives history and AFDD. Platform receipt time records
   delivery order/latency and is retained for audit.
6. **Late history without latest regression?** History is keyed by original observation; current state updates
   only for a greater observed timestamp (event ID deterministically breaks equality). The evaluator ignores
   equal/older device time after its checkpoint.
7. **Freshness policy?** RUN, SAT, and SAT_SP must be present, `GOOD`, and no older than 120 seconds relative to
   the evaluated sample; a gap over 120 seconds breaks an in-progress window.
8. **Why 120 seconds?** It is the candidate-chosen allowance of twice the stated 60-second source interval,
   tolerating one delayed interval while failing safe on prolonged silence.
9. **Continuous 15 minutes?** The first trustworthy ON sample above the strict threshold starts `QUALIFYING`.
   Every forward sample must preserve trust/continuity; opening occurs when observed-time delta reaches 900s.
10. **Why open at 10:15?** The first hero qualifying sample is 10:00; the 10:15 sample is exactly 900 seconds
    later. Both boundaries participate, producing one issue at 10:15.
11. **What breaks qualification?** OFF, trusted difference at/below threshold, missing/invalid/stale required
    input, or a gap greater than freshness resets `QUALIFYING`.
12. **While OFF?** A qualifying window resets. If already open, a fresh trustworthy OFF sample closes the issue
    with `AHU_OFF`; OFF cannot open a fault.
13. **Missing SAT_SP?** The sample is `UNTRUSTWORTHY_INPUT`; it cannot qualify or falsely recover an open issue.
    `ahu-a-f04-west` demonstrates no false trigger.
14. **Telemetry gaps?** No points are synthesized. A gap can remain in history and, beyond 120 seconds, resets
    continuity when the next sample is evaluated.
15. **Recovery?** The first fresh trusted OFF or difference at/below threshold closes immediately, appending
    reason and recovery sample to evidence. Missing/stale input does not falsely close an open issue.
16. **Recurrence?** After closure the state returns to `NORMAL`; a later full qualification creates the next
    occurrence row. A partial/open window cannot create duplicate issues.
17. **Why store opening rule version?** Versions are immutable and issues FK the exact opening version, so later
    edits/activation cannot rewrite why an existing issue opened.
18. **Why persist evidence?** Samples, effective config, topology, and recovery preserve an explainable audit
    even if latest telemetry, active rule, or ontology later changes.
19. **Installation vs served/affected?** `hasLocation` points to the plant room. `feeds` points to the HVAC zone,
    and `hasPart` reaches occupied rooms. Only the latter are potentially affected.
20. **Why is floor meter context?** The source explicitly says `measurement_scope_id=floor`; `meters` records
    that scope. The dashboard joins it as context and never creates AHU ownership/`hasPoint` edges.
21. **Property override?** An immutable rule-version override references canonical `building-b`. Preview resolves
    an AHU’s property via zone/floor/building edges and yields 2°C there, 3°C elsewhere.
22. **Why bounded AI tools?** This implementation exposes only supported capabilities, ontology search,
    validation, target resolution, and preview. It prevents the model from widening scope or executing code/SQL.
23. **Why can’t the model activate?** No activation tool is available. A locked server endpoint accepts only a
    `READY_FOR_REVIEW` request, records human confirmation, then creates/activates exactly once.
24. **Hallucinated asset ID?** Server resolution against current canonical IDs/display names fails and persists
    `REJECTED`; it never silently converts the invented asset into a target.
25. **Ontology changes after interpretation?** Confirmation re-resolves/revalidates the stored draft against the
    current ontology. Drift that removes valid scope/targets prevents activation.
26. **Provider failure?** At most two calls occur. The request becomes auditable `FAILED` with latency/retry/stop
    reason and no confirmation/activation. The real 429 run proves this path.
27. **What changes at production scale?** Replicated brokers/database, schema registry, RBAC/secrets manager,
    telemetry retention/compression, batch/partitioned ingestion, checkpointed streaming evaluation, materialized
    dashboard projections, metrics/tracing/alerts, clock-quality rules, and governed multi-user approvals.
