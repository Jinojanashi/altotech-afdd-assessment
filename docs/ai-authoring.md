# Safe AI-assisted AFDD rule authoring

The authoring workflow is an orchestration layer around the existing immutable rule DSL. The model produces only a constrained `Interpretation`; it cannot create assets, execute SQL/code, call arbitrary URLs, or activate rules. OpenAI Responses API is the implemented real provider and is configured with `OPENAI_API_KEY` and `OPENAI_MODEL`. Missing credentials produce an auditable `FAILED` request rather than a server crash.

## Trust boundary and state machine

The persisted path is `RECEIVED → INTERPRETING → DISCOVERING → VALIDATING → PREVIEWING → READY_FOR_REVIEW → CONFIRMED → ACTIVATED`. It can branch to `NEEDS_CLARIFICATION`, `REJECTED`, `FAILED`, or `STOPPED`. State history, interpretation, drafts, tool inputs/results, validation, preview, provider/model, retries, latency, confirmation time, and activation result are stored in `ai_authoring_requests`.

Server-owned bounded tools are `get_supported_capabilities`, `search_ontology`, `validate_rule_draft`, `resolve_rule_targets`, and `preview_rule`. They wrap current ontology and rule-domain functions. Model-proposed property/floor strings are resolved against current canonical IDs/display names before a `RuleDraft` exists. Unsupported logic, missing intent, unknown assets, and empty target sets are never silently simplified.

Only `POST /ai/authoring-requests/{id}/confirm` can create and activate a rule. It first locks the request and persists `CONFIRMED` with a human timestamp. The model has no activation tool. Repeated confirmation returns the prior result without creating another rule/version.

## API and UI

- `POST /ai/authoring-requests`
- `GET /ai/authoring-requests/{id}`
- `POST /ai/authoring-requests/{id}/clarification`
- `POST /ai/authoring-requests/{id}/confirm`
- `POST /ai/authoring-requests/{id}/cancel`
- UI: `/rules/new/ai`

Clarification resumes the same request. Review displays original intent, constrained draft, threshold, duration, severity, required points, matches, exclusions, warnings, and audit trace before the confirmation button is enabled.

## Retry policy and limitations

Interpretation is attempted at most twice. Malformed output or provider failure is persisted with retry count and stop reason. The only supported rule semantics are the existing observed-time `SAT_ABSOLUTE_DEVIATION` rule with `RUN=ON`, `SAT`, `SAT_SP`, operator `>`, and `degC`. AI authoring does not add new evaluator logic or control equipment.

Automated tests use deterministic fake clients and never require a network or API key. To make one real call without activation, put the key only in ignored `.env` and run:

```bash
make ai-live-demo
```

The target first runs `make verify-demo`, prints only sanitized workflow evidence, never calls confirmation,
and exits non-zero unless the supported request reaches `READY_FOR_REVIEW`.

The recorded real `openai/gpt-5.6-terra` attempt reached the provider, made two calls with one bounded retry,
and ended `FAILED` after HTTP 429 in approximately 5,408 ms. The persisted record had no human confirmation or
activation result. This validates the provider failure path only. A successful real run reaching
`READY_FOR_REVIEW` with a non-empty preview and no activation is still required before submission.

## AI-assistance disclosure

Codex was used to inspect the assessment, propose implementation code, and run validation. Generated work was reviewed through migration execution, deterministic scenario tests, full backend/frontend suites, lint, typecheck, and end-to-end API checks. One generated design idea—placing model-proposed asset IDs directly into the rule draft—was rejected; the implemented workflow resolves every property/floor reference against the current server ontology before validation and preview. The full disclosure and concrete corrections are in [`ai-assistance.md`](ai-assistance.md).
