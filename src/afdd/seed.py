"""Idempotently import the canonical inventory from the supplied source registers."""

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text

from afdd.settings import get_settings

SPACE_BRICK_CLASSES = {
    "Building": "brick:Building",
    "Floor": "brick:Floor",
    "HVAC Zone": "brick:HVAC_Zone",
    "Room": "brick:Room",
}
EQUIPMENT_BRICK_CLASSES = {
    "AHU": "brick:Air_Handler_Unit",
    "IAQ Sensor": "brick:IAQ_Sensor",
    "Electricity Meter": "brick:Electric_Meter",
}
POINT_BRICK_CLASSES = {
    "RUN": "brick:On_Off_Status",
    "ALARM": "brick:Alarm",
    "SAT": "brick:Supply_Air_Temperature_Sensor",
    "RAT": "brick:Return_Air_Temperature_Sensor",
    "SAT_SP": "brick:Supply_Air_Temperature_Setpoint",
    "ROOM_TEMP": "brick:Air_Temperature_Sensor",
    "RH": "brick:Relative_Humidity_Sensor",
    "CO2": "brick:CO2_Sensor",
    "POWER_KW": "brick:Electrical_Power_Sensor",
    "ENERGY_KWH": "brick:Electrical_Energy_Sensor",
}


@dataclass(frozen=True)
class SeedSummary:
    spaces: int
    equipment: int
    points: int
    relationships: int


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def load_source(source_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    spaces = read_csv(source_dir / "spaces.csv")
    equipment = read_csv(source_dir / "equipment.csv")
    points = read_csv(source_dir / "datapoint-reference.csv")
    return spaces, equipment, points


def context_for_space(space_id: str, spaces_by_id: dict[str, dict[str, str]]) -> dict[str, str]:
    """Derive context only by following the explicit parent_space_id register."""

    context: dict[str, str] = {}
    seen: set[str] = set()
    current_id: str | None = space_id
    while current_id:
        if current_id in seen:
            raise ValueError(f"Cycle found in spaces.csv at {space_id}")
        seen.add(current_id)
        current = spaces_by_id.get(current_id)
        if current is None:
            raise ValueError(f"Unknown space reference {current_id} while resolving {space_id}")
        if current["space_type"] == "Building":
            context["building_source_id"] = current_id
        if current["space_type"] == "Floor":
            context["floor_source_id"] = current_id
        current_id = current["parent_space_id"] or None
    return context


def validate_source(
    spaces: list[dict[str, str]], equipment: list[dict[str, str]], points: list[dict[str, str]]
) -> None:
    spaces_by_id = {row["space_id"]: row for row in spaces}
    equipment_by_id = {row["equipment_id"]: row for row in equipment}
    if len(spaces_by_id) != len(spaces) or len(equipment_by_id) != len(equipment):
        raise ValueError("Source register contains duplicate space_id or equipment_id")
    if len({row["source_point_id"] for row in points}) != len(points):
        raise ValueError("Source register contains duplicate source_point_id")
    for row in spaces:
        parent_id = row["parent_space_id"]
        if parent_id and parent_id not in spaces_by_id:
            raise ValueError(f"Space {row['space_id']} has unknown parent {parent_id}")
        context_for_space(row["space_id"], spaces_by_id)
    for row in equipment:
        for field in ("property_id", "installed_space_id", "served_space_id", "measurement_scope_id"):
            reference = row[field]
            if reference and reference not in spaces_by_id:
                raise ValueError(f"Equipment {row['equipment_id']} has unknown {field} {reference}")
        if row["served_space_id"] and row["equipment_type"] != "AHU":
            raise ValueError("Only supplied AHUs may carry a served_space_id")
    for row in points:
        if row["equipment_id"] not in equipment_by_id:
            raise ValueError(f"Point {row['source_point_id']} has unknown equipment")


def _upsert_entity(
    connection: Any,
    source_id: str,
    entity_kind: str,
    brick_class: str,
    name: str,
    metadata: dict[str, Any],
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ontology_entities (source_id, entity_kind, brick_class, name, metadata)
            VALUES (:source_id, :entity_kind, :brick_class, :name, CAST(:metadata AS jsonb))
            ON CONFLICT (source_id) DO UPDATE SET
                entity_kind = EXCLUDED.entity_kind,
                brick_class = EXCLUDED.brick_class,
                name = EXCLUDED.name,
                metadata = EXCLUDED.metadata
            """
        ),
        {
            "source_id": source_id,
            "entity_kind": entity_kind,
            "brick_class": brick_class,
            "name": name,
            "metadata": json.dumps(metadata),
        },
    )


def _entity_ids(connection: Any) -> dict[str, str]:
    return {row.source_id: str(row.id) for row in connection.execute(text("SELECT source_id, id FROM ontology_entities"))}


def _add_edge(connection: Any, entity_ids: dict[str, str], subject: str, predicate: str, object_: str) -> None:
    if subject not in entity_ids or object_ not in entity_ids:
        raise ValueError(f"Cannot create {predicate}: {subject} -> {object_}; referenced entity is absent")
    connection.execute(
        text(
            """
            INSERT INTO ontology_relationships (subject_id, predicate, object_id)
            VALUES (CAST(:subject_id AS uuid), :predicate, CAST(:object_id AS uuid))
            ON CONFLICT DO NOTHING
            """
        ),
        {"subject_id": entity_ids[subject], "predicate": predicate, "object_id": entity_ids[object_]},
    )


def reset_inventory(engine: Engine) -> None:
    """Clear canonical inventory and all FK-dependent local data; intended for local development only."""

    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE ontology_entities CASCADE"))


def seed_inventory(engine: Engine, source_dir: Path) -> SeedSummary:
    spaces, equipment, points = load_source(source_dir)
    validate_source(spaces, equipment, points)
    spaces_by_id = {row["space_id"]: row for row in spaces}
    equipment_by_id = {row["equipment_id"]: row for row in equipment}

    with engine.begin() as connection:
        for row in spaces:
            context = context_for_space(row["space_id"], spaces_by_id)
            _upsert_entity(
                connection,
                row["space_id"],
                "space",
                SPACE_BRICK_CLASSES[row["space_type"]],
                row["name"],
                {
                    "space_type": row["space_type"],
                    "usage_type": row["usage_type"] or None,
                    "property_type": row["property_type"] or None,
                    "context": context,
                },
            )

        for row in equipment:
            context_space = row["served_space_id"] or row["measurement_scope_id"] or row["installed_space_id"]
            context = context_for_space(context_space, spaces_by_id) if context_space else {}
            context["building_source_id"] = row["property_id"]
            _upsert_entity(
                connection,
                row["equipment_id"],
                "equipment",
                EQUIPMENT_BRICK_CLASSES[row["equipment_type"]],
                row["name"],
                {"equipment_type": row["equipment_type"], "context": context},
            )

        for row in points:
            _upsert_entity(
                connection,
                row["source_point_id"],
                "point",
                POINT_BRICK_CLASSES.get(row["source_name"], "brick:Point"),
                row["description"],
                {
                    "measurement_type": row["source_name"],
                    "description": row["description"],
                    "engineering_unit": row["unit"] or None,
                },
            )

        entity_ids = _entity_ids(connection)
        for row in spaces:
            connection.execute(
                text(
                    """
                    INSERT INTO spaces (entity_id, space_type, usage_type, property_type)
                    VALUES (CAST(:entity_id AS uuid), :space_type, :usage_type, :property_type)
                    ON CONFLICT (entity_id) DO UPDATE SET
                        space_type = EXCLUDED.space_type,
                        usage_type = EXCLUDED.usage_type,
                        property_type = EXCLUDED.property_type
                    """
                ),
                {
                    "entity_id": entity_ids[row["space_id"]],
                    "space_type": row["space_type"],
                    "usage_type": row["usage_type"] or None,
                    "property_type": row["property_type"] or None,
                },
            )
        for row in equipment:
            connection.execute(
                text(
                    """
                    INSERT INTO equipment (entity_id, equipment_type)
                    VALUES (CAST(:entity_id AS uuid), :equipment_type)
                    ON CONFLICT (entity_id) DO UPDATE SET equipment_type = EXCLUDED.equipment_type
                    """
                ),
                {"entity_id": entity_ids[row["equipment_id"]], "equipment_type": row["equipment_type"]},
            )
        for row in points:
            connection.execute(
                text(
                    """
                    INSERT INTO telemetry_points (
                        entity_id, owner_equipment_id, source_name, value_type, unit, expected_interval_seconds
                    ) VALUES (
                        CAST(:entity_id AS uuid), CAST(:owner_equipment_id AS uuid), :source_name,
                        :value_type, :unit, :expected_interval_seconds
                    ) ON CONFLICT (entity_id) DO UPDATE SET
                        owner_equipment_id = EXCLUDED.owner_equipment_id,
                        source_name = EXCLUDED.source_name,
                        value_type = EXCLUDED.value_type,
                        unit = EXCLUDED.unit,
                        expected_interval_seconds = EXCLUDED.expected_interval_seconds
                    """
                ),
                {
                    "entity_id": entity_ids[row["source_point_id"]],
                    "owner_equipment_id": entity_ids[row["equipment_id"]],
                    "source_name": row["source_name"],
                    "value_type": row["value_type"],
                    "unit": row["unit"] or None,
                    "expected_interval_seconds": int(row["expected_interval_seconds"]),
                },
            )

        for row in spaces:
            if row["parent_space_id"]:
                _add_edge(connection, entity_ids, row["parent_space_id"], "hasPart", row["space_id"])
                _add_edge(connection, entity_ids, row["space_id"], "isPartOf", row["parent_space_id"])
        for row in equipment:
            _add_edge(connection, entity_ids, row["property_id"], "hasPart", row["equipment_id"])
            _add_edge(connection, entity_ids, row["equipment_id"], "isPartOf", row["property_id"])
            if row["installed_space_id"]:
                _add_edge(connection, entity_ids, row["equipment_id"], "hasLocation", row["installed_space_id"])
                _add_edge(connection, entity_ids, row["installed_space_id"], "isLocationOf", row["equipment_id"])
            if row["served_space_id"]:
                _add_edge(connection, entity_ids, row["equipment_id"], "feeds", row["served_space_id"])
            if row["measurement_scope_id"]:
                _add_edge(connection, entity_ids, row["equipment_id"], "meters", row["measurement_scope_id"])
        for row in points:
            _add_edge(connection, entity_ids, row["equipment_id"], "hasPoint", row["source_point_id"])

        relationship_count = connection.execute(text("SELECT count(*) FROM ontology_relationships")).scalar_one()
    return SeedSummary(len(spaces), len(equipment), len(points), relationship_count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path(get_settings().seed_source_dir))
    parser.add_argument("--reset", action="store_true", help="clear inventory and dependent local data first")
    args = parser.parse_args()
    engine = create_engine(get_settings().database_url)
    if args.reset:
        reset_inventory(engine)
    summary = seed_inventory(engine, args.source_dir)
    print(json.dumps(asdict(summary), sort_keys=True))


if __name__ == "__main__":
    main()

