"""Run one real-model AI authoring trace without confirming or activating it."""

import argparse
import json

from sqlalchemy import create_engine

from afdd.ai_authoring import create_authoring_request
from afdd.settings import get_settings


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
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["state"] == "ACTIVATED":
            raise RuntimeError("safety invariant violated: demo must never activate")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
