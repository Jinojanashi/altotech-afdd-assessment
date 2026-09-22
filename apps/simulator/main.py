import asyncio
import logging

from afdd.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logger.info(
        "Simulator skeleton ready: source=%s interval=%ss acceleration=%sx topic=%s",
        settings.simulator_source_dir,
        settings.simulator_interval_seconds,
        settings.simulator_acceleration_factor,
        settings.telemetry_topic,
    )
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())

