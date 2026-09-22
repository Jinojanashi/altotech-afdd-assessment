# 5–10 minute reviewer demonstration

## 1. Start from clean application data

From the repository root:

```bash
cp .env.example .env  # only if .env does not already exist
make demo
```

The command resets application rows (not source files), migrates, seeds twice, replays all 30,237 deliveries,
waits for exact ingestion completion, evaluates AFDD, and prints verified counts/evidence. For a fully blank
Docker state first, run `make demo-reset` (this removes local demo volumes) and then `make demo`.

## 2. Portfolio and health

Open <http://localhost:3000/portfolio>. Confirm API `ok`, accepted `30235`, duplicate `1`, rejected `1`, and
an AFDD evaluation timestamp. Expand Building A and locate `ahu-a-f02-east`; the Recent issues panel links its
Critical recovered issue.

Select the AHU and point out:

- installed at `building-a-plant-room`;
- serves `building-a-f02-east`;
- potentially affects `building-a-f02-east-r01` and `building-a-f02-east-r02`;
- RUN, SAT, SAT_SP with units, device timestamp, freshness, and quality;
- IAQ devices scoped to rooms and the electricity meter scoped to the floor, not owned by the AHU.

The plant room is physical installation context. Affected occupied rooms are reached separately through
`AHU --feeds--> zone --hasPart--> rooms`, so the plant room is never labeled a tenant impact area.

## 3. Hero issue evidence

Open the `ahu-a-f02-east` issue. Show Critical severity, opening rule version, 3.0°C threshold, 900-second
duration, and the observed evidence trend. Qualification begins at 10:00 UTC when RUN is ON and
`abs(SAT - SAT_SP) > 3`; continuous trusted samples reach 900 seconds at 10:15, opening one issue. The fresh
normal 10:21 sample closes it. Each stored sample exposes SAT, SAT_SP, RUN, absolute difference, quality,
age/freshness, threshold, and the qualification interval.

## 4. Rule preview, exclusions, and override

Follow **Open rule**. Show immutable version 1, freshness 120 seconds, matched/excluded target preview, and
the Building B local threshold of 2.0°C. Locate `ahu-b-f01-west`: its approximate 2.5°C deviation would not
pass the 3.0°C default, but the 2.0°C override qualifies at 11:20, opens at 11:35, and recovers at 11:41.

Use the issue list/preview to explain non-triggers: `ahu-a-f03-west` is too short, `ahu-b-f04-east` is OFF,
and `ahu-a-f04-west` has missing SAT_SP. None opens an issue. Missing/old input resets qualification rather
than being interpreted as normal or fault.

## 5. Data-quality visibility

Open <http://localhost:8000/ingestion/status> and <http://localhost:8000/ingestion/events>. The latter shows
the duplicate delivery and rejected `unknown-ahu-999`. The duplicate creates no second observations/business
effect. The late `ahu-a-f01-east` row remains available at its observed timestamp; its repeated late delivery
is audited as a duplicate and cannot regress latest state or AFDD progress.

## 6. AI trust boundary

Open <http://localhost:3000/rules/new/ai>. The page loads without a key. A supported request is:

> Create a Critical rule for office AHUs in Building A when SAT differs from SAT setpoint by more than 3°C for 15 minutes while running.

With a working configured provider, show persisted workflow stages, server-resolved scope, draft, warnings,
matches/exclusions, and audit trace in `READY_FOR_REVIEW`. The rule remains inactive until **Confirm and
activate rule** is clicked; the model itself has no activation tool. Do not confirm during evidence capture.

Without `OPENAI_API_KEY`, submission stops safely in `FAILED` and records the reason. Deterministic fake-model
coverage is run by `make test`. To attempt the real provider later, put the key only in ignored `.env`, choose
`OPENAI_MODEL`, and run `make ai-live-demo` after `make demo`. The recorded real
`gpt-5.6-terra` attempt reached OpenAI but ended in HTTP 429 after one retry; that proves only the failure path.
A successful real run reaching `READY_FOR_REVIEW` without confirmation is still required before submission.

## 7. API inspection

Open <http://localhost:8000/docs>. Swagger groups inventory/ontology, telemetry, operations/ingestion,
rules/preview, issues, portfolio projections, and AI authoring. The raw schema is at
<http://localhost:8000/openapi.json>.
