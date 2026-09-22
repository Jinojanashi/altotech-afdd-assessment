"""Read-only projections used by the operations dashboard.

These helpers intentionally traverse canonical ontology edges rather than
deriving topology from source-id naming conventions.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from afdd.telemetry import latest_for_equipment, telemetry_status


def _value(row: Any) -> dict[str, Any]:
    result = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    for key, item in result.items():
        if isinstance(item, datetime) or hasattr(item, "hex"):
            result[key] = str(item)
    return result


def operations_status(engine: Engine) -> dict[str, Any]:
    """Return transparent ingest/evaluation health details for the UI."""
    with engine.connect() as connection:
        processing = connection.execute(text("""
            SELECT max(received_at) AS last_ingestion_at FROM ingestion_attempts
        """)).mappings().one()
        evaluation = connection.execute(text("""
            SELECT max(updated_at) AS last_evaluation_at, count(*) AS evaluation_states
            FROM afdd_evaluation_states
        """)).mappings().one()
    return {
        "api_status": "ok",
        "ingestion": {**telemetry_status(engine), **_value(processing)},
        "evaluation": _value(evaluation),
    }


def portfolio(engine: Engine) -> list[dict[str, Any]]:
    """Project buildings, floors, zones, AHUs, and issue counts for navigation."""
    with engine.connect() as connection:
        buildings = connection.execute(text("""
            SELECT e.id, e.source_id, e.name AS display_name
            FROM ontology_entities e JOIN spaces s ON s.entity_id=e.id
            WHERE s.space_type='Building' ORDER BY e.source_id
        """)).mappings().all()
        result: list[dict[str, Any]] = []
        for building in buildings:
            floors = connection.execute(text("""
                SELECT floor.id, floor.source_id, floor.name AS display_name
                FROM ontology_relationships r
                JOIN ontology_entities floor ON floor.id=r.subject_id
                JOIN spaces fs ON fs.entity_id=floor.id
                WHERE r.predicate='isPartOf' AND r.object_id=:building_id
                  AND fs.space_type='Floor'
                ORDER BY floor.source_id
            """), {"building_id": building.id}).mappings().all()
            floor_items: list[dict[str, Any]] = []
            for floor in floors:
                zones = connection.execute(text("""
                    SELECT zone.id, zone.source_id, zone.name AS display_name
                    FROM ontology_relationships r
                    JOIN ontology_entities zone ON zone.id=r.subject_id
                    JOIN spaces zs ON zs.entity_id=zone.id
                    WHERE r.predicate='isPartOf' AND r.object_id=:floor_id
                      AND zs.space_type='HVAC Zone'
                    ORDER BY zone.source_id
                """), {"floor_id": floor.id}).mappings().all()
                zone_items = []
                for zone in zones:
                    rooms = connection.execute(text("""
                        SELECT room.source_id, room.name AS display_name
                        FROM ontology_relationships r JOIN ontology_entities room ON room.id=r.object_id
                        JOIN spaces rs ON rs.entity_id=room.id
                        WHERE r.subject_id=:zone_id AND r.predicate='hasPart' AND rs.space_type='Room'
                        ORDER BY room.source_id
                    """), {"zone_id": zone.id}).mappings().all()
                    ahus = connection.execute(text("""
                        SELECT ahu.source_id, ahu.name AS display_name
                        FROM ontology_relationships r JOIN ontology_entities ahu ON ahu.id=r.subject_id
                        JOIN equipment eq ON eq.entity_id=ahu.id
                        WHERE r.object_id=:zone_id AND r.predicate='feeds' AND eq.equipment_type='AHU'
                        ORDER BY ahu.source_id
                    """), {"zone_id": zone.id}).mappings().all()
                    zone_items.append({**_value(zone), "rooms": [_value(room) for room in rooms], "equipment": [_value(ahu) for ahu in ahus]})
                floor_items.append({**_value(floor), "zones": zone_items})
            issue_counts = connection.execute(text("""
                SELECT count(*) FILTER (WHERE issue.status='OPEN') AS active_issues,
                       count(*) FILTER (WHERE issue.status='CLOSED') AS recent_issues
                FROM afdd_issues issue
                JOIN ontology_relationships feeds ON feeds.subject_id=issue.equipment_id AND feeds.predicate='feeds'
                JOIN ontology_relationships zone_floor ON zone_floor.subject_id=feeds.object_id AND zone_floor.predicate='isPartOf'
                JOIN ontology_relationships floor_building ON floor_building.subject_id=zone_floor.object_id AND floor_building.predicate='isPartOf'
                WHERE floor_building.object_id=:building_id
            """), {"building_id": building.id}).mappings().one()
            ahu_count = sum(len(zone["equipment"]) for floor in floor_items for zone in floor["zones"])
            result.append({**_value(building), "ahu_count": ahu_count, **_value(issue_counts), "floors": floor_items})
    return result


def equipment_context(engine: Engine, source_id: str) -> dict[str, Any] | None:
    """Return room IAQ and floor meters related to an AHU's served topology.

    Floor meters are returned under a distinct floor-scope collection; they are
    never represented as AHU-owned datapoints.
    """
    with engine.connect() as connection:
        ahu = connection.execute(text("""
            SELECT e.id FROM ontology_entities e JOIN equipment eq ON eq.entity_id=e.id
            WHERE e.source_id=:source_id AND eq.equipment_type='AHU'
        """), {"source_id": source_id}).first()
        if not ahu:
            return None
        room_devices = connection.execute(text("""
            SELECT DISTINCT device.source_id, device.name AS display_name, room.source_id AS room_id,
                   room.name AS room_display_name
            FROM ontology_relationships feeds
            JOIN ontology_relationships room_edge ON room_edge.subject_id=feeds.object_id AND room_edge.predicate='hasPart'
            JOIN ontology_relationships device_scope ON device_scope.object_id=room_edge.object_id AND device_scope.predicate='meters'
            JOIN ontology_entities device ON device.id=device_scope.subject_id
            JOIN equipment eq ON eq.entity_id=device.id AND eq.equipment_type='IAQ Sensor'
            JOIN ontology_entities room ON room.id=room_edge.object_id
            WHERE feeds.subject_id=:ahu_id AND feeds.predicate='feeds'
            ORDER BY room.source_id, device.source_id
        """), {"ahu_id": ahu.id}).mappings().all()
        floor_meters = connection.execute(text("""
            SELECT DISTINCT meter.source_id, meter.name AS display_name, floor.source_id AS floor_id,
                   floor.name AS floor_display_name
            FROM ontology_relationships feeds
            JOIN ontology_relationships zone_floor ON zone_floor.subject_id=feeds.object_id AND zone_floor.predicate='isPartOf'
            JOIN ontology_relationships meter_scope ON meter_scope.object_id=zone_floor.object_id AND meter_scope.predicate='meters'
            JOIN ontology_entities meter ON meter.id=meter_scope.subject_id
            JOIN equipment eq ON eq.entity_id=meter.id AND eq.equipment_type='Electricity Meter'
            JOIN ontology_entities floor ON floor.id=zone_floor.object_id
            WHERE feeds.subject_id=:ahu_id AND feeds.predicate='feeds'
            ORDER BY meter.source_id
        """), {"ahu_id": ahu.id}).mappings().all()
    return {
        "room_iaq": [{**_value(row), "readings": latest_for_equipment(engine, row.source_id)} for row in room_devices],
        "floor_meters": [{**_value(row), "readings": latest_for_equipment(engine, row.source_id)} for row in floor_meters],
    }
