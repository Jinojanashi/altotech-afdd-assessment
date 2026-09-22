"""Run one real-model AI authoring trace without confirming or activating it."""

import argparse
import json

from sqlalchemy import create_engine

from afdd.ai_authoring import create_authoring_request
from afdd.settings import get_settings


def evidence_summary(result: dict) -> dict:
    """Return useful live-run evidence without dumping prompts or provider credentials."""

    preview = result.get("target_preview") or {}
    validation = result.get("validation_result")
    return {
        "request_id": result["id"],
        "provider": result["provider"],
        "model": result["model"],
        "state": result["state"],
        "model_calls": result["model_calls"],
        "retry_count": result["retry_count"],
        "latency_ms": result["latency_ms"],
        "interpreted_intent": result.get("interpreted_intent"),
        "validation_result": validation,
        "preview_summary": (
            {
                "matched_count": preview.get("matched_count"),
                "excluded_count": preview.get("excluded_count"),
                "matched_equipment_ids": [
                    item.get("equipment_id") for item in preview.get("matched", [])
                ],
            }
            if preview
            else None
        ),
        "workflow_states": [item.get("state") for item in result.get("state_trace", [])],
        "human_confirmed_at": result.get("human_confirmed_at"),
        "activation_result": result.get("activation_result"),
        "stop_reason": result.get("stop_reason"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        default=(
            "Create a Critical rule for office AHUs in Building A when supply air temperature "
            "differs from its setpoint by more than 3°C for 15 minutes while the AHU is running."
        ),
    )
    args = parser.parse_args()
    engine = create_engine(get_settings().database_url)
    try:
        result = create_authoring_request(engine, args.prompt)
        print(json.dumps(evidence_summary(result), indent=2, sort_keys=True))
        if result["human_confirmed_at"] is not None or result["activation_result"] is not None:
            raise RuntimeError("safety invariant violated: live demo must not confirm or activate")
        if result["state"] != "READY_FOR_REVIEW":
            raise SystemExit(
                f"Live model demo did not reach READY_FOR_REVIEW (state={result['state']})"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
