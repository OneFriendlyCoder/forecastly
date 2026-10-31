"""Live scoring proof against the real stack. Run with: make test-scoring

Replays every event, then checks the live results against the batch code, then repeats with
injected faults while killing both services. Open deals must end on identical scores.
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
for folder in ("ml/simulator", "ml/features", "ml/model", "ml/scoring", "services/deal-state"):
    sys.path.insert(0, str(ROOT / folder))
from build_snapshots import load_events as load_deal_events
from build_snapshots import load_finished_deals
from features import build_features
from replay import DEFAULT_FAULTS, load_events, replay
from score import load_model, score_updates
from test_e2e import BROKERS, scoring_backlog, sql, wait_until_scored
from train import MODEL_PATH, TEST_DEALS_PATH

COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy/docker-compose.yml")]
TOPIC = "activity.events"
SAMPLE = 3000
LATEST_OPEN = """SELECT DISTINCT ON (s.deal_id) s.deal_id, s.as_of, s.score FROM deal_scores s
JOIN deal_health h USING (deal_id) WHERE h.deal_closed = 0 ORDER BY s.deal_id, s.as_of DESC"""


def fresh_stack():
    subprocess.run(["make", "reset", "up"], cwd=ROOT, check=True, capture_output=True)


def stored_scores(limit):
    rows = sql(f"SELECT deal_id, as_of, score, features FROM deal_scores ORDER BY md5(deal_id || as_of::text) LIMIT {limit}")
    rows["features"] = rows["features"].map(json.loads)
    return rows


def check_go_matches_python(rows, events):
    """The training features and the live features come from two codebases and must agree."""
    for row in rows.itertuples():
        as_of = datetime.fromisoformat(row.as_of).astimezone(timezone.utc)
        expected = build_features(events[row.deal_id], as_of)
        for name, value in expected.items():
            live = row.features[name]
            same = live is None if value is None else live is not None and abs(live - value) < 1e-6
            assert same, f"{row.deal_id} at {row.as_of}: {name} is {live} live and {value} in training code"
    print(f"ok: go and python features match on {len(rows)} live updates")


def check_scores_match_model(rows):
    model, version = load_model(MODEL_PATH)
    updates = rows["features"].tolist()
    batch = np.array([score for score, _ in score_updates(updates, model)])
    assert np.allclose(rows["score"], batch), "live scores differ from the saved model"
    assert sql("SELECT DISTINCT model_version FROM deal_scores")["model_version"].tolist() == [version]
    factors = sql("SELECT factors FROM deal_scores LIMIT 1")["factors"].map(json.loads)[0]
    assert len(factors) == 3 and {"feature", "value", "impact"} == set(factors[0])
    print(f"ok: live scores match the saved model, version {version}")


def check_only_valid_deals_scored():
    young = sql("SELECT count(*) AS n FROM deal_scores WHERE (features->>'days_since_engaged')::float8 < 7")["n"][0]
    assert young == 0, f"{young} scores on deals under 7 days old"
    deals = load_finished_deals().assign(closed=lambda d: d["closed_at"].dt.strftime("%Y-%m-%d"))
    latest = sql("SELECT deal_id, max(as_of)::date::text AS last FROM deal_scores GROUP BY deal_id").set_index("deal_id")
    joined = deals.set_index("deal_id").join(latest, how="inner")
    assert (joined["last"] <= joined["closed"]).all(), "a deal was scored after it closed"
    print("ok: no scores on young deals or after a close")


def live_auc():
    """Unseen finished deals, scored around day 30, against their real result."""
    test_deals = json.loads(TEST_DEALS_PATH.read_text())
    outcomes = load_finished_deals().set_index("deal_id")["outcome"]
    ids = ",".join(f"'{deal_id}'" for deal_id in test_deals)
    scores = sql(f"""SELECT DISTINCT ON (deal_id) deal_id, score FROM deal_scores
        WHERE deal_id IN ({ids}) AND (features->>'days_since_engaged')::float8 <= 30
        ORDER BY deal_id, as_of DESC""")
    auc = roc_auc_score(scores["deal_id"].map(outcomes).eq("won"), scores["score"])
    print(f"ok: live AUC {auc:.3f} on {len(scores)} unseen deals, up to day 30")
    assert auc > 0.5


def kill_during_run(service, pause):
    for _ in range(3):
        time.sleep(pause)
        subprocess.run([*COMPOSE, "kill", "-s", "SIGKILL", service], check=True, capture_output=True)
        subprocess.run([*COMPOSE, "start", service], check=True, capture_output=True)
        print(f"killed {service} with {scoring_backlog()} updates waiting")


def main():
    table = load_events(ROOT / "data/simulated/events.parquet")

    fresh_stack()
    replay(table, BROKERS, TOPIC, seconds_per_day=0)
    wait_until_scored()
    total = sql("SELECT count(*) AS n, count(DISTINCT deal_id) AS deals FROM deal_scores").iloc[0]
    print(f"ok: clean run, {total['n']} scores across {total['deals']} deals")
    rows = stored_scores(SAMPLE)
    check_go_matches_python(rows, load_deal_events())
    check_scores_match_model(rows)
    check_only_valid_deals_scored()
    live_auc()
    clean = sql(LATEST_OPEN)

    fresh_stack()
    replay(table, BROKERS, TOPIC, seconds_per_day=0, faults=DEFAULT_FAULTS)
    kill_during_run("scoring", 3)
    kill_during_run("deal-state", 5)
    wait_until_scored()
    final = sql(LATEST_OPEN)
    assert final.equals(clean), "open deals ended on different scores"
    print(f"ok: {len(final)} open deals end on identical scores after faults and 6 kills")


if __name__ == "__main__":
    main()
