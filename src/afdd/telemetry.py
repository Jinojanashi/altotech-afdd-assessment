"""Transactional validation, canonical resolution, persistence, and read queries."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import Engine, text

from afdd.events import TelemetryEvent, event_id_for


@dataclass(frozen=True)
class IngestionResult:
    status: str
    event_id: str | None
    observations: int = 0
    reason: str | None = None


def process_payload(engine: Engine, raw: bytes | str | dict[str, Any]) -> IngestionResult:
    try:
        payload = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
        event = TelemetryEvent.model_validate(payload)
        UUID(str(event.event_id))
    except (ValueError, TypeError, ValidationError) as exc:
        raw_text = raw.decode(errors="replace") if isinstance(raw, bytes) else json.dumps(raw, default=str) if isinstance(raw, dict) else str(raw)
        quarantine_id = event_id_for("quarantine", raw_text)
        reason = f"invalid_event: {exc}"
        now = datetime.now(UTC)
        with engine.begin() as connection:
            existing = connection.execute(
                text("SELECT event_id FROM ingestion_events WHERE event_id=:event"), {"event": quarantine_id}
            ).first()
            disposition = "DUPLICATE" if existing else "REJECTED"
            if not existing:
                connection.execute(text("""
                    INSERT INTO ingestion_events
                        (event_id,schema_version,source_system,source_record_id,equipment_source_id,observed_at,
                         received_at,source_file,payload,processing_status,reason)
                    VALUES (:event,0,'quarantine',:record,:equipment,:now,:now,'broker',CAST(:payload AS jsonb),'REJECTED',:reason)
                """), {"event": quarantine_id, "record": f"invalid:{quarantine_id}", "equipment": "<invalid>",
                        "now": now, "payload": json.dumps({"raw": raw_text}), "reason": reason})
            connection.execute(text("""
                INSERT INTO ingestion_attempts
                    (attempt_id,event_id,source_system,source_record_id,received_at,disposition,canonical_event_id,details)
                VALUES (:attempt,:event,'quarantine',:record,:now,:disposition,:event,CAST(:details AS jsonb))
            """), {"attempt": uuid4(), "event": quarantine_id, "record": f"invalid:{quarantine_id}",
                    "now": now, "disposition": disposition, "details": json.dumps({"reason": reason})})
        return IngestionResult(disposition, str(quarantine_id), reason=reason)

    raw_json = json.dumps(payload, default=str)
    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT event_id FROM ingestion_events WHERE event_id=:event_id OR (source_system=:source AND source_record_id=:record_id)"),
            {"event_id": event.event_id, "source": event.source, "record_id": event.source_record_id},
        ).first()
        if existing:
            connection.execute(text("""
                INSERT INTO ingestion_attempts
                    (attempt_id,event_id,source_system,source_record_id,received_at,disposition,canonical_event_id,details)
                VALUES (:attempt,:event,:source,:record,:received,'DUPLICATE',:canonical,'{}')
            """), {"attempt": uuid4(), "event": event.event_id, "source": event.source,
                    "record": event.source_record_id, "received": event.received_at, "canonical": existing.event_id})
            return IngestionResult("DUPLICATE", str(existing.event_id))

        equipment = connection.execute(text("""
            SELECT entity.id, eq.equipment_type FROM ontology_entities entity
            JOIN equipment eq ON eq.entity_id=entity.id WHERE entity.source_id=:source_id
        """), {"source_id": event.equipment_id}).first()
        reason = None
        points: dict[str, Any] = {}
        if equipment is None:
            reason = "unknown_equipment"
        elif equipment.equipment_type != event.equipment_type:
            reason = "equipment_type_mismatch"
        else:
            rows = connection.execute(text("""
                SELECT point.id, tp.source_name, tp.value_type, tp.unit
                FROM telemetry_points tp JOIN ontology_entities point ON point.id=tp.entity_id
                WHERE tp.owner_equipment_id=:equipment_id
            """), {"equipment_id": equipment.id})
            points = {row.source_name: row for row in rows}
            for measurement in event.measurements:
                point = points.get(measurement.measurement)
                if point is None:
                    reason = f"unknown_measurement:{measurement.measurement}"
                    break
                if point.value_type == "number" and (isinstance(measurement.value, bool) or not isinstance(measurement.value, (int, float))):
                    reason = f"invalid_value:{measurement.measurement}"
                    break
                if point.value_type == "enum" and not isinstance(measurement.value, str):
                    reason = f"invalid_value:{measurement.measurement}"
                    break

        status = "REJECTED" if reason else "ACCEPTED"
        connection.execute(text("""
            INSERT INTO ingestion_events
                (event_id,schema_version,source_system,source_record_id,equipment_source_id,observed_at,
                 received_at,source_file,payload,processing_status,reason)
            VALUES (:event,:version,:source,:record,:equipment,:observed,:received,:file,CAST(:payload AS jsonb),:status,:reason)
        """), {"event": event.event_id, "version": event.schema_version, "source": event.source,
                "record": event.source_record_id, "equipment": event.equipment_id, "observed": event.observed_at,
                "received": event.received_at, "file": event.source_file, "payload": raw_json,
                "status": status, "reason": reason})
        connection.execute(text("""
            INSERT INTO ingestion_attempts
                (attempt_id,event_id,source_system,source_record_id,received_at,disposition,canonical_event_id,details)
            VALUES (:attempt,:event,:source,:record,:received,:status,:event,CAST(:details AS jsonb))
        """), {"attempt": uuid4(), "event": event.event_id, "source": event.source,
                "record": event.source_record_id, "received": event.received_at, "status": status,
                "details": json.dumps({"reason": reason} if reason else {})})
        if reason:
            return IngestionResult(status, str(event.event_id), reason=reason)

        count = 0
        for measurement in event.measurements:
            point = points[measurement.measurement]
            numeric = measurement.value if point.value_type == "number" else None
            text_value = measurement.value if point.value_type != "number" else None
            connection.execute(text("""
                INSERT INTO telemetry_readings
                    (observed_at,point_id,event_id,received_at,numeric_value,text_value,quality,equipment_id,unit)
                VALUES (:observed,:point,:event,:received,:numeric,:text,'GOOD',:equipment,:unit)
                ON CONFLICT DO NOTHING
            """), {"observed": event.observed_at, "point": point.id, "event": event.event_id,
                    "received": event.received_at, "numeric": numeric, "text": text_value,
                    "equipment": equipment.id, "unit": point.unit})
            connection.execute(text("""
                INSERT INTO current_point_values
                    (point_id,observed_at,received_at,event_id,numeric_value,text_value,quality,equipment_id,unit)
                VALUES (:point,:observed,:received,:event,:numeric,:text,'GOOD',:equipment,:unit)
                ON CONFLICT (point_id) DO UPDATE SET observed_at=EXCLUDED.observed_at,
                    received_at=EXCLUDED.received_at,event_id=EXCLUDED.event_id,
                    numeric_value=EXCLUDED.numeric_value,text_value=EXCLUDED.text_value,
                    quality=EXCLUDED.quality,equipment_id=EXCLUDED.equipment_id,unit=EXCLUDED.unit
                WHERE EXCLUDED.observed_at > current_point_values.observed_at OR
                    (EXCLUDED.observed_at = current_point_values.observed_at AND
                     EXCLUDED.event_id::text > current_point_values.event_id::text)
            """), {"point": point.id, "observed": event.observed_at, "received": event.received_at,
                    "event": event.event_id, "numeric": numeric, "text": text_value,
                    "equipment": equipment.id, "unit": point.unit})
            count += 1
        return IngestionResult(status, str(event.event_id), count)


def telemetry_status(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT count(*) FILTER (WHERE disposition='ACCEPTED') accepted,
                   count(*) FILTER (WHERE disposition='DUPLICATE') duplicates,
                   count(*) FILTER (WHERE disposition='REJECTED') rejected
            FROM ingestion_attempts
        """)).mappings().one()
        return {**dict(row), "observations": connection.execute(text("SELECT count(*) FROM telemetry_readings")).scalar_one()}


