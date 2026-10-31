"""End-to-end check against the running stack. Run with: make test-e2e

Replays every event, replays them all again, then sends broken events. The deal
records must match the simulator's file exactly after each stage.
"""
import io
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
from confluent_kafka import Consumer, Producer, TopicPartition

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml/simulator"))
from replay import load_events, replay

BROKERS = "localhost:19092"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy/docker-compose.yml"), "exec", "-T"]
TYPES = ["email_sent", "email_replied", "meeting_held", "meeting_no_show", "contact_added",
         "close_date_changed", "stage_changed", "deal_closed"]
BROKEN = [b"{oops", b'{"event_id":"not-a-uuid"}', b"", b'{"event_type":"email_sent","deal_id":"x"}']


def sql(query):
    copy = f"COPY ({query}) TO STDOUT WITH CSV HEADER"
    out = subprocess.run([*COMPOSE, "postgres", "psql", "-U", "pulse", "-d", "pipeline_pulse", "-c", copy],
                         check=True, capture_output=True, text=True).stdout
    return pd.read_csv(io.StringIO(out))


def lag():
    out = subprocess.run([*COMPOSE, "redpanda", "rpk", "group", "describe", "deal-state"],
                         check=True, capture_output=True, text=True).stdout
    fields = dict(line.split(maxsplit=1) for line in out.splitlines() if len(line.split()) == 2)
    if fields.get("STATE") != "Stable":  # lag reads 0 during a rebalance, which means nothing
        return None
    return int(fields["TOTAL-LAG"].replace(",", ""))


def wait_until_caught_up(timeout=600):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if lag() == 0:
            return time.monotonic() - started
        time.sleep(1)
    raise AssertionError("consumer did not catch up")


def scoring_backlog():
    """Updates not yet scored. Reads committed offsets, because rpk's lag is 0 before the first commit."""
    consumer = Consumer({"bootstrap.servers": BROKERS, "group.id": "scoring"})
    partitions = [TopicPartition("deal.features", p) for p in range(6)]
    committed = consumer.committed(partitions, timeout=10)
    remaining = sum(consumer.get_watermark_offsets(p, timeout=10)[1] - max(p.offset, 0) for p in committed)
    consumer.close()
    return remaining


def wait_until_scored(timeout=600):
    wait_until_caught_up(timeout)
    deadline = time.monotonic() + timeout
    while scoring_backlog() > 0:
        assert time.monotonic() < deadline, "scoring did not catch up"
        time.sleep(1)


def check_matches(expected):
    actual = sql(f"SELECT deal_id, {', '.join(TYPES)} FROM deal_health").set_index("deal_id").sort_index()
    pd.testing.assert_frame_equal(actual[TYPES], expected[TYPES], check_dtype=False, check_names=False)
    stored = sql("SELECT count(*) AS n FROM events")["n"].iloc[0]
    assert stored == int(expected.to_numpy().sum()), f"{stored} events stored"


def read_dlq(count):
    consumer = Consumer({"bootstrap.servers": BROKERS, "group.id": f"check-{time.time()}", "auto.offset.reset": "earliest"})
    consumer.subscribe(["activity.events.dlq"])
    values = []
    deadline = time.monotonic() + 15
    while len(values) < count and time.monotonic() < deadline:
        msg = consumer.poll(1)
        if msg is not None and not msg.error():
            values.append(msg.value() or b"")
    consumer.close()
    return values


def main():
    table = load_events(ROOT / "data/simulated/events.parquet")
    expected = table.pivot_table(index="deal_id", columns="event_type", aggfunc="size", fill_value=0)
    expected = expected.reindex(columns=TYPES, fill_value=0).sort_index()

    sent, send_time = replay(table, BROKERS, "activity.events", seconds_per_day=0)
    wait = wait_until_caught_up()
    check_matches(expected)
    print(f"ok: first pass, {sent} events, processed within {send_time + wait:.0f}s ({sent / (send_time + wait):.0f} events/s)")

    replay(table, BROKERS, "activity.events", seconds_per_day=0)
    wait_until_caught_up()
    check_matches(expected)
    print("ok: second pass changed nothing")

    producer = Producer({"bootstrap.servers": BROKERS})
    for value in BROKEN:
        producer.produce("activity.events", key="broken", value=value)
    producer.flush(10)
    wait_until_caught_up()
    check_matches(expected)
    assert sorted(read_dlq(len(BROKEN))) == sorted(BROKEN), "broken events must reach the dead-letter topic"
    print(f"ok: {len(BROKEN)} broken events went to the dead-letter topic")


if __name__ == "__main__":
    main()
