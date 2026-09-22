from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine

from afdd.evaluator import get_issue, list_issues
from afdd.ontology import (
    entity_by_source_id,
    equipment_datapoints,
    equipment_topology,
    list_properties,
    relationships_for_entity,
)
from afdd.rules import (
    RuleDraft,
    activate_rule,
    create_rule,
    create_rule_version,
    disable_rule,
    draft_for_version,
    get_rule,
    get_rule_version,
    list_rules,
    preview_draft,
    validate_references,
)
from afdd.settings import get_settings
from afdd.telemetry import (
    latest_for_equipment,
    point_history,
    recent_ingestion_events,
    telemetry_status,
)

app = FastAPI(title="AFDD API", version="0.1.0")


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


def ontology_engine():
    return create_engine(get_settings().database_url)


@app.get("/properties", tags=["ontology"])
def properties() -> list[dict]:
    return list_properties(ontology_engine())


@app.get("/entities/{source_id}", tags=["ontology"])
def inspect_entity(source_id: str) -> dict:
    entity = entity_by_source_id(ontology_engine(), source_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Canonical entity not found")
    return entity


@app.get("/entities/{source_id}/relationships", tags=["ontology"])
def inspect_relationships(source_id: str) -> list[dict]:
    if entity_by_source_id(ontology_engine(), source_id) is None:
        raise HTTPException(status_code=404, detail="Canonical entity not found")
    return relationships_for_entity(ontology_engine(), source_id)


@app.get("/equipment/{source_id}/datapoints", tags=["ontology"])
def inspect_equipment_datapoints(source_id: str) -> list[dict]:
    entity = entity_by_source_id(ontology_engine(), source_id)
    if entity is None or entity["entity_kind"] != "equipment":
        raise HTTPException(status_code=404, detail="Equipment not found")
    return equipment_datapoints(ontology_engine(), source_id)


@app.get("/equipment/{source_id}/topology", tags=["ontology"])
def inspect_equipment_topology(source_id: str) -> dict:
    topology = equipment_topology(ontology_engine(), source_id)
    if topology is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return topology


@app.get("/telemetry/equipment/{source_id}/latest", tags=["telemetry"])
def latest_readings(source_id: str) -> list[dict]:
    return latest_for_equipment(ontology_engine(), source_id)


@app.get("/telemetry/points/{source_id}/history", tags=["telemetry"])
def history(source_id: str, start: datetime, end: datetime) -> list[dict]:
    if start > end:
        raise HTTPException(status_code=422, detail="start must be before end")
    return point_history(ontology_engine(), source_id, start, end)


@app.get("/ingestion/status", tags=["operations"])
def ingestion_status() -> dict:
    return telemetry_status(ontology_engine())


@app.get("/ingestion/events", tags=["operations"])
def ingestion_events(limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    return recent_ingestion_events(ontology_engine(), limit)


@app.post("/rules/validate", tags=["rules"])
def validate_rule(draft: RuleDraft) -> dict:
    errors = validate_references(ontology_engine(), draft)
    return {"valid": not errors, "errors": errors}


@app.post("/rules/preview", tags=["rules"])
def preview_rule(draft: RuleDraft) -> dict:
    return preview_draft(ontology_engine(), draft)


@app.get("/rules", tags=["rules"])
def rules() -> list[dict]:
    return list_rules(ontology_engine())


@app.post("/rules", tags=["rules"], status_code=201)
def add_rule(draft: RuleDraft) -> dict:
    try:
        return create_rule(ontology_engine(), draft)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/rules/{rule_id}", tags=["rules"])
def inspect_rule(rule_id: str) -> dict:
    try:
        return get_rule(ontology_engine(), rule_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Rule not found") from exc


@app.post("/rules/{rule_id}/versions", tags=["rules"], status_code=201)
def add_rule_version(rule_id: str, draft: RuleDraft) -> dict:
    try:
        return create_rule_version(ontology_engine(), rule_id, draft)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/rules/{rule_id}/versions/{version}", tags=["rules"])
def inspect_rule_version(rule_id: str, version: int) -> dict:
    try:
        return get_rule_version(ontology_engine(), rule_id, version)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Rule version not found") from exc


@app.get("/rules/{rule_id}/versions/{version}/preview", tags=["rules"])
def preview_rule_version(rule_id: str, version: int) -> dict:
    try:
        _, draft = draft_for_version(ontology_engine(), rule_id, version)
        return preview_draft(ontology_engine(), draft)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Rule version not found") from exc


@app.post("/rules/{rule_id}/versions/{version}/activate", tags=["rules"])
def enable_rule_version(rule_id: str, version: int) -> dict:
    try:
        return activate_rule(ontology_engine(), rule_id, version)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/rules/{rule_id}/disable", tags=["rules"])
def turn_off_rule(rule_id: str) -> dict:
    try:
        return disable_rule(ontology_engine(), rule_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Rule not found") from exc


@app.get("/issues", tags=["issues"])
def issues(status: str | None = Query(default=None, pattern="^(OPEN|CLOSED)$")) -> list[dict]:
    return list_issues(ontology_engine(), status)


@app.get("/issues/{issue_id}", tags=["issues"])
def issue_detail(issue_id: str) -> dict:
    try:
        issue = get_issue(ontology_engine(), issue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Issue not found") from exc
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue
