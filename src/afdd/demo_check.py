"""Fail-fast readiness and deterministic demo evidence checks."""

import argparse
import json
import time
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, create_engine, text

from afdd.settings import get_settings

EXPECTED_INGESTION = {
    "accepted": 30_235,
    "duplicates": 1,
    "rejected": 1,
    "observations": 103_649,
    "current_points": 288,
}


def _scalar(connection: Any, query: str, **params: Any) -> int:
    return int(connection.execute(text(query), params).scalar_one())


def collect_counts(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        inventory = {
            "spaces": _scalar(connection, "SELECT count(*) FROM spaces"),
            "equipment": _scalar(connection, "SELECT count(*) FROM equipment"),
            "points": _scalar(connection, "SELECT count(*) FROM telemetry_points"),
            "canonical_entities": _scalar(connection, "SELECT count(*) FROM ontology_entities"),
            "relationships": _scalar(connection, "SELECT count(*) FROM ontology_relationships"),
            "buildings": _scalar(connection, "SELECT count(*) FROM spaces WHERE space_type='Building'"),
            "floors": _scalar(connection, "SELECT count(*) FROM spaces WHERE space_type='Floor'"),
            "hvac_zones": _scalar(connection, "SELECT count(*) FROM spaces WHERE space_type='HVAC Zone'"),
            "occupied_rooms": _scalar(
                connection,
                "SELECT count(*) FROM spaces WHERE space_type='Room' "
                "AND usage_type IN ('Office Room','Guest Room')",
            ),
            "ahus": _scalar(connection, "SELECT count(*) FROM equipment WHERE equipment_type='AHU'"),
            "iaq_devices": _scalar(
                connection, "SELECT count(*) FROM equipment WHERE equipment_type='IAQ Sensor'"
            ),
            "electricity_meters": _scalar(
                connection, "SELECT count(*) FROM equipment WHERE equipment_type='Electricity Meter'"
            ),
        }
        ingestion = {
            "accepted": _scalar(
                connection,
                "SELECT count(*) FROM ingestion_attempts WHERE disposition='ACCEPTED'",
            ),
            "duplicates": _scalar(
                connection,
                "SELECT count(*) FROM ingestion_attempts WHERE disposition='DUPLICATE'",
            ),
            "rejected": _scalar(
                connection,
                "SELECT count(*) FROM ingestion_attempts WHERE disposition='REJECTED'",
            ),
            "observations": _scalar(connection, "SELECT count(*) FROM telemetry_readings"),
            "current_points": _scalar(connection, "SELECT count(*) FROM current_point_values"),
        }
    return {"inventory": inventory, "ingestion": ingestion}


def wait_for_ingestion(engine: Engine, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        counts = collect_counts(engine)
        actual = counts["ingestion"]
        if actual == EXPECTED_INGESTION:
            return counts
        if any(actual[key] > expected for key, expected in EXPECTED_INGESTION.items()):
            raise RuntimeError(f"ingestion counts exceeded deterministic expectation: {actual}")
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"ingestion did not complete within {timeout_seconds}s: {actual}; "
                f"expected {EXPECTED_INGESTION}"
            )
        time.sleep(0.5)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def verify_demo(engine: Engine) -> dict[str, Any]:
    counts = collect_counts(engine)
    expected_inventory = {
        "spaces": 93,
        "equipment": 84,
        "points": 288,
        "canonical_entities": 465,
        "relationships": 888,
        "buildings": 3,
        "floors": 12,
        "hvac_zones": 24,
        "occupied_rooms": 48,
        "ahus": 24,
        "iaq_devices": 48,
        "electricity_meters": 12,
    }
    _assert_equal(counts["inventory"], expected_inventory, "canonical inventory")
    _assert_equal(counts["ingestion"], EXPECTED_INGESTION, "telemetry ingestion")

    with engine.connect() as connection:
        issue_rows = connection.execute(
            text(
                """
                SELECT issue.*, entity.source_id AS equipment_source_id,
                       version.version AS rule_version
                FROM afdd_issues issue
                JOIN ontology_entities entity ON entity.id=issue.equipment_id
                JOIN afdd_rule_versions version ON version.id=issue.rule_version_id
                ORDER BY entity.source_id
                """
            )
        ).mappings().all()
        issues = {row["equipment_source_id"]: row for row in issue_rows}
        _assert_equal(set(issues), {"ahu-a-f02-east", "ahu-b-f01-west"}, "issue equipment")

        hero = issues["ahu-a-f02-east"]
        _assert_equal(hero["status"], "CLOSED", "hero status")
        _assert_equal(hero["severity"], "Critical", "hero severity")
        _assert_equal(float(hero["threshold"]), 3.0, "hero threshold")
        _assert_equal(hero["duration_seconds"], 900, "hero duration")
        _assert_equal(_iso(hero["qualifying_started_at"]), "2026-01-15T10:00:00+00:00", "hero qualification")
        _assert_equal(_iso(hero["opened_at"]), "2026-01-15T10:15:00+00:00", "hero opened")
        _assert_equal(_iso(hero["closed_at"]), "2026-01-15T10:21:00+00:00", "hero recovered")
        evidence = hero["evidence"]
        topology = evidence["topology"]
        _assert_equal(topology["installation_location"], "building-a-plant-room", "hero installation")
        _assert_equal(topology["served_zone"], "building-a-f02-east", "hero served zone")
        _assert_equal(
            topology["potentially_affected_rooms"],
            ["building-a-f02-east-r01", "building-a-f02-east-r02"],
            "hero affected rooms",
        )
        _assert_equal(evidence["rule"]["version"], hero["rule_version"], "opening rule version")
        required = {"RUN", "SAT", "SAT_SP"}
        if not evidence["samples"] or any(
            not required.issubset(sample["readings"]) for sample in evidence["samples"]
        ):
            raise AssertionError("hero evidence lacks RUN/SAT/SAT_SP samples")
        if any(sample.get("absolute_difference") is None for sample in evidence["samples"]):
            raise AssertionError("hero evidence lacks calculated differences")

        override = issues["ahu-b-f01-west"]
        _assert_equal(float(override["threshold"]), 2.0, "Building B effective threshold")
        _assert_equal(_iso(override["qualifying_started_at"]), "2026-01-15T11:20:00+00:00", "override qualification")
        _assert_equal(_iso(override["opened_at"]), "2026-01-15T11:35:00+00:00", "override opened")
        _assert_equal(_iso(override["closed_at"]), "2026-01-15T11:41:00+00:00", "override recovered")
        _assert_equal(override["effective_override"]["property_id"], "building-b", "override scope")

        excluded_issue_count = _scalar(
            connection,
            """SELECT count(*) FROM afdd_issues issue
               JOIN ontology_entities entity ON entity.id=issue.equipment_id
               WHERE entity.source_id IN ('ahu-a-f03-west','ahu-b-f04-east','ahu-a-f04-west')""",
        )
        _assert_equal(excluded_issue_count, 0, "non-trigger case issues")

        late_history = _scalar(
            connection,
            """SELECT count(*) FROM telemetry_readings reading
               JOIN ontology_entities equipment ON equipment.id=reading.equipment_id
               WHERE equipment.source_id='ahu-a-f01-east'
                 AND reading.observed_at='2026-01-15T09:10:00Z'""",
        )
        _assert_equal(late_history, 5, "retained canonical late-row point history")
        latest_after_late = _scalar(
            connection,
            """SELECT count(*) FROM current_point_values current
               JOIN ontology_entities equipment ON equipment.id=current.equipment_id
               WHERE equipment.source_id='ahu-a-f01-east'
                 AND current.observed_at='2026-01-15T13:59:00Z'""",
        )
        _assert_equal(latest_after_late, 5, "latest state after late delivery")

    return {
        **counts,
        "issues": {
            "total": len(issue_rows),
            "hero": {
                "equipment_id": "ahu-a-f02-east",
                "severity": hero["severity"],
                "status": hero["status"],
                "qualifying_started_at": _iso(hero["qualifying_started_at"]),
                "opened_at": _iso(hero["opened_at"]),
                "closed_at": _iso(hero["closed_at"]),
                "threshold": hero["threshold"],
                "duration_seconds": hero["duration_seconds"],
                "rule_version": hero["rule_version"],
                "installation_location": topology["installation_location"],
                "served_zone": topology["served_zone"],
                "potentially_affected_rooms": topology["potentially_affected_rooms"],
            },
            "building_b_override": {
                "equipment_id": "ahu-b-f01-west",
                "threshold": override["threshold"],
                "qualifying_started_at": _iso(override["qualifying_started_at"]),
                "opened_at": _iso(override["opened_at"]),
                "closed_at": _iso(override["closed_at"]),
            },
            "verified_non_triggers": ["ahu-a-f03-west", "ahu-b-f04-east", "ahu-a-f04-west"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait", action="store_true", help="wait for deterministic ingestion completion")
    parser.add_argument("--verify", action="store_true", help="verify all deterministic demo evidence")
    parser.add_argument("--quiet", action="store_true", help="print only a concise success line")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if not args.wait and not args.verify:
        parser.error("choose --wait or --verify")
    engine = create_engine(get_settings().database_url)
    try:
        result = (
            wait_for_ingestion(engine, args.timeout_seconds)
            if args.wait
            else verify_demo(engine)
        )
        if args.quiet:
            print("PASS deterministic inventory, telemetry, AFDD, override, and negative cases")
        else:
            print(json.dumps(result, default=str, indent=2, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
