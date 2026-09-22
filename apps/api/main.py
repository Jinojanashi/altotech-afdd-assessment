from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine

from afdd.ontology import (
    entity_by_source_id,
    equipment_datapoints,
    equipment_topology,
    list_properties,
    relationships_for_entity,
)
from afdd.settings import get_settings

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
