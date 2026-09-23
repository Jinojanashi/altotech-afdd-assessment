"""Safe AI-assisted rule authoring with server-authoritative bounded tools."""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
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

PROMPT_VERSION = "afdd-authoring-v2"
SCHEMA_VERSION = "interpretation-v2"
MAX_MODEL_ATTEMPTS = 2
ALLOWED_TRANSITIONS = {
    "RECEIVED": {"INTERPRETING", "FAILED", "STOPPED"},
    "INTERPRETING": {"DISCOVERING", "NEEDS_CLARIFICATION", "REJECTED", "FAILED", "STOPPED"},
    "DISCOVERING": {"VALIDATING", "NEEDS_CLARIFICATION", "REJECTED", "FAILED", "STOPPED"},
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
    property_queries: list[str] = Field(
        description="Property or building references only; never space-usage concepts."
    )
    floor_queries: list[str] = Field(description="Floor references only.")
    served_usage_queries: list[str] = Field(
        description="Usage concepts for spaces served by the equipment, such as office or guest."
    )
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
            "is supported. Missing threshold or duration requires clarification. Put only property or "
            "building references in property_queries, only floors in floor_queries, and served-space "
            "usage concepts in served_usage_queries. For example, 'office AHUs in Building A' means "
            "property_queries=['Building A'] and served_usage_queries=['office']. Do not return canonical "
            "ontology IDs; the server resolves all references authoritatively. Return the schema only."
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
                   space.usage_type, space.property_type, parent.source_id AS parent_id
            FROM ontology_entities entity JOIN spaces space ON space.entity_id=entity.id
            LEFT JOIN ontology_relationships rel
              ON rel.subject_id=entity.id AND rel.predicate='isPartOf'
            LEFT JOIN ontology_entities parent ON parent.id=rel.object_id
            WHERE space.space_type IN ('Building','Floor') ORDER BY entity.source_id
        """)).mappings()
        served_usage_rows = connection.execute(text("""
            SELECT DISTINCT zone_space.usage_type,
                   building_entity.source_id AS property_id,
                   building_space.usage_type AS property_usage_type
            FROM spaces zone_space
            JOIN ontology_entities zone_entity ON zone_entity.id=zone_space.entity_id
            JOIN ontology_relationships zone_floor
              ON zone_floor.subject_id=zone_entity.id AND zone_floor.predicate='isPartOf'
            JOIN ontology_relationships floor_building
              ON floor_building.subject_id=zone_floor.object_id AND floor_building.predicate='isPartOf'
            JOIN ontology_entities building_entity ON building_entity.id=floor_building.object_id
            JOIN spaces building_space ON building_space.entity_id=building_entity.id
            WHERE zone_space.space_type='HVAC Zone' AND zone_space.usage_type IS NOT NULL
            ORDER BY building_entity.source_id, zone_space.usage_type
        """)).mappings()
        return {
            "spaces": [dict(row) for row in rows],
            "served_usages": [dict(row) for row in served_usage_rows],
            "equipment_types": ["AHU"],
        }


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


@dataclass(frozen=True)
class ScopeResolution:
    property_ids: list[str]
    floor_ids: list[str]
    served_usages: list[str]
    warnings: list[str]
    normalization_events: list[dict[str, str]]
    unresolved_queries: list[str]
    ambiguous_queries: list[dict[str, Any]]


def _resolve_scope(
    discovery: dict[str, Any], interpretation: Interpretation
) -> ScopeResolution:
    spaces = discovery["spaces"]
    buildings = [item for item in spaces if item["space_type"] == "Building"]
    floors = [item for item in spaces if item["space_type"] == "Floor"]
    references = [
        *(("property", query) for query in interpretation.property_queries),
        *(("floor", query) for query in interpretation.floor_queries),
        *(("served_usage", query) for query in interpretation.served_usage_queries),
    ]

    def property_matches(query: str) -> set[str]:
        folded = query.casefold()
        return {
            item["source_id"]
            for item in buildings
            if folded in {item["source_id"].casefold(), item["display_name"].casefold()}
        }

    # Establish property context first so duplicate floor labels and usage aliases
    # are evaluated only against the selected canonical properties.
    resolved_properties = {
        next(iter(matches))
        for _, query in references
        if len(matches := property_matches(query)) == 1
    }

    def dimension_matches(query: str) -> dict[str, set[str]]:
        folded = query.casefold()
        matched_floors = {
            item["source_id"]
            for item in floors
            if folded in {item["source_id"].casefold(), item["display_name"].casefold()}
            and (not resolved_properties or item["parent_id"] in resolved_properties)
        }
        served_catalog = discovery["served_usages"]
        direct_usages = {
            item["usage_type"]
            for item in served_catalog
            if folded == item["usage_type"].casefold()
        }
        contextual_usages = {
            item["usage_type"]
            for item in served_catalog
            if item["property_usage_type"]
            and folded == item["property_usage_type"].casefold()
        }
        candidates = {
            "property": property_matches(query),
            "floor": matched_floors,
            "served_usage": direct_usages or contextual_usages,
        }
        return {dimension: values for dimension, values in candidates.items() if values}

    resolved_by_dimension: dict[str, list[str]] = {
        "property": [],
        "floor": [],
        "served_usage": [],
    }
    normalization_events: list[dict[str, str]] = []
    unresolved: list[str] = []
    ambiguous: list[dict[str, Any]] = []
    for source_dimension, query in references:
        matches = dimension_matches(query)
        if not matches:
            unresolved.append(query)
            continue
        if len(matches) != 1 or len(next(iter(matches.values()))) != 1:
            ambiguous.append({
                "query": query,
                "from": source_dimension,
                "matching_dimensions": sorted(matches),
            })
            continue
        target_dimension, values = next(iter(matches.items()))
        resolved_by_dimension[target_dimension].extend(values)
        if target_dimension != source_dimension:
            normalization_events.append({
                "event": "scope_reference_reclassified",
                "query": query,
                "from": source_dimension,
                "to": target_dimension,
            })

    resolved_properties = set(resolved_by_dimension["property"])
    resolved_floors = set(resolved_by_dimension["floor"])
    warnings: list[str] = []
    if resolved_properties and not resolved_floors and not interpretation.floor_queries:
        resolved_floors = {
            item["source_id"] for item in floors if item["parent_id"] in resolved_properties
        }
        warnings.append("No floors specified; review includes all canonical floors in the selected properties.")
    warnings.extend(
        f"scope_reference_reclassified: query={event['query']!r} "
        f"from={event['from']} to={event['to']}"
        for event in normalization_events
    )
    return ScopeResolution(
        property_ids=sorted(resolved_properties),
        floor_ids=sorted(resolved_floors),
        served_usages=sorted(set(resolved_by_dimension["served_usage"])),
        warnings=warnings,
        normalization_events=normalization_events,
        unresolved_queries=unresolved,
        ambiguous_queries=ambiguous,
    )


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
                 "floors": interpretation.floor_queries,
                 "served_usages": interpretation.served_usage_queries}, discovery)
    resolution = _resolve_scope(discovery, interpretation)
    _record_tool(trace, "normalize_scope_references", {
        "property_queries": interpretation.property_queries,
        "floor_queries": interpretation.floor_queries,
        "served_usage_queries": interpretation.served_usage_queries,
    }, {
        "normalization_events": resolution.normalization_events,
        "unresolved_queries": resolution.unresolved_queries,
        "ambiguous_queries": resolution.ambiguous_queries,
    })
    if resolution.ambiguous_queries:
        ambiguous_labels = ", ".join(
            f"{item['query']!r} ({', '.join(item['matching_dimensions'])})"
            for item in resolution.ambiguous_queries
        )
        _transition(
            engine,
            request_id,
            "NEEDS_CLARIFICATION",
            tool_trace=trace,
            warnings=resolution.warnings,
            clarification_question=(
                "Please clarify the intended scope dimension for: " + ambiguous_labels
            ),
        )
        return get_request(engine, request_id)
    if resolution.unresolved_queries:
        unresolved = [
            f"Unresolved ontology reference: {query}"
            for query in resolution.unresolved_queries
        ]
        _transition(engine, request_id, "REJECTED", tool_trace=trace,
                    warnings=resolution.warnings + unresolved,
                    stop_reason="; ".join(unresolved))
        return get_request(engine, request_id)
    if not resolution.property_ids:
        _transition(engine, request_id, "NEEDS_CLARIFICATION", tool_trace=trace,
                    warnings=resolution.warnings,
                    clarification_question="Please specify a building/property for the rule scope.")
        return get_request(engine, request_id)
    if not resolution.floor_ids:
        _transition(engine, request_id, "REJECTED", tool_trace=trace,
                    warnings=resolution.warnings,
                    stop_reason="Scope resolved to no canonical targets")
        return get_request(engine, request_id)
    scope_values: dict[str, Any] = {
        "property_ids": resolution.property_ids,
        "floor_ids": resolution.floor_ids,
    }
    if resolution.served_usages:
        scope_values["served_zone_usage_types"] = resolution.served_usages
    draft = RuleDraft(
        rule_key=f"ai-sat-deviation-{request_id[:8]}",
        display_name=f"AI-assisted SAT deviation — {', '.join(resolution.property_ids)}",
        severity=interpretation.severity or "Critical",
        scope=TargetScope(**scope_values),
        logic=FaultLogic(threshold=interpretation.threshold, duration_seconds=interpretation.duration_seconds),
    )
    draft_json = draft.model_dump(mode="json")
    _transition(engine, request_id, "VALIDATING", structured_draft=draft_json,
                tool_trace=trace, warnings=resolution.warnings)
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
