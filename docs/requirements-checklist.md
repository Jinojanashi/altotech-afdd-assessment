# Assessment requirement checklist

This matrix was created before Milestone 7 implementation changes and then updated after validation. `Covered`
means an implementation and automated test already existed at audit time. `Closed M7` identifies a required delivery gap closed by this
milestone. `Blocked` is deliberately not presented as complete.

| Requirement | Status | Implementation | Test/evidence | Demo/documentation |
|---|---|---|---|---|
| Configurable CSV simulator | Covered | `apps/simulator`, `afdd.simulator` | `test_telemetry_pipeline.py` | README telemetry section |
| Kafka-compatible broker | Covered | `redpanda`, `redpanda-init` Compose services | topic description / clean replay | `architecture.md` |
| Separate ingestion consumer | Covered | `apps/ingestion` | duplicate, reject, gap tests | ingestion status in Portfolio |
| Canonical relational ontology | Covered | migrations 0001/0002, `afdd.seed`, `afdd.ontology` | ontology seed suite | Portfolio/equipment topology |
| TimescaleDB history and latest state | Covered | migration 0003, `afdd.telemetry` | history/current non-regression tests | telemetry API and dashboard |
| Duplicate idempotency | Covered | unique event/source identity and attempt audit | duplicate/replay test | ingestion status |
| Late/out-of-order handling | Covered | conditional current-value upsert | late-history test | technical decisions/demo guide |
| Unknown, blank, missing, stale visibility | Covered | ingestion audit; derived missing/stale semantics | telemetry and AFDD tests | dashboard states/demo guide |
| Health/operational visibility | Covered | `/health`, `/ingestion/status`, `/portfolio` | API/frontend tests | Portfolio health strip |
| Versioned reusable AFDD rule | Covered | migration 0004, `afdd.rules` | schema/immutability tests | Rule detail |
| Ontology target preview/exclusions | Covered | `preview_draft` | preview/missing-point tests | Rule preview |
| Property-specific override | Covered | immutable override rows | default-vs-override test | Building B preview |
| Observed-time deterministic evaluation | Covered | `afdd.evaluator` | replay/timing/late tests | `afdd.md` |
| 15-minute, freshness, OFF/missing behavior | Covered | evaluator state machine | AFDD scenario suite | issue evidence/demo guide |
| Recovery, recurrence, immutable version/evidence | Covered | issue/state tables | lifecycle/version tests | Issue investigation |
| Served/affected-room traversal | Covered | relational edges and preview | topology/AFDD tests | issue topology |
| Portfolio dashboard | Covered | `/portfolio`, `PortfolioView` | frontend test | `/portfolio` |
| Issue investigation and telemetry context | Covered | issue/context projections and views | frontend/API/AFDD tests | issue route |
| Loading/empty/error/insufficient states | Covered | shared `State`, `TelemetryValue` | frontend test | screenshot checklist |
| Rule detail, preview, exclusions, override | Covered | `RuleView` | frontend test | rule route |
| Stateful AI authoring with bounded tools | Covered | migration 0005, `afdd.ai_authoring` | AI test matrix | `/rules/new/ai` |
| Structured draft and server ontology validation | Covered | interpretation schema/resolution pipeline | supported/hallucination/change tests | AI review state |
| Clarification/rejection/provider failure | Covered | persisted terminal/clarification paths | AI matrix | AI docs/demo guide |
| Human-only confirmation; no model activation | Covered | confirmation endpoint and state guard | exactly-once/guard tests | AI review button |
| AI audit trace | Covered | request state/tool/provider metadata | AI tests and persisted 429 evidence | AI docs |
| Real provider integration/failure path | Covered | OpenAI Responses adapter | real 429: 2 calls, 1 retry, safe `FAILED` | AI docs |
| Successful real-model review-state run | **Blocked** | command exists; provider quota prevented success | successful live evidence absent | explicit pre-submission blocker |
| Docker Compose/migrations/seed/reset/replay | Covered | Compose, Alembic, seed CLI | clean validation required in M7 | README |
| One-command deterministic demo and checks | **Closed M7** | `Makefile`, demo verifier/script | clean volume run | README/demo guide |
| OpenAPI verification | **Closed M7** | FastAPI generated schema | live `/docs` and `/openapi.json` check | README |
| Final reviewer docs/technical decisions/Q&A | **Closed M7** | docs set | consistency review | README links |
| Screenshot or precise capture walkthrough | **Closed M7** | screenshot checklist (no browser automation available) | reviewer capture sequence | `screenshot-walkthrough.md` |
| AI-assistance disclosure | **Closed M7** | documentation | real correction examples | README/technical docs |
| Full clean quality and repository hygiene pass | **Closed M7** | Make targets and validation | final command log | `validation-report.md` |

## Gaps identified before Milestone 7 changes

The product requirements were implemented, but submission/reviewer requirements were incomplete: there was
no deterministic top-level demo orchestration or completion verifier; README and architecture retained stale
milestone wording; the demonstration, tradeoff, reviewer-question, screenshot, and final audit documents were
absent; and OpenAPI plus a genuinely clean application start had not been included in a final validation.
The successful live-model run remains a required external blocker after the already observed HTTP 429.

Bonus requirements are intentionally absent. No Neo4j/RDF service, telemetry interpolation, speculative
diagnostics, or additional rule type is introduced by the closeout work.
