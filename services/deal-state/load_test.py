"""Measure the pipeline under load. Run with: make load-test

Each scenario starts empty. Latency runs from entering Kafka to being stored in Postgres, and
event-to-score runs on to the saved score. The timestamps come from two clocks: the Mac's and the
Docker VM's.
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "ml/simulator"))
sys.path.insert(0, str(ROOT / "services/deal-state"))
from confluent_kafka import Consumer, TopicPartition
from replay import load_events, replay, scale_events
from seed_deals import seed
from test_e2e import BROKERS, scoring_backlog, sql

COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy/docker-compose.yml")]
TOPIC = "activity.events"
LATENCY = """SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY s)::numeric, 3) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY s)::numeric, 3) AS p95,
       round(percentile_cont(0.99) WITHIN GROUP (ORDER BY s)::numeric, 3) AS p99,
       round(max(s)::numeric, 3) AS worst
FROM (SELECT extract(epoch FROM received_at - published_at) AS s FROM events) t"""


EVENT_TO_SCORE = LATENCY.replace("received_at - published_at", "scored_at - event_published_at").replace(
    "FROM events t", "FROM deal_scores t").replace("FROM events)", "FROM deal_scores)")


def backlog(consumer):
    """Messages in Kafka minus events stored. Exact here because load runs have no duplicates."""
    in_kafka = sum(consumer.get_watermark_offsets(TopicPartition(TOPIC, p), timeout=5)[1] for p in range(6))
    return in_kafka - sql("SELECT count(*) AS n FROM events")["n"].iloc[0]


def fresh_stack(consumers, copies):
    subprocess.run(["make", "reset", "up"], cwd=ROOT, check=True, capture_output=True)
    seed(copies)
    if consumers > 1:
        subprocess.run([*COMPOSE, "up", "-d", "--scale", f"deal-state={consumers}", "deal-state"],
                       check=True, capture_output=True)
        time.sleep(15)  # let the group settle before measuring


def container_cpu():
    out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}}"],
                         check=True, capture_output=True, text=True).stdout
    return {line.split()[0].replace("pipeline-pulse-", ""): line.split()[1]
            for line in out.splitlines() if "pipeline-pulse" in line}


def run(name, table, consumers=1, copies=1, **replay_args):
    fresh_stack(consumers, copies)
    result = {}

    def send():
        result["sent"], result["send_seconds"] = replay(table, BROKERS, TOPIC, **replay_args)

    watcher = Consumer({"bootstrap.servers": BROKERS, "group.id": "load-test-watcher"})
    sender = threading.Thread(target=send)
    started = time.monotonic()
    sender.start()
    peak, cpu, clear_after_peak = 0, None, None
    while True:
        remaining = backlog(watcher)
        if remaining > peak:
            peak, clear_after_peak = remaining, time.monotonic()
        if cpu is None and time.monotonic() - started > 8:
            cpu = container_cpu()
        if not sender.is_alive() and remaining == 0:
            break
        assert time.monotonic() - started < 900, "did not catch up"
        time.sleep(0.5)
    finished = time.monotonic()
    while scoring_backlog() > 0:
        assert time.monotonic() - started < 1800, "scoring did not catch up"
        time.sleep(0.5)
    scored = time.monotonic()
    sender.join()
    watcher.close()

    stored = sql("SELECT count(*) AS n FROM events")["n"].iloc[0]
    assert stored == result["sent"], f"{stored} stored of {result['sent']} sent"
    summary = {
        "scenario": name,
        "consumers": consumers,
        "events": int(stored),
        "total_seconds": round(finished - started, 1),
        "events_per_second": round(stored / (finished - started)),
        "peak_backlog": int(peak),
        "backlog_clear_seconds": round(finished - clear_after_peak, 1) if clear_after_peak else 0,
        "scoring_finished_seconds": round(scored - started, 1),
        "scores": int(sql("SELECT count(*) AS n FROM deal_scores")["n"].iloc[0]),
        "latency_seconds": sql(LATENCY).iloc[0].to_dict(),
        "event_to_score_seconds": sql(EVENT_TO_SCORE).iloc[0].to_dict(),
        "cpu_during_run": cpu,
    }
    print(json.dumps(summary), flush=True)
    return summary


def main():
    base = load_events(ROOT / "data/simulated/events.parquet")
    scaled = scale_events(base, 3)
    results = [
        run("target rate, 1M events/hour", base, profile=[(60, 280)]),
        run("as fast as possible", scaled, copies=3, seconds_per_day=0),
        run("as fast as possible", scaled, consumers=3, copies=3, seconds_per_day=0),
        run("burst", scaled, copies=3, profile=[(30, 2000), (10, 50000), (60, 2000)]),
    ]
    (ROOT / "data/load_test_results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
