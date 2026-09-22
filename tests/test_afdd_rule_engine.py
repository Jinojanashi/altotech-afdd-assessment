import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError

from afdd.evaluator import (
    EvaluationSample,
    InputReading,
    evaluate_rule_version,
    evaluate_sample,
    get_issue,
    list_issues,
    reset_evaluation,
)
from afdd.rules import (
    FaultLogic,
    PropertyOverride,
    RuleDraft,
    TargetScope,
    activate_rule,
    create_rule,
    create_rule_version,
    default_sat_rule,
    get_rule,
    get_rule_version,
    preview_draft,
)
from afdd.seed import reset_inventory, seed_inventory
from afdd.simulator import source_events
from afdd.telemetry import process_payload
from apps.api.main import app

ROOT = Path("/app/data/candidate-starter-pack")
SOURCE_DIR = Path(os.environ.get("SEED_SOURCE_DIR", ROOT / "building-and-equipment"))
TELEMETRY_DIR = ROOT / "sample-telemetry"
CASES = {
    "ahu-a-f01-east",
    "ahu-a-f02-east",
    "ahu-a-f03-west",
    "ahu-a-f04-west",
    "ahu-b-f01-west",
    "ahu-b-f04-east",
    "ahu-c-f03-east",
}


@pytest.fixture(scope="module")
def afdd_engine():
    engine = create_engine(os.environ["DATABASE_URL"])
    reset_inventory(engine)
    seed_inventory(engine, SOURCE_DIR)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def case_events():
    grouped = defaultdict(list)
    for event in source_events(TELEMETRY_DIR):
        if event.equipment_id in CASES:
            grouped[event.equipment_id].append(event)
    return grouped


@pytest.fixture(autouse=True)
def clean_rule_data(afdd_engine):
    with afdd_engine.begin() as connection:
        connection.execute(text("TRUNCATE ingestion_events CASCADE"))
        connection.execute(text("TRUNCATE afdd_rules CASCADE"))


def store_events(engine, events) -> None:
    for event in events:
        process_payload(engine, event.model_dump(mode="json"))


def create_active_rule(engine, draft: RuleDraft | None = None):
    version = create_rule(engine, draft or default_sat_rule())
    activate_rule(engine, version["rule_id"], version["version"])
    return version


def one_floor_rule(*, duration: int = 120, freshness: int = 120) -> RuleDraft:
    return RuleDraft(
        rule_key="test-sat-deviation",
        display_name="Test SAT deviation",
        scope=TargetScope(
            property_ids=["building-a"],
            floor_ids=["building-a-f02"],
        ),
        logic=FaultLogic(duration_seconds=duration, freshness_seconds=freshness),
    )


def sample(at: datetime, *, run="ON", sat=18.5, sat_sp=14.0, ages=None, missing=()) -> EvaluationSample:
    ages = ages or {}
    values = {"RUN": run, "SAT": sat, "SAT_SP": sat_sp}
    readings = {
        name: InputReading(value, at - timedelta(seconds=ages.get(name, 0)))
        for name, value in values.items()
        if name not in missing
    }
    return EvaluationSample("ahu-a-f02-east", at, readings, event_id=f"fixture-{at.isoformat()}")


def test_rule_schema_validation() -> None:
    assert default_sat_rule().logic.threshold == 3.0
    with pytest.raises(ValidationError):
        FaultLogic(threshold=0)
    with pytest.raises(ValidationError):
        TargetScope(
            property_ids=["building-a"],
            floor_ids=["building-a-f01"],
            required_points=["RUN", "SAT"],
        )
    with pytest.raises(ValidationError):
        PropertyOverride(property_id="building-a")


def test_target_preview_uses_ontology_and_effective_override(afdd_engine) -> None:
    preview = preview_draft(afdd_engine, default_sat_rule())
    assert preview["valid"] and preview["matched_count"] == 16
    assert preview["excluded_count"] == 8
    assert all("OUTSIDE_SELECTED_SCOPE" in item["exclusion_reasons"] for item in preview["excluded"])
    target = next(item for item in preview["matched"] if item["equipment_id"] == "ahu-a-f02-east")
    assert target["installation_location"] == "building-a-plant-room"
    assert target["served_zone"] == "building-a-f02-east"
    assert target["potentially_affected_rooms"] == [
        "building-a-f02-east-r01",
        "building-a-f02-east-r02",
    ]
    assert set(target["required_datapoints"]) == {"RUN", "SAT", "SAT_SP"}
    overridden = next(item for item in preview["matched"] if item["equipment_id"] == "ahu-b-f01-west")
    assert overridden["effective_threshold"] == 2.0


