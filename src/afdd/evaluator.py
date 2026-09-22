"""Deterministic observed-time AFDD evaluation and issue lifecycle."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from afdd.events import TelemetryEvent
from afdd.rules import RuleDraft, draft_for_version, preview_draft


@dataclass(frozen=True)
class InputReading:
    value: float | str | bool
    observed_at: datetime
    quality: str = "GOOD"


@dataclass(frozen=True)
class EvaluationSample:
    equipment_id: str
    observed_at: datetime
    readings: dict[str, InputReading]
    event_id: str | None = None


@dataclass(frozen=True)
class EvaluationTransition:
    """Pure state-machine output shared by live evaluation and read-only simulations."""

    outcome: str
    state: str
    last_observed_at: datetime | None
    qualifying_started_at: datetime | None
    qualifying_evidence: list[dict[str, Any]]
    evidence: dict[str, Any] | None = None
    issue_action: str | None = None
    issue_started_at: datetime | None = None
    issue_reason: str | None = None
    persist_state: bool = True


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def sample_from_event(event: TelemetryEvent) -> EvaluationSample:
    observed_at = _as_utc(event.observed_at)
    return EvaluationSample(
        equipment_id=event.equipment_id,
        observed_at=observed_at,
        readings={
            measurement.measurement: InputReading(measurement.value, observed_at)
            for measurement in event.measurements
        },
        event_id=str(event.event_id),
    )


def _sample_evidence(
    sample: EvaluationSample, required: list[str], freshness_seconds: int
) -> tuple[dict[str, Any], bool]:
    readings: dict[str, Any] = {}
    trustworthy = True
    for name in required:
        reading = sample.readings.get(name)
        if reading is None:
            readings[name] = {"present": False, "fresh": False, "quality": "MISSING"}
            trustworthy = False
            continue
        age = (sample.observed_at - _as_utc(reading.observed_at)).total_seconds()
        fresh = 0 <= age <= freshness_seconds
        valid = reading.quality == "GOOD" and fresh
        readings[name] = {
            "present": True,
            "value": reading.value,
            "observed_at": _as_utc(reading.observed_at).isoformat(),
            "quality": reading.quality,
            "age_seconds": age,
            "fresh": fresh,
        }
        trustworthy = trustworthy and valid
    difference = None
    if trustworthy:
        try:
            difference = abs(float(sample.readings["SAT"].value) - float(sample.readings["SAT_SP"].value))
        except (KeyError, TypeError, ValueError):
            trustworthy = False
    return {
        "event_id": sample.event_id,
        "observed_at": sample.observed_at.isoformat(),
        "readings": readings,
        "absolute_difference": difference,
        "trustworthy": trustworthy,
    }, trustworthy


def _load_state(connection: Any, version_id: str, equipment_id: str) -> dict[str, Any]:
    row = connection.execute(
        text(
            """
            SELECT state, last_observed_at, qualifying_started_at, qualifying_evidence
            FROM afdd_evaluation_states
            WHERE rule_version_id=CAST(:version_id AS uuid)
              AND equipment_id=CAST(:equipment_id AS uuid)
            FOR UPDATE
            """
        ),
        {"version_id": version_id, "equipment_id": equipment_id},
    ).mappings().first()
    return dict(row) if row else {
        "state": "NORMAL",
        "last_observed_at": None,
        "qualifying_started_at": None,
        "qualifying_evidence": [],
    }


def _save_state(
    connection: Any,
    version_id: str,
    equipment_id: str,
    state: str,
    observed_at: datetime,
    qualifying_started_at: datetime | None,
    evidence: list[dict[str, Any]],
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO afdd_evaluation_states
                (rule_version_id,equipment_id,state,last_observed_at,
                 qualifying_started_at,qualifying_evidence)
            VALUES (CAST(:version_id AS uuid),CAST(:equipment_id AS uuid),:state,:observed,
                    :started,CAST(:evidence AS jsonb))
            ON CONFLICT (rule_version_id,equipment_id) DO UPDATE SET
                state=EXCLUDED.state, last_observed_at=EXCLUDED.last_observed_at,
                qualifying_started_at=EXCLUDED.qualifying_started_at,
                qualifying_evidence=EXCLUDED.qualifying_evidence, updated_at=now()
            """
        ),
        {
            "version_id": version_id,
            "equipment_id": equipment_id,
            "state": state,
            "observed": observed_at,
            "started": qualifying_started_at,
            "evidence": json.dumps(evidence, sort_keys=True),
        },
    )


