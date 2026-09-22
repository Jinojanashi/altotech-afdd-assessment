"""Versioned rule DSL, persistence, validation, and ontology-based target preview."""

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, text


class TargetScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_type: Literal["AHU"] = "AHU"
    property_type: str = "Office"
    property_ids: list[str] = Field(min_length=1)
    floor_ids: list[str] = Field(min_length=1)
    served_zone_usage_types: list[str] = Field(default_factory=lambda: ["Tenant Area"])
    occupied_room_usage_types: list[str] = Field(default_factory=lambda: ["Office Room"])
    required_points: list[Literal["RUN", "SAT", "SAT_SP"]] = Field(
        default_factory=lambda: ["RUN", "SAT", "SAT_SP"]
    )

    @model_validator(mode="after")
    def unique_and_complete(self) -> "TargetScope":
        for name in (
            "property_ids",
            "floor_ids",
            "served_zone_usage_types",
            "occupied_room_usage_types",
            "required_points",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} contains duplicates")
        if set(self.required_points) != {"RUN", "SAT", "SAT_SP"}:
            raise ValueError("SAT deviation requires exactly RUN, SAT, and SAT_SP")
        return self


class FaultLogic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["SAT_ABSOLUTE_DEVIATION"] = "SAT_ABSOLUTE_DEVIATION"
    operator: Literal[">"] = ">"
    threshold: float = Field(default=3.0, gt=0)
    duration_seconds: int = Field(default=900, gt=0)
    freshness_seconds: int = Field(default=120, gt=0)


class PropertyOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: str
    threshold: float | None = Field(default=None, gt=0)
    duration_seconds: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def has_value(self) -> "PropertyOverride":
        if self.threshold is None and self.duration_seconds is None:
            raise ValueError("override must set threshold or duration_seconds")
        return self


class RuleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_key: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    severity: Literal["Critical", "Warning", "Info"] = "Critical"
    scope: TargetScope
    logic: FaultLogic
    overrides: list[PropertyOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_overrides(self) -> "RuleDraft":
        properties = [override.property_id for override in self.overrides]
        if len(properties) != len(set(properties)):
            raise ValueError("only one override is allowed per property")
        return self


def default_sat_rule(*, with_override: bool = True) -> RuleDraft:
    """Assessment rule expressed only in property/floor scope, never AHU identifiers."""

    overrides = [PropertyOverride(property_id="building-b", threshold=2.0)] if with_override else []
    return RuleDraft(
        rule_key="ahu-sat-deviation",
        display_name="Sustained AHU supply-air temperature deviation",
        scope=TargetScope(
            property_ids=["building-a", "building-b"],
            floor_ids=[
                "building-a-f01",
                "building-a-f02",
                "building-a-f03",
                "building-a-f04",
                "building-b-f01",
                "building-b-f02",
                "building-b-f03",
                "building-b-f04",
            ],
        ),
        logic=FaultLogic(),
        overrides=overrides,
    )


def _json(value: BaseModel | dict[str, Any]) -> str:
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(raw, sort_keys=True)


def _serializable(row: Any) -> dict[str, Any]:
    result = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    return {
        key: str(value) if isinstance(value, (UUID, datetime)) else value
        for key, value in result.items()
    }


def validate_references(engine: Engine, draft: RuleDraft) -> list[str]:
    requested = set(draft.scope.property_ids + draft.scope.floor_ids)
    requested.update(override.property_id for override in draft.overrides)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT entity.source_id, space.space_type
                FROM ontology_entities entity
                JOIN spaces space ON space.entity_id=entity.id
                WHERE entity.source_id = ANY(CAST(:source_ids AS text[]))
                """
            ),
            {"source_ids": sorted(requested)},
        )
        found = {row.source_id: row.space_type for row in rows}
    errors = [f"unknown space: {source_id}" for source_id in sorted(requested - found.keys())]
    errors.extend(
        f"property scope is not a Building: {source_id}"
        for source_id in draft.scope.property_ids
        if found.get(source_id) not in (None, "Building")
    )
    errors.extend(
        f"floor scope is not a Floor: {source_id}"
        for source_id in draft.scope.floor_ids
        if found.get(source_id) not in (None, "Floor")
    )
    errors.extend(
        f"override scope is not a selected property: {override.property_id}"
        for override in draft.overrides
        if override.property_id not in draft.scope.property_ids
    )
    return errors


def _target_facts(engine: Engine, equipment_type: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT equipment_entity.id AS equipment_uuid,
                       equipment_entity.source_id AS equipment_id,
                       property_entity.source_id AS property_id,
                       property_space.property_type,
                       floor_entity.source_id AS floor_id,
                       location.source_id AS installation_location,
                       zone.id AS served_zone_uuid,
                       zone.source_id AS served_zone,
                       zone_space.usage_type AS served_zone_usage
                FROM equipment
                JOIN ontology_entities equipment_entity ON equipment_entity.id=equipment.entity_id
                LEFT JOIN ontology_relationships feed
                    ON feed.subject_id=equipment.entity_id AND feed.predicate='feeds'
                LEFT JOIN ontology_entities zone ON zone.id=feed.object_id
                LEFT JOIN spaces zone_space ON zone_space.entity_id=zone.id
                LEFT JOIN ontology_relationships zone_parent
                    ON zone_parent.subject_id=zone.id AND zone_parent.predicate='isPartOf'
                LEFT JOIN ontology_entities floor_entity ON floor_entity.id=zone_parent.object_id
                LEFT JOIN ontology_relationships floor_parent
                    ON floor_parent.subject_id=floor_entity.id AND floor_parent.predicate='isPartOf'
                LEFT JOIN ontology_entities property_entity ON property_entity.id=floor_parent.object_id
                LEFT JOIN spaces property_space ON property_space.entity_id=property_entity.id
                LEFT JOIN ontology_relationships installed
                    ON installed.subject_id=equipment.entity_id AND installed.predicate='hasLocation'
                LEFT JOIN ontology_entities location ON location.id=installed.object_id
                WHERE equipment.equipment_type=:equipment_type
                ORDER BY equipment_entity.source_id
                """
            ),
            {"equipment_type": equipment_type},
        ).mappings()
        targets = [dict(row) for row in rows]
        for target in targets:
            room_rows = connection.execute(
                text(
                    """
                    SELECT room.source_id, room_space.usage_type
                    FROM ontology_relationships containment
                    JOIN ontology_entities room ON room.id=containment.object_id
                    JOIN spaces room_space ON room_space.entity_id=room.id
                    WHERE containment.subject_id=:zone_id
                      AND containment.predicate='hasPart' AND room_space.space_type='Room'
                    ORDER BY room.source_id
                    """
                ),
                {"zone_id": target["served_zone_uuid"]},
            ).mappings() if target["served_zone_uuid"] else []
            target["occupied_rooms"] = [dict(room) for room in room_rows]
            point_rows = connection.execute(
                text(
                    """
                    SELECT point.source_id, telemetry_point.source_name
                    FROM ontology_relationships ownership
                    JOIN ontology_entities point ON point.id=ownership.object_id
                    JOIN telemetry_points telemetry_point ON telemetry_point.entity_id=point.id
                    WHERE ownership.subject_id=:equipment_id AND ownership.predicate='hasPoint'
                    ORDER BY telemetry_point.source_name
                    """
                ),
                {"equipment_id": target["equipment_uuid"]},
            )
            target["points"] = {
                point.source_name: point.source_id for point in point_rows
            }
    return targets