def test_versions_are_immutable_and_edit_does_not_activate(afdd_engine) -> None:
    v1 = create_active_rule(afdd_engine, default_sat_rule(with_override=False))
    edited = default_sat_rule(with_override=False).model_copy(
        update={"logic": FaultLogic(threshold=4.0)}
    )
    v2 = create_rule_version(afdd_engine, v1["rule_id"], edited)
    assert v2["version"] == 2
    assert get_rule(afdd_engine, v1["rule_id"])["active_version"] == 1
    assert get_rule_version(afdd_engine, v1["rule_id"], 1)["logic_config"]["threshold"] == 3.0
    with pytest.raises(DatabaseError), afdd_engine.begin() as connection:
        connection.execute(
            text("UPDATE afdd_rule_versions SET severity='Warning' WHERE id=CAST(:id AS uuid)"),
            {"id": v1["version_id"]},
        )


def test_supplied_cases_evidence_recovery_late_and_version_preservation(
    afdd_engine, case_events
) -> None:
    for equipment_id in CASES - {"ahu-c-f03-east"}:
        store_events(afdd_engine, case_events[equipment_id])
    version = create_active_rule(afdd_engine)
    result = evaluate_rule_version(afdd_engine, version["rule_id"], 1)
    assert result["targets"] == 16 and result["issues"] == {"open": 0, "closed": 2}
    assert result["outcomes"]["IGNORED_LATE_OR_EQUAL"] == 1
    assert result["outcomes"]["UNTRUSTWORTHY_INPUT"] >= 6

    issues = list_issues(afdd_engine)
    assert {issue["equipment_id"] for issue in issues} == {
        "ahu-a-f02-east",
        "ahu-b-f01-west",
    }
    sustained = next(issue for issue in issues if issue["equipment_id"] == "ahu-a-f02-east")
    assert sustained["severity"] == "Critical" and sustained["status"] == "CLOSED"
    assert sustained["qualifying_started_at"] == "2026-01-15T10:00:00+00:00"
    assert sustained["opened_at"] == "2026-01-15T10:15:00+00:00"
    assert sustained["closed_at"] == "2026-01-15T10:21:00+00:00"
    evidence = get_issue(afdd_engine, sustained["id"])["evidence"]
    assert evidence["topology"] == {
        "property_id": "building-a",
        "floor_id": "building-a-f02",
        "installation_location": "building-a-plant-room",
        "served_zone": "building-a-f02-east",
        "potentially_affected_rooms": [
            "building-a-f02-east-r01",
            "building-a-f02-east-r02",
        ],
    }
    assert len(evidence["samples"]) == 16
    assert evidence["samples"][-1]["absolute_difference"] == pytest.approx(4.4)
    assert evidence["samples"][-1]["readings"]["RUN"]["value"] == "ON"

    assert not any(issue["equipment_id"] == "ahu-a-f03-west" for issue in issues)
    assert not any(issue["equipment_id"] == "ahu-b-f04-east" for issue in issues)
    assert not any(issue["equipment_id"] == "ahu-a-f04-west" for issue in issues)

    repeated = evaluate_rule_version(afdd_engine, version["rule_id"], 1)
    assert repeated["issues"] == {"open": 0, "closed": 2}

    edited = default_sat_rule().model_copy(update={"logic": FaultLogic(threshold=4.5)})
    create_rule_version(afdd_engine, version["rule_id"], edited)
    activate_rule(afdd_engine, version["rule_id"], 2)
    preserved = get_issue(afdd_engine, sustained["id"])
    assert preserved["rule_version"] == 1
    assert preserved["evidence"]["rule"]["logic"]["threshold"] == 3.0


def test_default_vs_property_override_on_supplied_case(afdd_engine, case_events) -> None:
    store_events(afdd_engine, case_events["ahu-b-f01-west"])
    default_version = create_active_rule(afdd_engine, default_sat_rule(with_override=False))
    evaluate_rule_version(afdd_engine, default_version["rule_id"], 1)
    assert list_issues(afdd_engine) == []

    overridden = default_sat_rule(with_override=True)
    version2 = create_rule_version(afdd_engine, default_version["rule_id"], overridden)
    activate_rule(afdd_engine, default_version["rule_id"], version2["version"])
    reset_evaluation(afdd_engine)
    evaluate_rule_version(afdd_engine, default_version["rule_id"], 2)
    issues = list_issues(afdd_engine)
    assert len(issues) == 1 and issues[0]["equipment_id"] == "ahu-b-f01-west"
    assert issues[0]["opened_at"] == "2026-01-15T11:35:00+00:00"
    detail = get_issue(afdd_engine, issues[0]["id"])
    assert detail["threshold"] == 2.0
    assert detail["effective_override"] == {"property_id": "building-b", "threshold": 2.0}


