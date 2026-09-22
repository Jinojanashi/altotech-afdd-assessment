"""Read-only historical AFDD simulation using the production state machine."""

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, text

from afdd.evaluator import evaluate_transition, sample_from_event
from afdd.events import TelemetryEvent
from afdd.rules import draft_for_version, preview_draft


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value else None


def _non_trigger_reason(sample_count: int, outcomes: Counter[str], reasons: Counter[str]) -> str:
    if sample_count == 0:
        return "NO_TELEMETRY_IN_WINDOW"
    if outcomes["QUALIFYING"]:
        return "DURATION_NOT_MET"
    if reasons["AHU_OFF"]:
        return "AHU_OFF"
    if outcomes["UNTRUSTWORTHY_INPUT"]:
        return "UNTRUSTWORTHY_INPUT"
    return "CONDITION_NOT_MET"


def backtest_rule_version(
    engine: Engine,
    *,
    rule_id: str,
    version: int,
    start: datetime,
    end: datetime,
    threshold: float | None = None,
    duration_seconds: int | None = None,
) -> dict[str, Any]:
    """Simulate one immutable rule version without persisting issues or evaluator state."""

    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError("start must be before end")

    version_id, draft = draft_for_version(engine, rule_id, version)
    preview = preview_draft(engine, draft)
    if not preview["valid"]:
        raise ValueError("rule version has invalid ontology references")

    targets: dict[str, dict[str, Any]] = {}
    for original in preview["matched"]:
        target = dict(original)
        if threshold is not None:
            target["effective_threshold"] = threshold
        if duration_seconds is not None:
            target["effective_duration_seconds"] = duration_seconds
        targets[target["equipment_id"]] = target

    payloads: list[dict[str, Any]] = []
    if targets:
        with engine.connect() as connection:
            payloads = list(
                connection.execute(
                    text(
                        """
                        SELECT payload FROM ingestion_events
                        WHERE processing_status='ACCEPTED'
                          AND equipment_source_id=ANY(CAST(:equipment_ids AS text[]))
                          AND observed_at >= :start AND observed_at <= :end
                        ORDER BY received_at,event_id
                        """
                    ),
                    {
                        "equipment_ids": sorted(targets),
                        "start": start,
                        "end": end,
                    },
                ).scalars()
            )

    events_by_equipment: dict[str, list[TelemetryEvent]] = {
        equipment_id: [] for equipment_id in targets
    }
    for payload in payloads:
        event = TelemetryEvent.model_validate(payload)
        events_by_equipment[event.equipment_id].append(event)

    results: list[dict[str, Any]] = []
    for equipment_id, target in targets.items():
        state: dict[str, Any] = {
            "state": "NORMAL",
            "last_observed_at": None,
            "qualifying_started_at": None,
            "qualifying_evidence": [],
        }
        occurrences: list[dict[str, Any]] = []
        outcomes: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        for event in events_by_equipment[equipment_id]:
            transition = evaluate_transition(
                state=state,
                draft=draft,
                target=target,
                sample=sample_from_event(event),
            )
            outcomes[transition.outcome] += 1
            if transition.issue_reason:
                reasons[transition.issue_reason] += 1
            if transition.issue_action == "OPEN":
                occurrences.append(
                    {
                        "qualifying_started_at": _iso(transition.issue_started_at),
                        "would_open_at": _iso(transition.last_observed_at),
                        "would_recover_at": None,
                    }
                )
            elif transition.issue_action == "CLOSE" and occurrences:
                occurrences[-1]["would_recover_at"] = _iso(transition.last_observed_at)
            if transition.persist_state:
                state = {
                    "state": transition.state,
                    "last_observed_at": transition.last_observed_at,
                    "qualifying_started_at": transition.qualifying_started_at,
                    "qualifying_evidence": transition.qualifying_evidence,
                }

        first = occurrences[0] if occurrences else {}
        results.append(
            {
                "equipment_id": equipment_id,
                "would_trigger": bool(occurrences),
                "qualifying_started_at": first.get("qualifying_started_at"),
                "would_open_at": first.get("would_open_at"),
                "would_recover_at": first.get("would_recover_at"),
                "effective_threshold": float(target["effective_threshold"]),
                "effective_duration_seconds": int(target["effective_duration_seconds"]),
                "effective_override": target["effective_override"],
                "what_if": {
                    key: value
                    for key, value in {
                        "threshold": threshold,
                        "duration_seconds": duration_seconds,
                    }.items()
                    if value is not None
                },
                "sample_count": len(events_by_equipment[equipment_id]),
                "non_trigger_reason": (
                    None
                    if occurrences
                    else _non_trigger_reason(
                        len(events_by_equipment[equipment_id]), outcomes, reasons
                    )
                ),
                "occurrences": occurrences,
            }
        )

    triggered = sum(result["would_trigger"] for result in results)
    return {
        "simulation": True,
        "persistence": "READ_ONLY",
        "rule": {
            "rule_id": rule_id,
            "rule_key": draft.rule_key,
            "version_id": version_id,
            "version": version,
        },
        "historical_window": {"start": start.isoformat(), "end": end.isoformat()},
        "what_if": {
            key: value
            for key, value in {
                "threshold": threshold,
                "duration_seconds": duration_seconds,
            }.items()
            if value is not None
        },
        "matched_target_count": len(results),
        "excluded_target_count": len(preview["excluded"]),
        "triggered_count": triggered,
        "not_triggered_count": len(results) - triggered,
        "results": results,
        "excluded": preview["excluded"],
    }
