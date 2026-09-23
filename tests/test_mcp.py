"""Focused tests for the optional read-only MCP surface."""

import asyncio
import os
from collections import defaultdict
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from afdd.evaluator import evaluate_rule_version, list_issues
from afdd.rules import activate_rule, create_rule, default_sat_rule, get_rule
from afdd.seed import reset_inventory, seed_inventory
from afdd.simulator import source_events
from afdd.telemetry import process_payload
from apps.mcp.server import (
    READ_ONLY_TOOL_NAMES,
    get_equipment_context,
    get_issue_detail,
    get_portfolio_summary,
    mcp,
    preview_rule_targets,
)

ROOT = Path("/app/data/candidate-starter-pack")
SOURCE_DIR = Path(os.environ.get("SEED_SOURCE_DIR", ROOT / "building-and-equipment"))
TELEMETRY_DIR = ROOT / "sample-telemetry"


@pytest.fixture(scope="module")
def mcp_fixture() -> dict[str, str]:
    engine = create_engine(os.environ["DATABASE_URL"])
    reset_inventory(engine)
    seed_inventory(engine, SOURCE_DIR)
    events = defaultdict(list)
    for event in source_events(TELEMETRY_DIR):
        if event.equipment_id == "ahu-a-f02-east":
            events[event.equipment_id].append(event)
    for event in events["ahu-a-f02-east"]:
        process_payload(engine, event.model_dump(mode="json"))
    version = create_rule(engine, default_sat_rule(with_override=False))
    activate_rule(engine, version["rule_id"], version["version"])
    evaluate_rule_version(engine, version["rule_id"], version["version"])
    issue_id = list_issues(engine)[0]["id"]
    yield {"rule_id": version["rule_id"], "issue_id": issue_id}
    engine.dispose()


def _snapshot() -> tuple[int, int, int, int]:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT (SELECT count(*) FROM afdd_rules),
                           (SELECT count(*) FROM afdd_issues),
                           (SELECT count(*) FROM afdd_evaluation_states),
                           (SELECT count(*) FROM telemetry_readings)
                    """
                )
            ).one()
            return tuple(row)
    finally:
        engine.dispose()


def test_read_only_tool_registration() -> None:
    assert READ_ONLY_TOOL_NAMES == {
        "get_portfolio_summary",
        "get_equipment_context",
        "get_issue_detail",
        "preview_rule_targets",
    }
    forbidden = {"activate_rule", "confirm_rule", "create_rule", "execute_sql", "write_telemetry"}
    assert not READ_ONLY_TOOL_NAMES & forbidden
    assert {tool.name for tool in asyncio.run(mcp.list_tools())} == READ_ONLY_TOOL_NAMES


def test_mcp_queries_use_existing_read_models_without_mutation(mcp_fixture) -> None:
    before = _snapshot()
    portfolio = get_portfolio_summary()
    equipment = get_equipment_context("ahu-a-f02-east")
    issue = get_issue_detail(mcp_fixture["issue_id"])
    preview = preview_rule_targets(mcp_fixture["rule_id"], 1)
    after = _snapshot()

    assert portfolio["ok"] is True and len(portfolio["properties"]) == 3
    assert equipment["ok"] is True
    assert equipment["topology"]["installation_location"]["source_id"] == "building-a-plant-room"
    assert equipment["topology"]["served_zone"]["source_id"] == "building-a-f02-east"
    assert {item["measurement"] for item in equipment["latest_telemetry"]} >= {"RUN", "SAT", "SAT_SP"}
    assert issue["ok"] is True and issue["issue"]["equipment_source_id"] == "ahu-a-f02-east"
    assert issue["issue"]["rule_version"] == 1
    assert preview["ok"] is True and preview["preview"]["matched_count"] == 16
    assert before == after
    assert get_rule(create_engine(os.environ["DATABASE_URL"]), mcp_fixture["rule_id"])["enabled"] is True


def test_mcp_unknown_entity_errors_are_structured(mcp_fixture) -> None:
    equipment = get_equipment_context("does-not-exist")
    issue = get_issue_detail("00000000-0000-0000-0000-000000000000")
    preview = preview_rule_targets(mcp_fixture["rule_id"], 99)

    assert equipment["error"]["code"] == "EQUIPMENT_NOT_FOUND"
    assert issue["error"]["code"] == "ISSUE_NOT_FOUND"
    assert preview["error"]["code"] == "RULE_VERSION_NOT_FOUND"
