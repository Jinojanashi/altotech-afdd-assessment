import csv
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from afdd.ontology import (
    equipment_datapoints,
    equipment_topology,
    inventory_counts,
    list_properties,
    relationships_for_entity,
)
from afdd.seed import reset_inventory, seed_inventory
from apps.api.main import app

SOURCE_DIR = Path(os.environ.get("SEED_SOURCE_DIR", "data/candidate-starter-pack/building-and-equipment"))


def source_count(filename: str) -> int:
    with (SOURCE_DIR / filename).open(newline="", encoding="utf-8") as file:
        return sum(1 for _ in csv.DictReader(file))


@pytest.fixture(scope="session")
def engine():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for ontology integration tests")
    engine = create_engine(database_url)
    reset_inventory(engine)
    seed_inventory(engine, SOURCE_DIR)
    return engine


def test_inventory_counts_match_source_registers(engine) -> None:
    counts = inventory_counts(engine)
    assert counts["spaces"] == source_count("spaces.csv") == 93
    assert counts["equipment"] == source_count("equipment.csv") == 84
    assert counts["points"] == source_count("datapoint-reference.csv") == 288
    assert counts["canonical_entities"] == 93 + 84 + 288
    assert len(list_properties(engine)) == 3


def test_no_duplicate_canonical_source_ids(engine) -> None:
    with engine.connect() as connection:
        duplicate_count = connection.execute(
            text(
                """
                SELECT count(*) FROM (
                    SELECT source_id FROM ontology_entities GROUP BY source_id HAVING count(*) > 1
                ) duplicates
                """
            )
        ).scalar_one()
    assert duplicate_count == 0


def test_ahu_topology_keeps_location_and_served_zone_separate(engine) -> None:
    topology = equipment_topology(engine, "ahu-a-f02-east")
    assert topology is not None
    assert topology["installation_location"]["source_id"] == "building-a-plant-room"
    assert topology["served_zone"]["source_id"] == "building-a-f02-east"
    assert topology["installation_location"]["source_id"] != topology["served_zone"]["source_id"]
    assert [room["source_id"] for room in topology["occupied_rooms"]] == [
        "building-a-f02-east-r01",
        "building-a-f02-east-r02",
    ]


def test_ahu_points_are_owned_through_explicit_edges(engine) -> None:
    points = equipment_datapoints(engine, "ahu-a-f02-east")
    assert {point["measurement_type"] for point in points} >= {"RUN", "SAT", "SAT_SP"}
    relationships = relationships_for_entity(engine, "ahu-a-f02-east")
    has_point = {edge["related_source_id"] for edge in relationships if edge["predicate"] == "hasPoint"}
    assert {"ahu-a-f02-east-run", "ahu-a-f02-east-sat", "ahu-a-f02-east-sat-sp"} <= has_point


def test_floor_meter_measurement_scope_is_a_floor_not_an_ahu(engine) -> None:
    relationships = relationships_for_entity(engine, "meter-a-f02")
    meter_scopes = [
        edge["related_source_id"]
        for edge in relationships
        if edge["direction"] == "outgoing" and edge["predicate"] == "meters"
    ]
    assert meter_scopes == ["building-a-f02"]
    assert not any(edge["predicate"] == "feeds" for edge in relationships)


def test_seed_is_idempotent(engine) -> None:
    before = inventory_counts(engine)
    second_summary = seed_inventory(engine, SOURCE_DIR)
    after = inventory_counts(engine)
    assert after == before
    assert second_summary.spaces == before["spaces"]
    assert second_summary.equipment == before["equipment"]
    assert second_summary.points == before["points"]


def test_minimal_api_exposes_concrete_ahu_topology(engine) -> None:
    response = TestClient(app).get("/equipment/ahu-a-f02-east/topology")
    assert response.status_code == 200
    body = response.json()
    assert body["installation_location"]["source_id"] == "building-a-plant-room"
    assert body["served_zone"]["source_id"] == "building-a-f02-east"
    assert [room["source_id"] for room in body["occupied_rooms"]] == [
        "building-a-f02-east-r01",
        "building-a-f02-east-r02",
    ]
    assert {point["measurement_type"] for point in body["datapoints"]} >= {"RUN", "SAT", "SAT_SP"}