def _open_issue(
    connection: Any,
    *,
    rule_id: str,
    version_id: str,
    version: int,
    draft: RuleDraft,
    target: dict[str, Any],
    started_at: datetime,
    opened_at: datetime,
    threshold: float,
    duration_seconds: int,
    window: list[dict[str, Any]],
) -> str:
    occurrence = connection.execute(
        text(
            """
            SELECT coalesce(max(occurrence),0)+1 FROM afdd_issues
            WHERE rule_version_id=CAST(:version_id AS uuid)
              AND equipment_id=CAST(:equipment_id AS uuid)
            """
        ),
        {"version_id": version_id, "equipment_id": target["canonical_equipment_id"]},
    ).scalar_one()
    evidence = {
        "rule": {
            "rule_id": rule_id,
            "rule_key": draft.rule_key,
            "version": version,
            "severity": draft.severity,
            "logic": draft.logic.model_dump(mode="json"),
        },
        "equipment": {
            "canonical_equipment_id": target["canonical_equipment_id"],
            "equipment_id": target["equipment_id"],
        },
        "topology": {
            "property_id": target["property_id"],
            "floor_id": target["floor_id"],
            "installation_location": target["installation_location"],
            "served_zone": target["served_zone"],
            "potentially_affected_rooms": target["potentially_affected_rooms"],
        },
        "effective_config": {
            "threshold": threshold,
            "duration_seconds": duration_seconds,
            "freshness_seconds": draft.logic.freshness_seconds,
            "override": target["effective_override"],
        },
        "qualifying_started_at": started_at.isoformat(),
        "triggered_at": opened_at.isoformat(),
        "samples": window,
    }
    return str(
        connection.execute(
            text(
                """
                INSERT INTO afdd_issues
                    (rule_id,rule_version_id,equipment_id,occurrence,severity,status,
                     qualifying_started_at,opened_at,threshold,duration_seconds,
                     effective_override,evidence)
                VALUES (CAST(:rule_id AS uuid),CAST(:version_id AS uuid),
                        CAST(:equipment_id AS uuid),:occurrence,:severity,'OPEN',
                        :started,:opened,:threshold,:duration,CAST(:override AS jsonb),
                        CAST(:evidence AS jsonb))
                RETURNING id
                """
            ),
            {
                "rule_id": rule_id,
                "version_id": version_id,
                "equipment_id": target["canonical_equipment_id"],
                "occurrence": occurrence,
                "severity": draft.severity,
                "started": started_at,
                "opened": opened_at,
                "threshold": threshold,
                "duration": duration_seconds,
                "override": json.dumps(target["effective_override"] or {}, sort_keys=True),
                "evidence": json.dumps(evidence, sort_keys=True),
            },
        ).scalar_one()
    )


def _close_issue(
    connection: Any,
    version_id: str,
    equipment_id: str,
    observed_at: datetime,
    reason: str,
    sample_evidence: dict[str, Any],
) -> None:
    issue = connection.execute(
        text(
            """
            SELECT id,evidence FROM afdd_issues
            WHERE rule_version_id=CAST(:version_id AS uuid)
              AND equipment_id=CAST(:equipment_id AS uuid) AND status='OPEN'
            FOR UPDATE
            """
        ),
        {"version_id": version_id, "equipment_id": equipment_id},
    ).mappings().first()
    if not issue:
        return
    evidence = dict(issue["evidence"])
    evidence["recovery"] = {
        "closed_at": observed_at.isoformat(),
        "reason": reason,
        "sample": sample_evidence,
    }
    connection.execute(
        text(
            """
            UPDATE afdd_issues SET status='CLOSED',closed_at=:closed,evidence=CAST(:evidence AS jsonb)
            WHERE id=:issue_id
            """
        ),
        {"closed": observed_at, "evidence": json.dumps(evidence, sort_keys=True), "issue_id": issue["id"]},
    )


