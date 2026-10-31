"""Needs `make up`. Run with: .venv/bin/python ml/simulator/test_replay.py"""
import json
import sys
import uuid
from pathlib import Path

import jsonschema
import pandas as pd
from confluent_kafka import Consumer, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic

sys.path.insert(0, str(Path(__file__).parent))
from replay import ROOT, load_events, replay

BROKERS = "localhost:19092"
SCHEMA = json.loads((ROOT / "schemas/event.v1.json").read_text())


def read_all(topic):
    consumer = Consumer({"bootstrap.servers": BROKERS, "group.id": uuid.uuid4().hex, "auto.offset.reset": "earliest",
                         "enable.partition.eof": True})
    consumer.subscribe([topic])
    messages, finished = [], set()
    while len(finished) < 6:
        msg = consumer.poll(30)
        assert msg is not None, "timed out reading from Kafka"
        if msg.error():
            assert msg.error().code() == KafkaError._PARTITION_EOF, msg.error()
            finished.add(msg.partition())
        else:
            messages.append(msg)
    consumer.close()
    return messages


def check_delivery(table, messages):
    assert len(messages) == len(table), "every event must arrive exactly once"
    events = [json.loads(m.value()) for m in messages]
    assert {e["event_id"] for e in events} == set(table["event_id"]), "the same events must arrive"

    validator = jsonschema.Draft202012Validator(SCHEMA)
    for event in events[:5000]:
        validator.validate(event)

    expected, seen, partitions = {}, {}, {}
    for row in table[["deal_id", "event_id"]].itertuples(index=False):
        expected.setdefault(row.deal_id, []).append(row.event_id)
    for msg, event in zip(messages, events):
        assert msg.key().decode() == event["deal_id"]
        seen.setdefault(event["deal_id"], []).append(event["event_id"])
        partitions.setdefault(event["deal_id"], set()).add(msg.partition())
    assert seen == expected, "each deal's events must arrive in order"
    assert all(len(p) == 1 for p in partitions.values()), "each deal must stay on one partition"
    return len({p for parts in partitions.values() for p in parts})


def main():
    admin = AdminClient({"bootstrap.servers": BROKERS})
    topics = [f"replay.test.{uuid.uuid4().hex[:8]}" for _ in range(2)]
    for future in admin.create_topics([NewTopic(t, num_partitions=6, replication_factor=1) for t in topics]).values():
        future.result()
    try:
        table = load_events(ROOT / "data/simulated/events.parquet")
        sent, elapsed = replay(table, BROKERS, topics[0], seconds_per_day=0)
        used = check_delivery(table, read_all(topics[0]))
        print(f"ok: {sent} events in order across {used} partitions, {sent / elapsed:.0f} events/s")

        sample = table.head(2000)
        spd = 0.5
        times = pd.to_datetime(sample["occurred_at"])
        span_days = (times.iloc[-1] - times.iloc[0]).total_seconds() / 86400
        _, paced = replay(sample, BROKERS, topics[1], seconds_per_day=spd)
        assert span_days * spd <= paced < span_days * spd + 5, f"took {paced:.1f}s for {span_days:.1f} simulated days"
        print(f"ok: {span_days:.1f} simulated days took {paced:.1f}s at {spd}s per day")
    finally:
        for future in admin.delete_topics(topics).values():
            future.result()


if __name__ == "__main__":
    main()
