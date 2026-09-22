"""Read-only query helpers for the canonical relational ontology."""

from typing import Any

from sqlalchemy import Engine, text


def _record(row: Any) -> dict[str, Any]:
    result = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    for key, value in result.items():
        if hasattr(value, "hex"):
            result[key] = str(value)
    return result


def list_properties(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT e.source_id, e.name AS display_name, e.brick_class, s.property_type, s.usage_type
                FROM ontology_entities e
                JOIN spaces s ON s.entity_id = e.id
                WHERE s.space_type = 'Building'
                ORDER BY e.source_id
                """
            )
        )
        return [_record(row) for row in rows]


def entity_by_source_id(engine: Engine, source_id: str) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT e.source_id, e.entity_kind, e.brick_class, e.name AS display_name, e.metadata,
                       s.space_type, s.usage_type, s.property_type, eq.equipment_type,
                       tp.source_name AS measurement_type, tp.value_type, tp.unit, tp.expected_interval_seconds
                FROM ontology_entities e
                LEFT JOIN spaces s ON s.entity_id = e.id
                LEFT JOIN equipment eq ON eq.entity_id = e.id
                LEFT JOIN telemetry_points tp ON tp.entity_id = e.id
                WHERE e.source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).first()
        return _record(row) if row else None


def relationships_for_entity(engine: Engine, source_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT 'outgoing' AS direction, r.predicate, target.source_id AS related_source_id,
                       target.name AS related_display_name, target.entity_kind AS related_entity_kind
                FROM ontology_entities entity
                JOIN ontology_relationships r ON r.subject_id = entity.id
                JOIN ontology_entities target ON target.id = r.object_id
                WHERE entity.source_id = :source_id
                UNION ALL
                SELECT 'incoming' AS direction, r.predicate, origin.source_id AS related_source_id,
                       origin.name AS related_display_name, origin.entity_kind AS related_entity_kind
                FROM ontology_entities entity
                JOIN ontology_relationships r ON r.object_id = entity.id
                JOIN ontology_entities origin ON origin.id = r.subject_id
                WHERE entity.source_id = :source_id
                ORDER BY direction, predicate, related_source_id
                """
            ),
            {"source_id": source_id},
        )
        return [_record(row) for row in rows]


def equipment_datapoints(engine: Engine, source_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT point.source_id, point.name AS display_name, point.brick_class,
                       tp.source_name AS measurement_type, tp.value_type, tp.unit, tp.expected_interval_seconds
                FROM ontology_entities equipment_entity
                JOIN ontology_relationships r
                    ON r.subject_id = equipment_entity.id AND r.predicate = 'hasPoint'
                JOIN ontology_entities point ON point.id = r.object_id
                JOIN telemetry_points tp ON tp.entity_id = point.id
                WHERE equipment_entity.source_id = :source_id
                ORDER BY tp.source_name
                """
            ),
            {"source_id": source_id},
        )
        return [_record(row) for row in rows]


def equipment_topology(engine: Engine, source_id: str) -> dict[str, Any] | None:
    entity = entity_by_source_id(engine, source_id)
    if entity is None or entity["entity_kind"] != "equipment":
        return None
    with engine.connect() as connection:
        installation = connection.execute(
            text(
                """
                SELECT target.source_id, target.name AS display_name
                FROM ontology_entities source
                JOIN ontology_relationships r ON r.subject_id = source.id AND r.predicate = 'hasLocation'
                JOIN ontology_entities target ON target.id = r.object_id
                WHERE source.source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().first()
        served_zone = connection.execute(
            text(
                """
                SELECT target.source_id, target.name AS display_name
                FROM ontology_entities source
                JOIN ontology_relationships r ON r.subject_id = source.id AND r.predicate = 'feeds'
                JOIN ontology_entities target ON target.id = r.object_id
                WHERE source.source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().first()
        rooms: list[dict[str, Any]] = []
        if served_zone:
            room_rows = connection.execute(
                text(
                    """
                    SELECT room.source_id, room.name AS display_name
                    FROM ontology_entities zone
                    JOIN ontology_relationships r ON r.subject_id = zone.id AND r.predicate = 'hasPart'
                    JOIN ontology_entities room ON room.id = r.object_id
                    JOIN spaces room_space ON room_space.entity_id = room.id
                    WHERE zone.source_id = :zone_source_id AND room_space.space_type = 'Room'
                    ORDER BY room.source_id
                    """
                ),
                {"zone_source_id": served_zone["source_id"]},
            )
            rooms = [_record(row) for row in room_rows]
    return {
        "equipment": entity,
        "installation_location": _record(installation) if installation else None,
        "served_zone": _record(served_zone) if served_zone else None,
        "occupied_rooms": rooms,
        "datapoints": equipment_datapoints(engine, source_id),
    }


def inventory_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "spaces": connection.execute(text("SELECT count(*) FROM spaces")).scalar_one(),
            "equipment": connection.execute(text("SELECT count(*) FROM equipment")).scalar_one(),
            "points": connection.execute(text("SELECT count(*) FROM telemetry_points")).scalar_one(),
            "relationships": connection.execute(text("SELECT count(*) FROM ontology_relationships")).scalar_one(),
            "canonical_entities": connection.execute(text("SELECT count(*) FROM ontology_entities")).scalar_one(),
        }
