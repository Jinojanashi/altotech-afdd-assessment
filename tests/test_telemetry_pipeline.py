import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from afdd.seed import reset_inventory, seed_inventory
from afdd.simulator import source_events
from afdd.telemetry import latest_for_equipment, point_history, process_payload, telemetry_status
from apps.api.main import app

ROOT = Path("/app/data/candidate-starter-pack")
SOURCE_DIR = Path(os.environ.get("SEED_SOURCE_DIR", ROOT / "building-and-equipment"))
TELEMETRY_DIR = ROOT / "sample-telemetry"


@pytest.fixture(scope="module")
def telemetry_engine():
    engine = create_engine(os.environ["DATABASE_URL"])
    reset_inventory(engine)
    seed_inventory(engine, SOURCE_DIR)
    return engine


@pytest.fixture(autouse=True)
def empty_telemetry(telemetry_engine):
    with telemetry_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE ingestion_events CASCADE"))


def event_rows(equipment_id: str):
    return [event for event in source_events(TELEMETRY_DIR) if event.equipment_id == equipment_id]


def test_source_event_count_and_normal_canonical_resolution(telemetry_engine) -> None:
    events = source_events(TELEMETRY_DIR)
    first = next(events)
    assert sum(1 for _ in events) + 1 == 30_237
    result = process_payload(telemetry_engine, first.model_dump(mode="json"))
    assert result.status == "ACCEPTED" and result.observations == 5
    latest = latest_for_equipment(telemetry_engine, first.equipment_id)
    sat = next(item for item in latest if item["measurement"] == "SAT")
    assert sat["unit"] == "degC" and sat["quality"] == "GOOD"


def test_duplicate_and_replay_are_idempotent(telemetry_engine) -> None:
    duplicate_rows = [event for event in source_events(TELEMETRY_DIR) if event.source_record_id == "src-ahu-0100-001"]
    assert len(duplicate_rows) == 2
    assert process_payload(telemetry_engine, duplicate_rows[0].model_dump(mode="json")).status == "ACCEPTED"
    assert process_payload(telemetry_engine, duplicate_rows[1].model_dump(mode="json")).status == "DUPLICATE"
    assert process_payload(telemetry_engine, duplicate_rows[0].model_dump(mode="json")).status == "DUPLICATE"
    with telemetry_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM telemetry_readings")).scalar_one() == 5
    assert telemetry_status(telemetry_engine) == {"accepted": 1, "duplicates": 2, "rejected": 0, "observations": 5}


def test_late_history_is_retained_without_current_regression(telemetry_engine) -> None:
    events = event_rows("ahu-a-f01-east")
    late = events[-1]
    newest = max(events[:-1], key=lambda event: event.observed_at)
    process_payload(telemetry_engine, newest.model_dump(mode="json"))
    process_payload(telemetry_engine, late.model_dump(mode="json"))
    sat = next(item for item in latest_for_equipment(telemetry_engine, "ahu-a-f01-east") if item["measurement"] == "SAT")
    assert sat["observed_at"].startswith("2026-01-15 13:59:00")
    history = point_history(
        telemetry_engine, "ahu-a-f01-east-sat",
        datetime(2026, 1, 15, 8, tzinfo=UTC), datetime(2026, 1, 15, 14, tzinfo=UTC),
    )
    assert [item["observed_at"] for item in history] == [
        "2026-01-15 09:10:00+00:00", "2026-01-15 13:59:00+00:00",
    ]


def test_unknown_equipment_is_visibly_rejected(telemetry_engine) -> None:
    event = event_rows("unknown-ahu-999")[0]
    result = process_payload(telemetry_engine, event.model_dump(mode="json"))
    assert result.status == "REJECTED" and result.reason == "unknown_equipment"
    assert telemetry_status(telemetry_engine)["observations"] == 0


def test_malformed_event_is_quarantined(telemetry_engine) -> None:
    result = process_payload(telemetry_engine, b"not-json")
    assert result.status == "REJECTED" and result.reason.startswith("invalid_event:")
    status = telemetry_status(telemetry_engine)
    assert status["rejected"] == 1 and status["observations"] == 0


def test_missing_period_remains_a_gap(telemetry_engine) -> None:
    for event in event_rows("ahu-c-f03-east"):
        process_payload(telemetry_engine, event.model_dump(mode="json"))
    history = point_history(
        telemetry_engine, "ahu-c-f03-east-sat",
        datetime(2026, 1, 15, 11, tzinfo=UTC), datetime(2026, 1, 15, 11, 4, tzinfo=UTC),
    )
    assert history == []


def test_blank_sat_sp_is_not_synthesized(telemetry_engine) -> None:
    events = [event for event in event_rows("ahu-a-f04-west") if datetime(2026, 1, 15, 12, 10, tzinfo=UTC) <= event.observed_at <= datetime(2026, 1, 15, 12, 15, tzinfo=UTC)]
    assert len(events) == 6 and all("SAT_SP" not in {m.measurement for m in event.measurements} for event in events)
    for event in events:
        process_payload(telemetry_engine, event.model_dump(mode="json"))
    history = point_history(
        telemetry_engine, "ahu-a-f04-west-sat-sp",
        datetime(2026, 1, 15, 12, 10, tzinfo=UTC), datetime(2026, 1, 15, 12, 15, tzinfo=UTC),
    )
    assert history == []


def test_telemetry_api_latest_history_and_status(telemetry_engine) -> None:
    event = next(event for event in source_events(TELEMETRY_DIR) if event.equipment_id == "meter-a-f01")
    process_payload(telemetry_engine, event.model_dump(mode="json"))
    client = TestClient(app)
    latest = client.get("/telemetry/equipment/meter-a-f01/latest")
    assert latest.status_code == 200 and len(latest.json()) == 2
    history = client.get(
        "/telemetry/points/meter-a-f01-power/history",
        params={"start": "2026-01-15T08:00:00Z", "end": "2026-01-15T08:01:00Z"},
    )
    assert history.status_code == 200 and history.json()[0]["unit"] == "kW"
    assert client.get("/ingestion/status").json()["accepted"] == 1
