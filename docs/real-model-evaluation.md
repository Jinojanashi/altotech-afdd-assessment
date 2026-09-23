# Real Model Evaluation

A real OpenAI model was executed through the AI-assisted rule-authoring workflow.

## Successful supported-request run

- Provider: OpenAI
- Model: gpt-5.6-terra
- Request ID: `5bb1b689-0d7d-4a0b-8465-3b879aeecc2c`
- Final state: `READY_FOR_REVIEW`
- Model calls: 1
- Retry count: 0
- Latency: 4601 ms
- Validation: passed
- Matched targets: 8
- Excluded targets: 16
- Human confirmation: none
- Activation: none

### Workflow states

`RECEIVED`
→ `INTERPRETING`
→ `DISCOVERING`
→ `VALIDATING`
→ `PREVIEWING`
→ `READY_FOR_REVIEW`

### Interpreted rule

The real model interpreted the request as:

- Equipment type: AHU
- Property: Building A
- Severity: Critical
- Measurement comparison: `abs(SAT - SAT_SP)`
- Operator: `>`
- Threshold: `3.0 degC`
- Duration: `900 seconds`
- Operating condition: `RUN = ON`

### Target preview

The server-side ontology resolver matched 8 AHUs in Building A and excluded 16 AHUs outside the selected scope.

The matched equipment was:

- `ahu-a-f01-east`
- `ahu-a-f01-west`
- `ahu-a-f02-east`
- `ahu-a-f02-west`
- `ahu-a-f03-east`
- `ahu-a-f03-west`
- `ahu-a-f04-east`
- `ahu-a-f04-west`

### Safety result

The real model was allowed to interpret the request, but server-side validation,
ontology resolution, and target preview remained authoritative.

The workflow intentionally stopped at `READY_FOR_REVIEW`.

No human confirmation was recorded and no rule was activated:

- `human_confirmed_at = null`
- `activation_result = null`

This demonstrates that natural-language authoring cannot bypass validation,
ontology resolution, preview, or explicit human confirmation.

## Additional failure-path evidence

Separate real-model/provider runs also demonstrated safe failure handling,
including bounded retry on provider HTTP 429 responses and rejection of
unresolved ontology references.

Those failures did not create or activate rules.
