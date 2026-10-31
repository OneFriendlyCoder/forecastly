"""Send simulated events into Kafka in time order, as if they were happening live."""
import argparse
import json
import time
from pathlib import Path

import pandas as pd
from confluent_kafka import Producer

ROOT = Path(__file__).resolve().parents[2]
SECONDS_PER_SIM_DAY = 86400


def load_events(path, limit=None):
    table = pd.read_parquet(path)  # already in time order, with each deal's order kept
    return table.head(limit) if limit else table


def to_message(row):
    event = row._asdict()
    event["actor"] = json.loads(event["actor"])
    event["payload"] = json.loads(event["payload"])
    return json.dumps(event, separators=(",", ":"))


def replay(table, brokers, topic, seconds_per_day=1.0):
    """Send every row, then return (sent, elapsed seconds). seconds_per_day=0 means no pauses."""
    # murmur2 matches the default partitioner of Java and Go Kafka clients.
    producer = Producer({"bootstrap.servers": brokers, "enable.idempotence": True, "linger.ms": 20,
                         "partitioner": "murmur2_random", "compression.type": "lz4"})
    failures = []

    def on_delivery(err, _msg):
        if err:
            failures.append(err)

    times = pd.to_datetime(table["occurred_at"], utc=True)
    offsets = ((times - times.iloc[0]).dt.total_seconds() / SECONDS_PER_SIM_DAY * seconds_per_day).tolist()
    started = time.monotonic()
    for row, offset in zip(table.itertuples(index=False), offsets):
        wait = started + offset - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        while True:
            try:
                producer.produce(topic, key=row.deal_id, value=to_message(row), on_delivery=on_delivery)
                break
            except BufferError:  # local queue is full, so let the broker catch up
                producer.poll(0.1)
        producer.poll(0)
    remaining = producer.flush(30)
    if failures or remaining:
        raise RuntimeError(f"{len(failures)} failed, {remaining} undelivered: {failures[:3]}")
    return len(table), time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/simulated/events.parquet")
    parser.add_argument("--brokers", default="localhost:19092")
    parser.add_argument("--topic", default="activity.events")
    parser.add_argument("--seconds-per-day", type=float, default=1.0, help="real seconds per simulated day")
    parser.add_argument("--fast", action="store_true", help="send with no pauses")
    parser.add_argument("--limit", type=int, help="only send the first N events")
    args = parser.parse_args()
    speed = 0 if args.fast else args.seconds_per_day
    sent, elapsed = replay(load_events(args.input, args.limit), args.brokers, args.topic, speed)
    print(f"sent {sent} events in {elapsed:.1f}s ({sent / elapsed:.0f} events/s)")


if __name__ == "__main__":
    main()
