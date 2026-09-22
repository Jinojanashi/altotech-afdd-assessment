import argparse
import asyncio
import logging

from aiokafka import AIOKafkaConsumer, TopicPartition
from sqlalchemy import create_engine

from afdd.settings import get_settings
from afdd.telemetry import process_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-messages", type=int)
    parser.add_argument("--idle-timeout", type=float, default=0)
    args = parser.parse_args()
    settings = get_settings()
    engine = create_engine(settings.database_url)
    consumer = AIOKafkaConsumer(
        settings.telemetry_topic,
        bootstrap_servers=settings.broker_list,
        group_id=settings.consumer_group_ingestion,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    processed = 0
    counts = {"ACCEPTED": 0, "DUPLICATE": 0, "REJECTED": 0}
    try:
        while not args.max_messages or processed < args.max_messages:
            batch = await consumer.getmany(
                timeout_ms=int((args.idle_timeout or 1) * 1000), max_records=500
            )
            if not batch:
                if args.idle_timeout:
                    break
                continue
            for records in batch.values():
                for message in records:
                    for attempt in range(3):
                        try:
                            result = process_payload(engine, message.value)
                            counts[result.status] += 1
                            count = counts[result.status]
                            noteworthy = (
                                result.status == "REJECTED" or count == 1 or count % 1000 == 0
                            )
                            log = logger.info if noteworthy else logger.debug
                            log(
                                "telemetry_ingestion status=%s count=%d event_id=%s observations=%d reason=%s",
                                result.status,
                                count,
                                result.event_id,
                                result.observations,
                                result.reason,
                            )
                            break
                        except Exception:
                            logger.exception("retryable_consumer_error attempt=%d", attempt + 1)
                            if attempt == 2:
                                raise
                            await asyncio.sleep(0.25 * (attempt + 1))
                    await consumer.commit(
                        {
                            TopicPartition(message.topic, message.partition): message.offset + 1,
                        }
                    )
                    processed += 1
    finally:
        await consumer.stop()
        engine.dispose()
    logger.info("telemetry_consumer_stopped processed=%d counts=%s", processed, counts)


if __name__ == "__main__":
    asyncio.run(main())