def evaluate_transition(
    *,
    state: dict[str, Any],
    draft: RuleDraft,
    target: dict[str, Any],
    sample: EvaluationSample,
) -> EvaluationTransition:
    """Advance the AFDD state machine without reading or writing persistent state."""

    sample = EvaluationSample(
        sample.equipment_id, _as_utc(sample.observed_at), sample.readings, sample.event_id
    )
    threshold = float(target["effective_threshold"])
    duration_seconds = int(target["effective_duration_seconds"])
    freshness_seconds = draft.logic.freshness_seconds
    evidence, trustworthy = _sample_evidence(
        sample, list(draft.scope.required_points), freshness_seconds
    )
    last_observed = state.get("last_observed_at")
    if last_observed is not None and sample.observed_at <= _as_utc(last_observed):
        return EvaluationTransition(
            outcome="IGNORED_LATE_OR_EQUAL",
            state=state["state"],
            last_observed_at=last_observed,
            qualifying_started_at=state.get("qualifying_started_at"),
            qualifying_evidence=list(state.get("qualifying_evidence") or []),
            persist_state=False,
        )

    current_state = state["state"]
    started = state.get("qualifying_started_at")
    window = list(state.get("qualifying_evidence") or [])
    if last_observed is not None:
        gap = (sample.observed_at - _as_utc(last_observed)).total_seconds()
        if gap > freshness_seconds and current_state == "QUALIFYING":
            current_state, started, window = "NORMAL", None, []

    if not trustworthy:
        return EvaluationTransition(
            outcome="UNTRUSTWORTHY_INPUT",
            state="OPEN" if current_state == "OPEN" else "NORMAL",
            last_observed_at=sample.observed_at,
            qualifying_started_at=None,
            qualifying_evidence=[],
            evidence=evidence,
            issue_reason="UNTRUSTWORTHY_INPUT",
        )

    run_on = str(sample.readings["RUN"].value).upper() == "ON"
    difference = float(evidence["absolute_difference"])
    qualifies = run_on and difference > threshold
    if not qualifies:
        reason = "AHU_OFF" if not run_on else "CONDITION_CLEARED"
        return EvaluationTransition(
            outcome="CLOSED" if current_state == "OPEN" else "NORMAL",
            state="NORMAL",
            last_observed_at=sample.observed_at,
            qualifying_started_at=None,
            qualifying_evidence=[],
            evidence=evidence,
            issue_action="CLOSE" if current_state == "OPEN" else None,
            issue_reason=reason,
        )

    if current_state == "OPEN":
        return EvaluationTransition(
            outcome="REMAINS_OPEN",
            state="OPEN",
            last_observed_at=sample.observed_at,
            qualifying_started_at=None,
            qualifying_evidence=[],
            evidence=evidence,
        )

    if current_state == "NORMAL" or started is None:
        started = sample.observed_at
        window = [evidence]
    else:
        started = _as_utc(started)
        window.append(evidence)
    if (sample.observed_at - started).total_seconds() >= duration_seconds:
        return EvaluationTransition(
            outcome="OPENED",
            state="OPEN",
            last_observed_at=sample.observed_at,
            qualifying_started_at=None,
            qualifying_evidence=[],
            evidence=evidence,
            issue_action="OPEN",
            issue_started_at=started,
        )

    return EvaluationTransition(
        outcome="QUALIFYING",
        state="QUALIFYING",
        last_observed_at=sample.observed_at,
        qualifying_started_at=started,
        qualifying_evidence=window,
        evidence=evidence,
    )


def evaluate_sample(
    engine: Engine,
    *,
    rule_id: str,
    version_id: str,
    version: int,
    draft: RuleDraft,
    target: dict[str, Any],
    sample: EvaluationSample,
) -> str:
    """Advance one rule/equipment state; returns a traceable transition outcome."""
    with engine.begin() as connection:
        state = _load_state(connection, version_id, target["canonical_equipment_id"])
        transition = evaluate_transition(state=state, draft=draft, target=target, sample=sample)
        if transition.issue_action == "OPEN":
            _open_issue(
                connection,
                rule_id=rule_id,
                version_id=version_id,
                version=version,
                draft=draft,
                target=target,
                started_at=transition.issue_started_at,
                opened_at=transition.last_observed_at,
                threshold=float(target["effective_threshold"]),
                duration_seconds=int(target["effective_duration_seconds"]),
                window=list(state.get("qualifying_evidence") or []) + [transition.evidence],
            )
        elif transition.issue_action == "CLOSE":
            _close_issue(
                connection,
                version_id,
                target["canonical_equipment_id"],
                transition.last_observed_at,
                transition.issue_reason,
                transition.evidence,
            )
        if transition.persist_state:
            _save_state(
                connection,
                version_id,
                target["canonical_equipment_id"],
                transition.state,
                transition.last_observed_at,
                transition.qualifying_started_at,
                transition.qualifying_evidence,
            )
        return transition.outcome


