import asyncio
import logging

from afdd.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logger.info(
        "AFDD worker skeleton ready: brokers=%s topic=%s",
        settings.broker_list,
        settings.afdd_evaluation_topic,
    )
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())

