"""End-to-end check against the running stack. Run with: make test-api

Replays every event, then compares each endpoint with what Postgres holds.
"""
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml/simulator"))
sys.path.insert(0, str(ROOT / "services/deal-state"))
from replay import load_events, replay
from test_e2e import BROKERS, TYPES, sql, wait_until_scored

API = "http://localhost:8080"
LATEST = """SELECT DISTINCT ON (s.deal_id) s.deal_id, s.score, h.deal_closed
FROM deal_scores s JOIN deal_health h USING (deal_id) ORDER BY s.deal_id, s.as_of DESC, s.scored_at DESC"""


def get(path):
    """Returns (status, body) and doesn't treat 4xx as an exception."""
    try:
        with urllib.request.urlopen(API + path, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def check_at_risk(latest):
    status, body = get("/deals/at-risk?limit=1000")
    assert status == 200
    expected = latest[latest["deal_closed"] == 0].sort_values(["score", "deal_id"]).head(1000)
    assert [d["deal_id"] for d in body["deals"]] == expected["deal_id"].tolist(), "wrong deals or order"
    assert all(abs(d["score"] - s) < 1e-9 for d, s in zip(body["deals"], expected["score"])), "not the latest score"
    assert len(body["deals"][0]["factors"]) == 3
    closed = set(latest[latest["deal_closed"] > 0]["deal_id"])
    assert closed and not closed & {d["deal_id"] for d in body["deals"]}, "a closed deal is at risk"
    assert len(get("/deals/at-risk")[1]["deals"]) == 50
    assert len(get("/deals/at-risk?limit=3")[1]["deals"]) == 3
    print(f"ok: at-risk list matches Postgres ({len(body['deals'])} deals, closed deals excluded)")


def check_deal(latest):
    row = latest[latest["deal_closed"] == 0].iloc[0]
    status, deal = get(f"/deals/{row['deal_id']}")
    assert status == 200 and not deal["closed"] and abs(deal["score"] - row["score"]) < 1e-9
    counts = sql(f"SELECT {', '.join(TYPES)} FROM deal_health WHERE deal_id = '{row['deal_id']}'").iloc[0]
    assert {t: deal["activity"][t] for t in TYPES} == {t: int(counts[t]) for t in TYPES}
    assert deal["features"]["deal_id"] == row["deal_id"] and len(deal["factors"]) == 3

    finished = latest[latest["deal_closed"] > 0].iloc[0]["deal_id"]
    assert get(f"/deals/{finished}")[1]["closed"] is True

    prospect = sql("SELECT d.deal_id FROM deals d LEFT JOIN deal_health h USING (deal_id) WHERE h.deal_id IS NULL LIMIT 1").iloc[0, 0]
    status, untouched = get(f"/deals/{prospect}")
    assert status == 200 and untouched["score"] is None and untouched["activity"] is None
    print("ok: open, closed and never-active deals all return the right detail")


def check_history(latest):
    deal_id = sql("SELECT deal_id FROM deal_scores GROUP BY deal_id HAVING count(*) > 5 LIMIT 1").iloc[0, 0]
    stored = sql(f"SELECT as_of FROM deal_scores WHERE deal_id = '{deal_id}'")
    status, body = get(f"/deals/{deal_id}/scores?limit=1000")
    scores = body["scores"]
    assert status == 200 and len(scores) == len(stored)
    assert [s["as_of"] for s in scores] == sorted(s["as_of"] for s in scores)
    assert abs(scores[-1]["score"] - latest.set_index("deal_id").at[deal_id, "score"]) < 1e-9
    newest = get(f"/deals/{deal_id}/scores?limit=2")[1]["scores"]
    assert newest == scores[-2:], "a limit must keep the newest scores"
    print(f"ok: score history matches Postgres ({len(scores)} scores, oldest first)")


def check_events(latest):
    deal_id = latest.iloc[0]["deal_id"]
    stored = sql(f"SELECT count(*) AS n FROM events WHERE deal_id = '{deal_id}'")["n"].iloc[0]
    status, body = get(f"/deals/{deal_id}/events?limit=1000")
    times = [e["occurred_at"] for e in body["events"]]
    assert status == 200 and len(times) == stored and times == sorted(times, reverse=True)
    assert get(f"/deals/{deal_id}/events?limit=2")[1]["events"] == body["events"][:2]
    assert get("/deals/nope/events")[0] == 404
    print(f"ok: events match Postgres ({len(times)} events, newest first)")


def check_bad_requests():
    assert get("/health") == (200, {"status": "ok"})
    assert get("/deals/nope")[0] == 404
    assert get("/deals/nope/scores")[0] == 404
    assert get("/deals/at-risk?limit=0")[0] == 400
    assert get("/deals/" + urllib.parse.quote("x' OR '1'='1"))[0] == 404
    print("ok: unknown deals get 404, bad limits get 400")


def main():
    subprocess.run(["make", "reset", "up"], cwd=ROOT, check=True, capture_output=True)
    replay(load_events(ROOT / "data/simulated/events.parquet"), BROKERS, "activity.events", seconds_per_day=0)
    wait_until_scored()
    latest = sql(LATEST)
    check_at_risk(latest)
    check_deal(latest)
    check_history(latest)
    check_events(latest)
    check_bad_requests()


if __name__ == "__main__":
    main()