def _reading(row: Any) -> dict[str, Any]:
    item = dict(row._mapping)
    numeric = item.pop("numeric_value")
    text_value = item.pop("text_value")
    item["value"] = numeric if numeric is not None else text_value
    for key, value in item.items():
        if isinstance(value, (UUID, datetime)):
            item[key] = str(value)
    return item


def latest_for_equipment(engine: Engine, equipment_source_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT point.source_id AS point_id, tp.source_name AS measurement, current.numeric_value,
                   current.text_value, current.unit, current.observed_at, current.received_at,
                   current.quality, extract(epoch FROM (now()-current.observed_at))::bigint AS age_seconds
            FROM ontology_entities equipment_entity
            JOIN current_point_values current ON current.equipment_id=equipment_entity.id
            JOIN telemetry_points tp ON tp.entity_id=current.point_id
            JOIN ontology_entities point ON point.id=current.point_id
            WHERE equipment_entity.source_id=:equipment ORDER BY tp.source_name
        """), {"equipment": equipment_source_id})
        return [_reading(row) for row in rows]


def point_history(engine: Engine, point_source_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT point.source_id AS point_id, tp.source_name AS measurement, reading.numeric_value,
                   reading.text_value, reading.unit, reading.observed_at, reading.received_at, reading.quality,
                   reading.event_id
            FROM ontology_entities point JOIN telemetry_points tp ON tp.entity_id=point.id
            JOIN telemetry_readings reading ON reading.point_id=point.id
            WHERE point.source_id=:point AND reading.observed_at BETWEEN :start AND :end
            ORDER BY reading.observed_at, reading.event_id
        """), {"point": point_source_id, "start": start, "end": end})
        return [_reading(row) for row in rows]


def recent_ingestion_events(engine: Engine, limit: int = 50) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT attempt.disposition AS status, attempt.event_id, attempt.source_record_id,
                   event.equipment_source_id AS equipment_id, event.observed_at, attempt.received_at,
                   event.reason
            FROM ingestion_attempts attempt
            JOIN ingestion_events event ON event.event_id=attempt.canonical_event_id
            WHERE attempt.disposition IN ('DUPLICATE','REJECTED')
            ORDER BY attempt.received_at DESC LIMIT :limit
        """), {"limit": limit})
        return [{key: str(value) if isinstance(value, (UUID, datetime)) else value for key, value in row._mapping.items()} for row in rows]
