# AI-assistance disclosure

Codex was used throughout this assessment to inspect the supplied files and existing code, generate initial
service/migration/UI scaffolding, propose domain implementation, expand deterministic tests, edit documentation,
and execute validation commands. The OpenAI Responses API is also integrated as the product’s constrained rule
interpretation provider; it is not used by automated tests.

AI accelerated repetitive Compose/Docker setup, SQL and Pydantic boilerplate, test fixture coverage, and the
requirement-to-evidence matrix. Generated output was not accepted on appearance: migrations and seeds were run,
source counts were compared, telemetry was replayed end to end, database evidence was queried, backend/frontend
tests were executed, and Ruff, compileall, TypeScript, production build, Compose config, and diff checks were run.
Manual review covered dashboard routes, API/OpenAPI reachability, ontology semantics, issue evidence, and docs.

Concrete corrections from review:

- The generated web container originally served `/rules/new/ai` as a direct Nginx 404. Validation caught it;
  SPA `try_files` fallback was added and the direct route was rechecked.
- Reset initially risked leaving ingestion audit rows because they are not ontology-FK dependent. The final
  reset explicitly truncates `ingestion_events CASCADE`, making clean replay counts reproducible.
- An unsafe design possibility—putting model-proposed asset IDs directly into a rule draft—was rejected. The
  implementation resolves every property/floor reference against the live server ontology before validation,
  preview, and again at confirmation.

The real provider test used `openai/gpt-5.6-terra`. It made two calls with one bounded retry and safely ended
`FAILED` after HTTP 429 in about 5,408 ms. `human_confirmed_at` and `activation_result` remained null. This is
honestly recorded as failure-path evidence, not successful model evaluation; one successful real run reaching
`READY_FOR_REVIEW` without activation remains required before submission.