def test_supplied_entire_gap_resets_continuity(afdd_engine, case_events) -> None:
    gap_events = [
        event
        for event in case_events["ahu-c-f03-east"]
        if datetime(2026, 1, 15, 10, 56, tzinfo=UTC)
        <= event.observed_at
        <= datetime(2026, 1, 15, 11, 9, tzinfo=UTC)
    ]
    assert [event.observed_at.minute for event in gap_events] == [56, 57, 58, 59, 5, 6, 7, 8, 9]
    store_events(afdd_engine, gap_events)
    hotel_rule = RuleDraft(
        rule_key="hotel-gap-test",
        display_name="Hotel gap continuity fixture",
        scope=TargetScope(
            property_type="Hotel",
            property_ids=["building-c"],
            floor_ids=["building-c-f03"],
            served_zone_usage_types=["Guest Area"],
            occupied_room_usage_types=["Guest Room"],
        ),
        logic=FaultLogic(threshold=0.1, duration_seconds=240, freshness_seconds=120),
    )
    version = create_active_rule(afdd_engine, hotel_rule)
    result = evaluate_rule_version(afdd_engine, version["rule_id"], 1)
    assert result["targets"] == 2
    issues = list_issues(afdd_engine)
    assert len(issues) == 1 and issues[0]["equipment_id"] == "ahu-c-f03-east"
    assert issues[0]["qualifying_started_at"] == "2026-01-15T11:05:00+00:00"
    assert issues[0]["opened_at"] == "2026-01-15T11:09:00+00:00"


def test_missing_stale_gap_recovery_recurrence_and_late_semantics(afdd_engine) -> None:
    version = create_active_rule(afdd_engine, one_floor_rule())
    preview = preview_draft(afdd_engine, one_floor_rule())
    target = next(item for item in preview["matched"] if item["equipment_id"] == "ahu-a-f02-east")
    _, draft = version["version_id"], one_floor_rule()
    args = {
        "rule_id": version["rule_id"],
        "version_id": version["version_id"],
        "version": 1,
        "draft": draft,
        "target": target,
    }
    start = datetime(2026, 1, 15, 10, tzinfo=UTC)
    assert evaluate_sample(afdd_engine, sample=sample(start, missing=("SAT_SP",)), **args) == "UNTRUSTWORTHY_INPUT"
    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=1), ages={"SAT": 121}), **args) == "UNTRUSTWORTHY_INPUT"
    assert list_issues(afdd_engine) == []

    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=2)), **args) == "QUALIFYING"
    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=5)), **args) == "QUALIFYING"
    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=6)), **args) == "QUALIFYING"
    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=7)), **args) == "OPENED"
    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=7)), **args) == "IGNORED_LATE_OR_EQUAL"
    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=3)), **args) == "IGNORED_LATE_OR_EQUAL"
    assert evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=8), sat=14.5), **args) == "CLOSED"

    for minute in (9, 10, 11):
        evaluate_sample(afdd_engine, sample=sample(start + timedelta(minutes=minute)), **args)
    issues = list_issues(afdd_engine)
    assert len(issues) == 2
    assert [issue["occurrence"] for issue in issues] == [1, 2]
    assert issues[0]["status"] == "CLOSED" and issues[1]["status"] == "OPEN"


def test_required_point_missing_is_visible_without_modifying_source(afdd_engine) -> None:
    try:
        with afdd_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ontology_entities WHERE source_id='ahu-a-f02-east-sat-sp'")
            )
        preview = preview_draft(afdd_engine, default_sat_rule())
        excluded = next(
            item for item in preview["excluded"] if item["equipment_id"] == "ahu-a-f02-east"
        )
        assert excluded["exclusion_reasons"] == ["REQUIRED_POINT_MISSING"]
        assert excluded["required_datapoints"]["SAT_SP"] is None
    finally:
        seed_inventory(afdd_engine, SOURCE_DIR)


def test_deterministic_replay_and_minimal_api(afdd_engine, case_events) -> None:
    store_events(afdd_engine, case_events["ahu-a-f02-east"])
    version = create_active_rule(afdd_engine, default_sat_rule(with_override=False))
    first = evaluate_rule_version(afdd_engine, version["rule_id"], 1)
    first_issue = list_issues(afdd_engine)[0]
    first_evidence = get_issue(afdd_engine, first_issue["id"])["evidence"]
    reset_evaluation(afdd_engine)
    second = evaluate_rule_version(afdd_engine, version["rule_id"], 1)
    second_issue = list_issues(afdd_engine)[0]
    second_evidence = get_issue(afdd_engine, second_issue["id"])["evidence"]
    assert first == second
    assert first_issue["opened_at"] == second_issue["opened_at"]
    assert first_evidence == second_evidence

    client = TestClient(app)
    assert client.get("/rules").status_code == 200
    preview_response = client.get(f"/rules/{version['rule_id']}/versions/1/preview")
    assert preview_response.status_code == 200 and preview_response.json()["matched_count"] == 16
    issues_response = client.get("/issues")
    assert issues_response.status_code == 200 and len(issues_response.json()) == 1
    detail = client.get(f"/issues/{second_issue['id']}")
    assert detail.status_code == 200 and detail.json()["evidence"]["rule"]["version"] == 1
