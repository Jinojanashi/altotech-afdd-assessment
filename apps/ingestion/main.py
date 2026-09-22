import asyncio
import logging

from afdd.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logger.info(
        "Ingestion skeleton ready: brokers=%s topic=%s",
        settings.broker_list,
        settings.telemetry_topic,
    )
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())

