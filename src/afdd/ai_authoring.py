"""Safe AI-assisted rule authoring with server-authoritative bounded tools."""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from afdd.rules import (
    FaultLogic,
    RuleDraft,
    TargetScope,
    activate_rule,
    create_rule,
    preview_draft,
    validate_references,
)

PROMPT_VERSION = "afdd-authoring-v1"
SCHEMA_VERSION = "interpretation-v1"
MAX_MODEL_ATTEMPTS = 2
ALLOWED_TRANSITIONS = {
    "RECEIVED": {"INTERPRETING", "FAILED", "STOPPED"},
    "INTERPRETING": {"DISCOVERING", "NEEDS_CLARIFICATION", "REJECTED", "FAILED", "STOPPED"},
    "DISCOVERING": {"VALIDATING", "REJECTED", "FAILED", "STOPPED"},
    "VALIDATING": {"PREVIEWING", "REJECTED", "FAILED", "STOPPED"},
    "PREVIEWING": {"READY_FOR_REVIEW", "REJECTED", "FAILED", "STOPPED"},
    "NEEDS_CLARIFICATION": {"RECEIVED", "STOPPED"},
    "READY_FOR_REVIEW": {"CONFIRMED", "STOPPED"},
    "CONFIRMED": {"ACTIVATED", "FAILED"},
}


class Interpretation(BaseModel):
    """Constrained intermediate intent. It is never executable by itself."""

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["SUPPORTED", "NEEDS_CLARIFICATION", "REJECTED"]
    intent: str
    property_queries: list[str]
    floor_queries: list[str]
    equipment_type: Literal["AHU"]
    left_measurement: str | None
    right_measurement: str | None
    operator: str | None
    threshold: float | None
    unit: str | None
    run_point: str | None
    run_equals: str | None
    duration_seconds: int | None
    severity: Literal["Critical", "Warning", "Info"] | None
    clarification_question: str | None
    rejection_reason: str | None


class ModelClient(Protocol):
    provider: str
    model: str

    def interpret(self, prompt: str, context: dict[str, Any]) -> Interpretation: ...


class OpenAIResponsesClient:
    """Small provider adapter using Responses API structured output."""

    provider = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def interpret(self, prompt: str, context: dict[str, Any]) -> Interpretation:
        system = (
            "Interpret an AFDD rule request. Never activate, control equipment, invent assets, or "
            "silently simplify unsupported logic. Only SAT absolute deviation from SAT_SP while RUN=ON "
            "is supported. Missing threshold or duration requires clarification. Return the schema only."
        )
        payload = {
            "model": self.model,
            "instructions": system,
            "input": json.dumps({"untrusted_user_request": prompt, "server_context": context}),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "afdd_rule_interpretation",
                    "strict": True,
                    "schema": Interpretation.model_json_schema(),
                }
            },
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"OpenAI provider unavailable: {exc}") from exc
        output_text = result.get("output_text")
        if not output_text:
            for item in result.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
        if not output_text:
            raise ValueError("OpenAI response contained no structured output")
        return Interpretation.model_validate_json(output_text)


def supported_capabilities() -> dict[str, Any]:
    return {
        "logic": "SAT_ABSOLUTE_DEVIATION",
        "measurements": ["RUN", "SAT", "SAT_SP"],
        "operator": ">",
        "unit": "degC",
        "severities": ["Critical", "Warning", "Info"],
        "duration_semantics": "continuous observed-time qualification",
        "actions": ["raise_issue"],
    }