def evaluate_rule_version(engine: Engine, rule_id: str, version: int) -> dict[str, Any]:
    version_id, draft = draft_for_version(engine, rule_id, version)
    preview = preview_draft(engine, draft)
    targets = {target["equipment_id"]: target for target in preview["matched"]}
    outcomes: dict[str, int] = {}
    if targets:
        with engine.connect() as connection:
            payloads = connection.execute(
                text(
                    """
                    SELECT payload FROM ingestion_events
                    WHERE processing_status='ACCEPTED'
                      AND equipment_source_id=ANY(CAST(:equipment_ids AS text[]))
                    ORDER BY received_at,event_id
                    """
                ),
                {"equipment_ids": sorted(targets)},
            ).scalars().all()
        for payload in payloads:
            event = TelemetryEvent.model_validate(payload)
            outcome = evaluate_sample(
                engine,
                rule_id=rule_id,
                version_id=version_id,
                version=version,
                draft=draft,
                target=targets[event.equipment_id],
                sample=sample_from_event(event),
            )
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
    with engine.connect() as connection:
        issue_counts = connection.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE status='OPEN') AS open,
                       count(*) FILTER (WHERE status='CLOSED') AS closed
                FROM afdd_issues WHERE rule_version_id=CAST(:version_id AS uuid)
                """
            ),
            {"version_id": version_id},
        ).mappings().one()
    return {
        "rule_id": rule_id,
        "version": version,
        "targets": len(targets),
        "exclusions": len(preview["excluded"]),
        "outcomes": outcomes,
        "issues": dict(issue_counts),
    }


def evaluate_active_rules(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        active = connection.execute(
            text(
                """
                SELECT rule.id, version.version FROM afdd_rules rule
                JOIN afdd_rule_versions version ON version.id=rule.active_version_id
                WHERE rule.enabled=true ORDER BY rule.rule_key
                """
            )
        ).all()
    return [evaluate_rule_version(engine, str(rule.id), rule.version) for rule in active]


def reset_evaluation(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE afdd_evaluation_states,afdd_issues"))


def _issue_record(row: Any) -> dict[str, Any]:
    result = dict(row._mapping)
    return {
        key: value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, UUID) else value
        for key, value in result.items()
    }


def list_issues(engine: Engine, status: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT issue.id,rule.rule_key,version.version AS rule_version,
               equipment.source_id AS equipment_id,issue.occurrence,issue.severity,
               issue.status,issue.qualifying_started_at,issue.opened_at,issue.closed_at
        FROM afdd_issues issue
        JOIN afdd_rules rule ON rule.id=issue.rule_id
        JOIN afdd_rule_versions version ON version.id=issue.rule_version_id
        JOIN ontology_entities equipment ON equipment.id=issue.equipment_id
    """
    params: dict[str, Any] = {}
    if status:
        query += " WHERE issue.status=:status"
        params["status"] = status
    query += " ORDER BY issue.opened_at,equipment.source_id,issue.occurrence"
    with engine.connect() as connection:
        return [_issue_record(row) for row in connection.execute(text(query), params)]


def get_issue(engine: Engine, issue_id: str) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT issue.*,rule.rule_key,version.version AS rule_version,
                       equipment.source_id AS equipment_source_id
                FROM afdd_issues issue
                JOIN afdd_rules rule ON rule.id=issue.rule_id
                JOIN afdd_rule_versions version ON version.id=issue.rule_version_id
                JOIN ontology_entities equipment ON equipment.id=issue.equipment_id
                WHERE issue.id=CAST(:issue_id AS uuid)
                """
            ),
            {"issue_id": issue_id},
        ).first()
        return _issue_record(row) if row else None
