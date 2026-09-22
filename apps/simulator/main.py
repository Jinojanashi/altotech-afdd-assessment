import argparse
import asyncio
import logging
from pathlib import Path

from aiokafka import AIOKafkaProducer

from afdd.settings import get_settings
from afdd.simulator import source_events

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay-seconds", type=float)
    parser.add_argument("--max-events", type=int)
    args = parser.parse_args()
    settings = get_settings()
    delay = args.delay_seconds
    if delay is None:
        delay = settings.simulator_interval_seconds / settings.simulator_acceleration_factor
    producer = AIOKafkaProducer(bootstrap_servers=settings.broker_list, acks="all")
    await producer.start()
    published = 0
    try:
        for event in source_events(Path(settings.simulator_source_dir)):
            await producer.send_and_wait(
                settings.telemetry_topic,
                event.model_dump_json().encode(),
                key=event.equipment_id.encode(),
            )
            published += 1
            if args.max_events and published >= args.max_events:
                break
            if delay:
                await asyncio.sleep(delay)
    finally:
        await producer.stop()
    logger.info("telemetry_replay_complete published=%d topic=%s", published, settings.telemetry_topic)


if __name__ == "__main__":
    asyncio.run(main())
