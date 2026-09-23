"""Small read-only MCP surface over the existing AFDD query layer.

This module deliberately contains no commands, activation, authoring, or
persistence functions.  MCP is optional and does not participate in the
normal product runtime.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine

from afdd.dashboard import equipment_context, operations_status, portfolio
from afdd.evaluator import get_issue, list_issues
from afdd.ontology import entity_by_source_id, equipment_topology
from afdd.rules import draft_for_version, preview_draft
from afdd.settings import get_settings
from afdd.telemetry import latest_for_equipment

READ_ONLY_TOOL_NAMES = frozenset(
    {
        "get_portfolio_summary",
        "get_equipment_context",
        "get_issue_detail",
        "preview_rule_targets",
    }
)

mcp = FastMCP("AFDD Read-Only Interface", json_response=True)


def _engine():
    return create_engine(get_settings().database_url)


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


@mcp.tool()
def get_portfolio_summary() -> dict[str, Any]:
    """Return portfolio, telemetry health, evaluation status, and issue summary."""

    engine = _engine()
    try:
        issues = list_issues(engine)
        return {
            "ok": True,
            "operations": operations_status(engine),
            "properties": portfolio(engine),
            "issues": {
                "open": sum(issue["status"] == "OPEN" for issue in issues),
                "closed": sum(issue["status"] == "CLOSED" for issue in issues),
            },
        }
    finally:
        engine.dispose()


@mcp.tool()
def get_equipment_context(equipment_id: str) -> dict[str, Any]:
    """Inspect one canonical equipment source ID and its explicit topology/telemetry."""

    engine = _engine()
    try:
        entity = entity_by_source_id(engine, equipment_id)
        topology = equipment_topology(engine, equipment_id)
        if entity is None or topology is None:
            return _error("EQUIPMENT_NOT_FOUND", f"Unknown equipment: {equipment_id}")
        return {
            "ok": True,
            "equipment": entity,
            "topology": topology,
            "latest_telemetry": latest_for_equipment(engine, equipment_id),
            "related_context": equipment_context(engine, equipment_id),
        }
    finally:
        engine.dispose()


@mcp.tool()
def get_issue_detail(issue_id: str) -> dict[str, Any]:
    """Return persisted issue evidence for a concrete issue ID; never alters lifecycle state."""

    engine = _engine()
    try:
        issue = get_issue(engine, issue_id)
        if issue is None:
            return _error("ISSUE_NOT_FOUND", f"Unknown issue: {issue_id}")
        return {"ok": True, "issue": issue}
    finally:
        engine.dispose()


@mcp.tool()
def preview_rule_targets(rule_id: str, version: int) -> dict[str, Any]:
    """Resolve matched targets and exclusions for one immutable rule version."""

    engine = _engine()
    try:
        try:
            _, draft = draft_for_version(engine, rule_id, version)
        except (LookupError, ValueError):
            return _error("RULE_VERSION_NOT_FOUND", f"Unknown rule/version: {rule_id}/{version}")
        return {"ok": True, "rule_id": rule_id, "version": version, "preview": preview_draft(engine, draft)}
    finally:
        engine.dispose()


def main() -> None:
    """Run the standard MCP stdio transport for a local MCP-compatible client."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