def search_ontology(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT entity.source_id, entity.name AS display_name, space.space_type,
                   space.usage_type, parent.source_id AS parent_id
            FROM ontology_entities entity JOIN spaces space ON space.entity_id=entity.id
            LEFT JOIN ontology_relationships rel
              ON rel.subject_id=entity.id AND rel.predicate='isPartOf'
            LEFT JOIN ontology_entities parent ON parent.id=rel.object_id
            WHERE space.space_type IN ('Building','Floor') ORDER BY entity.source_id
        """)).mappings()
        return {"spaces": [dict(row) for row in rows], "equipment_types": ["AHU"]}


def _jsonable(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, UUID) else value
        for key, value in record.items()
    }


def get_request(engine: Engine, request_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT * FROM ai_authoring_requests WHERE id=CAST(:id AS uuid)"), {"id": request_id}
        ).mappings().first()
    if not row:
        raise LookupError("authoring request not found")
    return _jsonable(dict(row))


def _transition(engine: Engine, request_id: str, state: str, **updates: Any) -> None:
    allowed = {
        "interpreted_intent", "structured_draft", "reviewed_draft", "clarification_question",
        "clarification_history", "tool_trace", "validation_result", "target_preview", "warnings",
        "human_confirmed_at", "activation_result", "model_calls", "retry_count", "latency_ms", "stop_reason",
    }
    if set(updates) - allowed:
        raise ValueError("unsupported request update")
    with engine.begin() as connection:
        current = connection.execute(
            text("SELECT state,state_trace FROM ai_authoring_requests WHERE id=CAST(:id AS uuid) FOR UPDATE"),
            {"id": request_id},
        ).mappings().one()
        if state not in ALLOWED_TRANSITIONS.get(current["state"], set()):
            raise ValueError(f"invalid authoring transition: {current['state']} -> {state}")
        trace = list(current["state_trace"]) + [
            {"state": state, "at": datetime.now().astimezone().isoformat()}
        ]
        assignments = ["state=:state", "state_trace=CAST(:state_trace AS jsonb)", "updated_at=now()"]
        params: dict[str, Any] = {"id": request_id, "state": state, "state_trace": json.dumps(trace)}
        json_fields = {
            "interpreted_intent", "structured_draft", "reviewed_draft", "clarification_history",
            "tool_trace", "validation_result", "target_preview", "warnings", "activation_result",
        }
        for key, value in updates.items():
            if key in json_fields:
                assignments.append(f"{key}=CAST(:{key} AS jsonb)")
                params[key] = json.dumps(value)
            else:
                assignments.append(f"{key}=:{key}")
                params[key] = value
        connection.execute(
            text(f"UPDATE ai_authoring_requests SET {', '.join(assignments)} WHERE id=CAST(:id AS uuid)"),
            params,
        )


def _record_tool(trace: list[dict[str, Any]], name: str, arguments: Any, result: Any) -> None:
    trace.append({"tool": name, "arguments": arguments, "result": result})


def _resolve_scope(discovery: dict[str, Any], interpretation: Interpretation) -> tuple[list[str], list[str], list[str]]:
    spaces = discovery["spaces"]
    buildings = [item for item in spaces if item["space_type"] == "Building"]
    floors = [item for item in spaces if item["space_type"] == "Floor"]
    resolved_properties: list[str] = []
    unresolved: list[str] = []
    for query in interpretation.property_queries:
        matches = [item for item in buildings if query.casefold() in {item["source_id"].casefold(), item["display_name"].casefold()}]
        if len(matches) == 1:
            resolved_properties.append(matches[0]["source_id"])
        else:
            unresolved.append(query)
    resolved_floors: list[str] = []
    for query in interpretation.floor_queries:
        matches = [item for item in floors if query.casefold() in {item["source_id"].casefold(), item["display_name"].casefold()} and item["parent_id"] in resolved_properties]
        if len(matches) == 1:
            resolved_floors.append(matches[0]["source_id"])
        else:
            unresolved.append(query)
    warnings: list[str] = []
    if resolved_properties and not interpretation.floor_queries:
        resolved_floors = [item["source_id"] for item in floors if item["parent_id"] in resolved_properties]
        warnings.append("No floors specified; review includes all canonical floors in the selected properties.")
    return sorted(set(resolved_properties)), sorted(set(resolved_floors)), warnings + [f"Unresolved ontology reference: {item}" for item in unresolved]


def _process(engine: Engine, request_id: str, client: ModelClient, prompt: str) -> dict[str, Any]:
    record = get_request(engine, request_id)
    trace = list(record["tool_trace"])
    started = time.monotonic()
    _transition(engine, request_id, "INTERPRETING")
    _record_tool(trace, "get_supported_capabilities", {}, supported_capabilities())
    context = {"capabilities": supported_capabilities(), "clarifications": record["clarification_history"]}
    interpretation: Interpretation | None = None
    last_error = ""
    attempts = 0
    for attempts in range(1, MAX_MODEL_ATTEMPTS + 1):
        try:
            interpretation = client.interpret(prompt, context)
            break
        except (RuntimeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    latency = int((time.monotonic() - started) * 1000)
    if interpretation is None:
        _transition(engine, request_id, "FAILED", tool_trace=trace, model_calls=attempts,
                    retry_count=max(0, attempts - 1), latency_ms=latency,
                    stop_reason=f"Model interpretation failed after bounded retry: {last_error}")
        return get_request(engine, request_id)
    common = {"interpreted_intent": interpretation.model_dump(mode="json"), "tool_trace": trace,
              "model_calls": attempts, "retry_count": max(0, attempts - 1), "latency_ms": latency}
    if interpretation.outcome == "REJECTED":
        _transition(engine, request_id, "REJECTED", **common,
                    stop_reason=interpretation.rejection_reason or "Unsupported request")
        return get_request(engine, request_id)
    missing = []
    if not interpretation.property_queries: missing.append("building/property")
    if interpretation.threshold is None: missing.append("threshold")
    if interpretation.duration_seconds is None: missing.append("duration")
    if interpretation.outcome == "NEEDS_CLARIFICATION" or missing:
        question = interpretation.clarification_question or f"Please specify: {', '.join(missing)}."
        _transition(engine, request_id, "NEEDS_CLARIFICATION", **common, clarification_question=question)
        return get_request(engine, request_id)
    supported = (
        interpretation.left_measurement == "SAT" and interpretation.right_measurement == "SAT_SP"
        and interpretation.operator == ">" and interpretation.unit == "degC"
        and interpretation.run_point == "RUN" and interpretation.run_equals == "ON"
    )
    if not supported:
        _transition(engine, request_id, "REJECTED", **common,
                    stop_reason="Requested logic is outside the supported SAT-deviation DSL")
        return get_request(engine, request_id)
    _transition(engine, request_id, "DISCOVERING", **common)
    discovery = search_ontology(engine)
    _record_tool(trace, "search_ontology", {"properties": interpretation.property_queries,
                 "floors": interpretation.floor_queries}, discovery)
    properties, floors, warnings = _resolve_scope(discovery, interpretation)
    unresolved = [warning for warning in warnings if warning.startswith("Unresolved")]
    if unresolved or not properties or not floors:
        _transition(engine, request_id, "REJECTED", tool_trace=trace, warnings=warnings,
                    stop_reason="; ".join(unresolved) or "Scope resolved to no canonical targets")
        return get_request(engine, request_id)
    draft = RuleDraft(
        rule_key=f"ai-sat-deviation-{request_id[:8]}",
        display_name=f"AI-assisted SAT deviation — {', '.join(properties)}",
        severity=interpretation.severity or "Critical",
        scope=TargetScope(property_ids=properties, floor_ids=floors),
        logic=FaultLogic(threshold=interpretation.threshold, duration_seconds=interpretation.duration_seconds),
    )
    draft_json = draft.model_dump(mode="json")
    _transition(engine, request_id, "VALIDATING", structured_draft=draft_json, tool_trace=trace, warnings=warnings)
    errors = validate_references(engine, draft)
    validation = {"valid": not errors, "errors": errors}
    _record_tool(trace, "validate_rule_draft", draft_json, validation)
    if errors:
        _transition(engine, request_id, "REJECTED", validation_result=validation, tool_trace=trace,
                    stop_reason="; ".join(errors))
        return get_request(engine, request_id)
    _transition(engine, request_id, "PREVIEWING", validation_result=validation, tool_trace=trace)
    preview = preview_draft(engine, draft)
    _record_tool(trace, "resolve_rule_targets", {"scope": draft_json["scope"]},
                 {"matched_count": preview["matched_count"], "excluded_count": preview["excluded_count"]})
    _record_tool(trace, "preview_rule", draft_json, preview)
    if not preview["matched"]:
        _transition(engine, request_id, "REJECTED", target_preview=preview, tool_trace=trace,
                    stop_reason="Current canonical ontology resolved to zero eligible targets")
        return get_request(engine, request_id)
    _transition(engine, request_id, "READY_FOR_REVIEW", reviewed_draft=draft_json,
                target_preview=preview, tool_trace=trace, clarification_question=None)
    return get_request(engine, request_id)


def create_authoring_request(engine: Engine, prompt: str, client: ModelClient | None = None) -> dict[str, Any]:
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if client is None:
        from afdd.settings import get_settings
        settings = get_settings()
        provider, model = "openai", settings.openai_model
    else:
        provider, model = client.provider, client.model
    with engine.begin() as connection:
        request_id = str(connection.execute(text("""
            INSERT INTO ai_authoring_requests
                (original_prompt,state,state_trace,provider,model,prompt_version,schema_version)
            VALUES (:prompt,'RECEIVED',CAST(:trace AS jsonb),:provider,:model,:prompt_version,:schema_version)
            RETURNING id
        """), {"prompt": prompt.strip(), "trace": json.dumps([{"state": "RECEIVED", "at": datetime.now().astimezone().isoformat()}]),
                 "provider": provider, "model": model, "prompt_version": PROMPT_VERSION,
                 "schema_version": SCHEMA_VERSION}).scalar_one())
    if client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            _transition(engine, request_id, "FAILED", stop_reason="OPENAI_API_KEY is not configured")
            return get_request(engine, request_id)
        client = OpenAIResponsesClient(settings.openai_api_key, settings.openai_model)
    return _process(engine, request_id, client, prompt.strip())


def answer_clarification(engine: Engine, request_id: str, answer: str, client: ModelClient | None = None) -> dict[str, Any]:
    record = get_request(engine, request_id)
    if record["state"] != "NEEDS_CLARIFICATION":
        raise ValueError("request is not awaiting clarification")
    history = list(record["clarification_history"]) + [{"question": record["clarification_question"], "answer": answer}]
    _transition(engine, request_id, "RECEIVED", clarification_history=history, clarification_question=None)
    if client is None:
        from afdd.settings import get_settings
        settings = get_settings()
        if not settings.openai_api_key:
            _transition(engine, request_id, "FAILED", stop_reason="OPENAI_API_KEY is not configured")
            return get_request(engine, request_id)
        client = OpenAIResponsesClient(settings.openai_api_key, settings.openai_model)
    combined = f"{record['original_prompt']}\nClarification answer: {answer}"
    return _process(engine, request_id, client, combined)


def cancel_request(engine: Engine, request_id: str) -> dict[str, Any]:
    record = get_request(engine, request_id)
    if record["state"] in {"ACTIVATED", "REJECTED", "FAILED", "STOPPED"}:
        return record
    _transition(engine, request_id, "STOPPED", stop_reason="Cancelled by human")
    return get_request(engine, request_id)


def confirm_request(engine: Engine, request_id: str) -> dict[str, Any]:
    with engine.begin() as connection:
        row = connection.execute(text("""
            SELECT state,reviewed_draft,activation_result FROM ai_authoring_requests
            WHERE id=CAST(:id AS uuid) FOR UPDATE
        """), {"id": request_id}).mappings().first()
        if not row:
            raise LookupError("authoring request not found")
        if row["state"] == "ACTIVATED":
            return get_request(engine, request_id)
        if row["state"] != "READY_FOR_REVIEW":
            raise ValueError("only a reviewed request can be confirmed")
        confirmed_at = datetime.now().astimezone()
        connection.execute(text("""
            UPDATE ai_authoring_requests SET state='CONFIRMED',human_confirmed_at=:confirmed,
                state_trace=state_trace || CAST(:trace AS jsonb),updated_at=now()
            WHERE id=CAST(:id AS uuid)
        """), {"id": request_id, "confirmed": confirmed_at,
                 "trace": json.dumps([{"state": "CONFIRMED", "at": confirmed_at.isoformat()}])})
        draft_json = row["reviewed_draft"]
    try:
        version = create_rule(engine, RuleDraft.model_validate(draft_json))
        rule = activate_rule(engine, version["rule_id"], version["version"])
    except (LookupError, SQLAlchemyError, ValidationError, ValueError) as exc:
        _transition(engine, request_id, "FAILED", stop_reason=f"Activation failed after confirmation: {exc}")
        return get_request(engine, request_id)
    _transition(engine, request_id, "ACTIVATED", activation_result={"rule": rule, "version": version})
    return get_request(engine, request_id)
