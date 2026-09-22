"""Separate AFDD worker with deterministic one-shot and polling modes."""

import argparse
import json
import logging
import time

from sqlalchemy import create_engine

from afdd.evaluator import evaluate_active_rules, reset_evaluation
from afdd.rules import ensure_default_rule
from afdd.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="evaluate accepted telemetry then exit")
    parser.add_argument("--reset", action="store_true", help="clear evaluation state and issues first")
    parser.add_argument(
        "--ensure-default-rule", action="store_true", help="idempotently create and activate the demo rule"
    )
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    engine = create_engine(get_settings().database_url)
    try:
        if args.ensure_default_rule:
            rule = ensure_default_rule(engine)
            logger.info(
                "default_rule_ready rule_id=%s version=%s", rule["id"], rule["active_version"]
            )
        if args.reset:
            reset_evaluation(engine)
        while True:
            results = evaluate_active_rules(engine)
            print(json.dumps(results, sort_keys=True))
            if args.once:
                return
            time.sleep(args.poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
