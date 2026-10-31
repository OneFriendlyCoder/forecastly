"""Send simulated events into Kafka in time order, as if they were happening live."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from confluent_kafka import Producer

ROOT = Path(__file__).resolve().parents[2]
SECONDS_PER_SIM_DAY = 86400


DEFAULT_FAULTS = {"seed": 7, "duplicates": 0.02, "late": 0.02, "broken": 0.001, "late_window": 5000}


def load_events(path, limit=None):
    table = pd.read_parquet(path)  # already in time order, with each deal's order kept
    return table.head(limit) if limit else table


def to_message(row):
    event = row._asdict()
    event["actor"] = json.loads(event["actor"])
    event["payload"] = json.loads(event["payload"])
    return json.dumps(event, separators=(",", ":"))


def corrupt(value, rng):
    """A broken copy of a message: either cut short, or valid JSON that breaks the contract."""
    if rng.random() < 0.5:
        return value[: len(value) // 2]
    return value.replace('"schema_version":1', '"schema_version":99')


def plan_messages(table, offsets, faults=None):
    """Return (messages, counts). Each message is (key, value, offset), in send order.

    Every real event is still sent at least once, so faults must not change the final state.
    """
    planned, counts = [], {"duplicates": 0, "late": 0, "broken": 0}
    rng = np.random.default_rng(faults["seed"]) if faults else None
    for position, (row, offset) in enumerate(zip(table.itertuples(index=False), offsets)):
        value = to_message(row)
        send_at = position
        if faults and rng.random() < faults["late"]:
            send_at += int(rng.integers(100, faults["late_window"]))
            counts["late"] += 1
        planned.append((send_at, row.deal_id, value, offset))
        if faults and rng.random() < faults["duplicates"]:
            planned.append((position + int(rng.integers(1, faults["late_window"])), row.deal_id, value, offset))
            counts["duplicates"] += 1
        if faults and rng.random() < faults["broken"]:
            planned.append((position, row.deal_id, corrupt(value, rng), offset))
            counts["broken"] += 1
    planned.sort(key=lambda message: message[0])  # stable, so untouched events keep their order
    return [message[1:] for message in planned], counts


def replay(table, brokers, topic, seconds_per_day=1.0, faults=None):
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
    messages, counts = plan_messages(table, offsets, faults)
    if faults:
        print(f"injecting {counts}")
    started = time.monotonic()
    for key, value, offset in messages:
        wait = started + offset - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        while True:
            try:
                producer.produce(topic, key=key, value=value, on_delivery=on_delivery)
                break
            except BufferError:  # local queue is full, so let the broker catch up
                producer.poll(0.1)
        producer.poll(0)
    remaining = producer.flush(30)
    if failures or remaining:
        raise RuntimeError(f"{len(failures)} failed, {remaining} undelivered: {failures[:3]}")
    return len(messages), time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/simulated/events.parquet")
    parser.add_argument("--brokers", default="localhost:19092")
    parser.add_argument("--topic", default="activity.events")
    parser.add_argument("--seconds-per-day", type=float, default=1.0, help="real seconds per simulated day")
    parser.add_argument("--fast", action="store_true", help="send with no pauses")
    parser.add_argument("--limit", type=int, help="only send the first N events")
    parser.add_argument("--faults", action="store_true", help="inject duplicate, late and broken events")
    args = parser.parse_args()
    speed = 0 if args.fast else args.seconds_per_day
    faults = DEFAULT_FAULTS if args.faults else None
    sent, elapsed = replay(load_events(args.input, args.limit), args.brokers, args.topic, speed, faults)
    print(f"sent {sent} events in {elapsed:.1f}s ({sent / elapsed:.0f} events/s)")


if __name__ == "__main__":
    main()