def preview_draft(engine: Engine, draft: RuleDraft) -> dict[str, Any]:
    reference_errors = validate_references(engine, draft)
    if reference_errors:
        return {"valid": False, "errors": reference_errors, "matched": [], "excluded": []}
    overrides = {override.property_id: override for override in draft.overrides}
    matched: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for fact in _target_facts(engine, draft.scope.equipment_type):
        reasons: list[str] = []
        if (
            fact["property_id"] not in draft.scope.property_ids
            or fact["floor_id"] not in draft.scope.floor_ids
            or fact["property_type"] != draft.scope.property_type
        ):
            reasons.append("OUTSIDE_SELECTED_SCOPE")
        eligible_rooms = [
            room["source_id"]
            for room in fact["occupied_rooms"]
            if room["usage_type"] in draft.scope.occupied_room_usage_types
        ]
        if fact["served_zone_usage"] not in draft.scope.served_zone_usage_types or not eligible_rooms:
            reasons.append("NOT_SERVING_TENANT_AREA")
        missing = sorted(set(draft.scope.required_points) - fact["points"].keys())
        if missing:
            reasons.append("REQUIRED_POINT_MISSING")
        override = overrides.get(fact["property_id"])
        item = {
            "canonical_equipment_id": str(fact["equipment_uuid"]),
            "equipment_id": fact["equipment_id"],
            "property_id": fact["property_id"],
            "floor_id": fact["floor_id"],
            "installation_location": fact["installation_location"],
            "served_zone": fact["served_zone"],
            "potentially_affected_rooms": eligible_rooms,
            "effective_threshold": (
                override.threshold if override and override.threshold is not None else draft.logic.threshold
            ),
            "effective_duration_seconds": (
                override.duration_seconds
                if override and override.duration_seconds is not None
                else draft.logic.duration_seconds
            ),
            "freshness_seconds": draft.logic.freshness_seconds,
            "required_datapoints": {
                name: fact["points"].get(name) for name in draft.scope.required_points
            },
            "effective_override": override.model_dump(exclude_none=True) if override else None,
            "exclusion_reasons": reasons,
        }
        (excluded if reasons else matched).append(item)
    return {
        "valid": True,
        "errors": [],
        "matched_count": len(matched),
        "excluded_count": len(excluded),
        "matched": matched,
        "excluded": excluded,
    }


def create_rule(engine: Engine, draft: RuleDraft) -> dict[str, Any]:
    errors = validate_references(engine, draft)
    if errors:
        raise ValueError("; ".join(errors))
    with engine.begin() as connection:
        rule_id = connection.execute(
            text(
                """
                INSERT INTO afdd_rules (rule_key, display_name)
                VALUES (:key, :name) RETURNING id
                """
            ),
            {"key": draft.rule_key, "name": draft.display_name},
        ).scalar_one()
    return create_rule_version(engine, str(rule_id), draft)


def create_rule_version(engine: Engine, rule_id: str, draft: RuleDraft) -> dict[str, Any]:
    errors = validate_references(engine, draft)
    if errors:
        raise ValueError("; ".join(errors))
    with engine.begin() as connection:
        rule = connection.execute(
            text("SELECT id, rule_key FROM afdd_rules WHERE id=CAST(:rule_id AS uuid)"),
            {"rule_id": rule_id},
        ).first()
        if not rule:
            raise LookupError("rule not found")
        if rule.rule_key != draft.rule_key:
            raise ValueError("rule_key cannot change between versions")
        version = connection.execute(
            text("SELECT coalesce(max(version),0)+1 FROM afdd_rule_versions WHERE rule_id=:rule_id"),
            {"rule_id": rule.id},
        ).scalar_one()
        version_id = connection.execute(
            text(
                """
                INSERT INTO afdd_rule_versions
                    (rule_id,version,severity,scope_config,logic_config)
                VALUES (:rule_id,:version,:severity,CAST(:scope AS jsonb),CAST(:logic AS jsonb))
                RETURNING id
                """
            ),
            {
                "rule_id": rule.id,
                "version": version,
                "severity": draft.severity,
                "scope": _json(draft.scope),
                "logic": _json(draft.logic),
            },
        ).scalar_one()
        for override in draft.overrides:
            property_id = connection.execute(
                text("SELECT id FROM ontology_entities WHERE source_id=:source_id"),
                {"source_id": override.property_id},
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO afdd_rule_overrides
                        (rule_version_id,property_id,threshold,duration_seconds)
                    VALUES (:version_id,:property_id,:threshold,:duration)
                    """
                ),
                {
                    "version_id": version_id,
                    "property_id": property_id,
                    "threshold": override.threshold,
                    "duration": override.duration_seconds,
                },
            )
        connection.execute(
            text("UPDATE afdd_rules SET display_name=:name WHERE id=:rule_id"),
            {"name": draft.display_name, "rule_id": rule.id},
        )
    return get_rule_version(engine, rule_id, version)


def _draft_from_version(row: Any, overrides: list[dict[str, Any]]) -> RuleDraft:
    return RuleDraft(
        rule_key=row.rule_key,
        display_name=row.display_name,
        severity=row.severity,
        scope=row.scope_config,
        logic=row.logic_config,
        overrides=overrides,
    )


def get_rule_version(engine: Engine, rule_id: str, version: int) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT version_row.id AS version_id, version_row.rule_id, rule.rule_key,
                       rule.display_name, version_row.version, version_row.severity,
                       version_row.scope_config, version_row.logic_config, version_row.created_at
                FROM afdd_rule_versions version_row
                JOIN afdd_rules rule ON rule.id=version_row.rule_id
                WHERE version_row.rule_id=CAST(:rule_id AS uuid) AND version_row.version=:version
                """
            ),
            {"rule_id": rule_id, "version": version},
        ).first()
        if not row:
            raise LookupError("rule version not found")
        overrides = [
            {
                "property_id": override.property_id,
                "threshold": override.threshold,
                "duration_seconds": override.duration_seconds,
            }
            for override in connection.execute(
                text(
                    """
                    SELECT property.source_id AS property_id, override.threshold,
                           override.duration_seconds
                    FROM afdd_rule_overrides override
                    JOIN ontology_entities property ON property.id=override.property_id
                    WHERE override.rule_version_id=:version_id ORDER BY property.source_id
                    """
                ),
                {"version_id": row.version_id},
            )
        ]
    result = _serializable(row)
    result["overrides"] = overrides
    return result


