# Safe AI-assisted AFDD rule authoring

The authoring workflow is an orchestration layer around the existing immutable rule DSL. The model produces only a constrained `Interpretation`; it cannot create assets, execute SQL/code, call arbitrary URLs, or activate rules. OpenAI Responses API is the implemented real provider and is configured with `OPENAI_API_KEY` and `OPENAI_MODEL`. Missing credentials produce an auditable `FAILED` request rather than a server crash.

## Trust boundary and state machine

The persisted path is `RECEIVED → INTERPRETING → DISCOVERING → VALIDATING → PREVIEWING → READY_FOR_REVIEW → CONFIRMED → ACTIVATED`. It can branch to `NEEDS_CLARIFICATION`, `REJECTED`, `FAILED`, or `STOPPED`. State history, interpretation, drafts, tool inputs/results, validation, preview, provider/model, retries, latency, confirmation time, and activation result are stored in `ai_authoring_requests`.

Server-owned bounded tools are `get_supported_capabilities`, `search_ontology`, `validate_rule_draft`,
`resolve_rule_targets`, and `preview_rule`. They wrap current ontology and rule-domain functions. Structured
output separates property, floor, and served-space usage queries. Every free-text reference is exact-matched
against the current typed ontology before a `RuleDraft` exists; model-provided IDs are never trusted directly.

If a reference is placed in the wrong dimension but uniquely matches one other allowed dimension, the server
reclassifies it and persists `scope_reference_reclassified` in warnings and the tool trace. Multiple possible
dimensions produce `NEEDS_CLARIFICATION`; no match produces `REJECTED`. Unsupported logic, missing intent,
unknown assets, and empty target sets are never silently simplified.

Only `POST /ai/authoring-requests/{id}/confirm` can create and activate a rule. It first locks the request and persists `CONFIRMED` with a human timestamp. The model has no activation tool. Repeated confirmation returns the prior result without creating another rule/version.

## API and UI

- `POST /ai/authoring-requests`
- `GET /ai/authoring-requests/{id}`
- `POST /ai/authoring-requests/{id}/clarification`
- `POST /ai/authoring-requests/{id}/confirm`
- `POST /ai/authoring-requests/{id}/cancel`
- UI: `/rules/new/ai`

Clarification resumes the same request. Review displays original intent, constrained draft, threshold, duration, severity, required points, matches, exclusions, warnings, and audit trace before the confirmation button is enabled.

## Retry and provider behavior

Interpretation is attempted at most twice. Malformed output or provider failure is persisted with retry count and stop reason. The only supported rule semantics are the existing observed-time `SAT_ABSOLUTE_DEVIATION` rule with `RUN=ON`, `SAT`, `SAT_SP`, operator `>`, and `degC`. AI authoring does not add new evaluator logic or control equipment.

Automated tests use deterministic fake clients and never require a network or API key. To make one real call without activation, put the key only in ignored `.env` and run:

```bash
make ai-live-demo
```

The target prints only sanitized workflow evidence, never calls confirmation, and exits non-zero unless the
supported request reaches `READY_FOR_REVIEW`.

A successful real OpenAI `gpt-5.6-terra` request (`5bb1b689-0d7d-4a0b-8465-3b879aeecc2c`) reached
`READY_FOR_REVIEW` in one call with zero retries and 4,601 ms latency. Validation passed; the ontology-backed
preview matched 8 Building A AHUs and excluded 16. The workflow intentionally stopped with
`human_confirmed_at = null` and `activation_result = null`.

A separate real request made two calls with one bounded retry and ended safely in `FAILED` after HTTP 429;
it also had no confirmation or activation. Another real response placed a served-space usage in the property
dimension and was safely rejected by the then-current resolver. That evidence motivated the generic typed
normalization described above; there is no literal-value special case.

Raw sanitized outputs are preserved under [`evidence/`](evidence/). These provider runs complement, rather
than replace, deterministic fake-client coverage in the automated suite.

## Limitations

The model can author only the existing SAT absolute-deviation DSL. Production use would also require identity,
RBAC, approval policy, provider observability, cost controls, and governed audit retention. Those concerns do
not weaken the current rule-validation or human-confirmation boundary.

## AI-assistance disclosure

Codex was used to inspect the assessment, propose implementation code, and run validation. Generated work was
reviewed through migration execution, deterministic scenario tests, full backend/frontend suites, lint,
typecheck, and end-to-end API checks. One generated design idea—placing model-proposed asset IDs directly into
the rule draft—was rejected; the workflow resolves every scope reference against the current server ontology
before validation and preview. The full disclosure is in [`ai-assistance.md`](ai-assistance.md).
