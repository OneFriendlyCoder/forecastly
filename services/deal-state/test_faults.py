"""Clean-vs-faults proof. Run with: make test-faults

The same events are processed three ways, starting from empty each time:
clean, with injected faults, and with faults while the service is killed.
The final state must be identical in all three.
"""
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "ml/simulator"))
sys.path.insert(0, str(ROOT / "services/deal-state"))
from replay import DEFAULT_FAULTS, load_events, plan_messages, replay
from test_e2e import BROKERS, read_dlq, sql, wait_until_caught_up

COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy/docker-compose.yml")]
TOPIC = "activity.events"
EVENTS_DIGEST = "SELECT count(*) AS n, md5(string_agg(event_id::text || event_type || deal_id || payload::text, ',' ORDER BY event_id)) AS digest FROM events"


def fresh_stack():
    subprocess.run(["make", "reset", "up"], cwd=ROOT, check=True, capture_output=True)


def final_state():
    health = sql("SELECT * FROM deal_health").drop(columns="updated_at").sort_values("deal_id").reset_index(drop=True)
    return health, sql(EVENTS_DIGEST).iloc[0].to_dict()


def assert_same(state, baseline, label):
    pd.testing.assert_frame_equal(state[0], baseline[0])
    assert state[1] == baseline[1], f"{label}: stored events differ"
    print(f"ok: {label} matches clean run ({len(state[0])} deals, {state[1]['n']} events)")


def kill_at_progress(total):
    """SIGKILL the service at fixed points, so each kill lands while it still has work left."""
    for share in (0.25, 0.5, 0.75):
        deadline = time.monotonic() + 180
        while (stored := sql("SELECT count(*) AS n FROM events")["n"].iloc[0]) < total * share:
            assert time.monotonic() < deadline, f"stuck at {stored} events"
            time.sleep(0.2)
        subprocess.run([*COMPOSE, "kill", "-s", "SIGKILL", "deal-state"], check=True, capture_output=True)
        print(f"killed service with {stored} of {total} events stored")
        subprocess.run([*COMPOSE, "start", "deal-state"], check=True, capture_output=True)


def main():
    table = load_events(ROOT / "data/simulated/events.parquet")

    fresh_stack()
    replay(table, BROKERS, TOPIC, seconds_per_day=0)
    wait_until_caught_up()
    clean = final_state()
    print(f"ok: clean run finished ({clean[1]['n']} events)")

    fresh_stack()
    _, counts = plan_messages(table, [0.0] * len(table), DEFAULT_FAULTS)
    replay(table, BROKERS, TOPIC, seconds_per_day=0, faults=DEFAULT_FAULTS)
    wait_until_caught_up()
    assert_same(final_state(), clean, "faults")
    dead = len(read_dlq(counts["broken"] + 1))
    assert dead == counts["broken"], f"{dead} of {counts['broken']} broken events reached the dead-letter topic"
    print(f"ok: all {dead} broken events reached the dead-letter topic")

    fresh_stack()
    subprocess.run([*COMPOSE, "stop", "deal-state"], check=True, capture_output=True)
    replay(table, BROKERS, TOPIC, seconds_per_day=0, faults=DEFAULT_FAULTS)
    subprocess.run([*COMPOSE, "start", "deal-state"], check=True, capture_output=True)
    started = time.monotonic()
    kill_at_progress(len(table))
    wait_until_caught_up()
    print(f"ok: recovered from 3 kills in {time.monotonic() - started:.0f}s")
    assert_same(final_state(), clean, "faults with 3 kills")


if __name__ == "__main__":
    main()