def draft_for_version(engine: Engine, rule_id: str, version: int) -> tuple[str, RuleDraft]:
    record = get_rule_version(engine, rule_id, version)
    return record["version_id"], RuleDraft(
        rule_key=record["rule_key"],
        display_name=record["display_name"],
        severity=record["severity"],
        scope=record["scope_config"],
        logic=record["logic_config"],
        overrides=record["overrides"],
    )


def activate_rule(engine: Engine, rule_id: str, version: int) -> dict[str, Any]:
    version_id, draft = draft_for_version(engine, rule_id, version)
    preview = preview_draft(engine, draft)
    if not preview["valid"] or not preview["matched"]:
        raise ValueError("rule activation requires a valid rule with at least one target")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE afdd_rules SET active_version_id=CAST(:version_id AS uuid), enabled=true,
                    activated_at=now(), disabled_at=NULL WHERE id=CAST(:rule_id AS uuid)
                """
            ),
            {"version_id": version_id, "rule_id": rule_id},
        )
    return get_rule(engine, rule_id)


def disable_rule(engine: Engine, rule_id: str) -> dict[str, Any]:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE afdd_rules SET enabled=false, disabled_at=now()
                WHERE id=CAST(:rule_id AS uuid) RETURNING id
                """
            ),
            {"rule_id": rule_id},
        ).first()
        if not result:
            raise LookupError("rule not found")
    return get_rule(engine, rule_id)


def get_rule(engine: Engine, rule_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT rule.id, rule.rule_key, rule.display_name, rule.enabled, rule.created_at,
                       rule.activated_at, rule.disabled_at, version.version AS active_version
                FROM afdd_rules rule
                LEFT JOIN afdd_rule_versions version ON version.id=rule.active_version_id
                WHERE rule.id=CAST(:rule_id AS uuid)
                """
            ),
            {"rule_id": rule_id},
        ).first()
        if not row:
            raise LookupError("rule not found")
        versions = connection.execute(
            text(
                "SELECT version, id AS version_id, created_at FROM afdd_rule_versions "
                "WHERE rule_id=CAST(:rule_id AS uuid) ORDER BY version"
            ),
            {"rule_id": rule_id},
        )
        result = _serializable(row)
        result["versions"] = [_serializable(version) for version in versions]
        return result


def list_rules(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        ids = connection.execute(text("SELECT id FROM afdd_rules ORDER BY rule_key")).scalars().all()
    return [get_rule(engine, str(rule_id)) for rule_id in ids]


def ensure_default_rule(engine: Engine, *, with_override: bool = True) -> dict[str, Any]:
    with engine.connect() as connection:
        existing = connection.execute(
            text("SELECT id FROM afdd_rules WHERE rule_key='ahu-sat-deviation'")
        ).scalar_one_or_none()
    if existing:
        return get_rule(engine, str(existing))
    version = create_rule(engine, default_sat_rule(with_override=with_override))
    return activate_rule(engine, version["rule_id"], version["version"])
