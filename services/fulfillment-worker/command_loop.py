"""Acknowledge only the command whose database work has completed."""
import time
from kafka import TopicPartition
from kafka.structs import OffsetAndMetadata


def consume_commands(consumer, process_message, sleep=time.sleep):
    try:
        for message in consumer:
            # Bound retries below Kafka's poll interval. Exhaustion stops the
            # process without acknowledging, allowing restart to replay safely.
            for attempt in range(5):
                try:
                    process_message(message)
                    consumer.commit({
                        TopicPartition(message.topic, message.partition):
                        OffsetAndMetadata(message.offset + 1, "")
                    })
                    break
                except Exception:
                    if attempt == 4:
                        raise
                    sleep(1)
    finally:
        consumer.close(autocommit=False)
