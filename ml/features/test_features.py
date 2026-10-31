"""Run with: python3 ml/features/test_features.py"""
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from build_snapshots import CHECKPOINT_DAYS, build_snapshots, checkpoints, load_events, load_finished_deals
from features import build_features

AS_OF = datetime(2017, 3, 31, tzinfo=timezone.utc)
CONTACT = {"kind": "contact", "id": "c1", "role": "champion"}
REP = {"kind": "rep", "id": "rep_001"}


def event(event_id, event_type, day, actor=REP, payload=None):
    return {"event_id": str(event_id), "event_type": event_type, "occurred_at": f"2017-03-{day:02d}T12:00:00Z",
            "actor": actor, "payload": payload or {}}


def reply(event_id, day, sentiment="neutral", hours=2.0):
    return event(event_id, "email_replied", day, CONTACT, {"reply_delay_hours": hours, "sentiment": sentiment})


def future_events(as_of):
    """One of every event type, all a second too late to count."""
    when = (as_of + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payloads = {"email_replied": {"reply_delay_hours": 1.0, "sentiment": "negative"}}
    types = ["email_sent", "email_replied", "meeting_held", "meeting_no_show", "contact_added",
             "close_date_changed", "stage_changed", "deal_closed"]
    return [{"event_id": f"future-{t}", "event_type": t, "occurred_at": when, "actor": CONTACT,
             "payload": payloads.get(t, {})} for t in types]


def check_known_answer():
    events = [event(1, "stage_changed", 1), event(2, "email_sent", 1), event(3, "email_sent", 20),
              reply(4, 2, "negative", 2.0), reply(5, 21, hours=4.0), event(6, "meeting_held", 25),
              event(7, "meeting_no_show", 2), event(8, "contact_added", 3), event(9, "close_date_changed", 4)]
    assert build_features(events, AS_OF) == {
        "days_since_engaged": 29.5, "emails_sent_14d": 1, "replies_14d": 1, "meetings_14d": 1,
        "days_since_last_reply": 9.5, "median_reply_hours": 3.0, "negative_replies": 1, "contacts_added": 1,
        "buyers_replied": 1, "no_shows": 1, "close_date_pushes": 1}


def check_empty_history():
    features = build_features([], AS_OF)
    assert features["days_since_last_reply"] is None and features["days_since_engaged"] is None
    assert features["replies_14d"] == 0


def check_leakage(deals, events):
    """The core guarantee, on real deals: later events can't change what a checkpoint sees."""
    for deal in deals.sample(300, random_state=1).itertuples():
        history = events[deal.deal_id]
        for as_of in checkpoints(deal).values():
            before = [e for e in history if e["occurred_at"] <= as_of.strftime("%Y-%m-%dT%H:%M:%SZ")]
            expected = build_features(before, as_of)
            assert build_features(history, as_of) == expected, "the deal's own later events leaked"
            assert build_features(history + future_events(as_of), as_of) == expected, "fake future events leaked"


def check_the_leak_test_can_fail():
    as_of = AS_OF
    leaked = [{**e, "occurred_at": as_of.strftime("%Y-%m-%dT%H:%M:%SZ")} for e in future_events(as_of)]
    assert build_features(leaked, as_of) != build_features([], as_of), "events at as_of must count"


def check_duplicates_and_late_arrivals():
    events = [event(1, "stage_changed", 1), reply(2, 10), reply(3, 20), event(4, "email_sent", 5)]
    expected = build_features(events, AS_OF)
    mixed = events + events[:2]
    random.Random(7).shuffle(mixed)
    assert build_features(mixed, AS_OF) == expected


def check_snapshots(snapshots, deals):
    closed = deals.set_index("deal_id")["closed_at"].dt.tz_localize("UTC")
    assert (snapshots["as_of"] < snapshots["deal_id"].map(closed)).all(), "no checkpoint at or after the close"
    assert not snapshots.duplicated(["deal_id", "checkpoint_day"]).any()
    assert set(snapshots["checkpoint_day"]) == set(CHECKPOINT_DAYS)
    assert (snapshots["days_since_engaged"] == snapshots["checkpoint_day"]).all()
    assert snapshots["won"].nunique() == 2


def strongest_signal(snapshots):
    """Best AUC of any single feature. Near 1.0 would mean the result slipped into the features."""
    scores = {}
    for name in snapshots.columns.drop(["deal_id", "checkpoint_day", "as_of", "product", "won"]):
        values = snapshots[name].fillna(-1)
        score = roc_auc_score(snapshots["won"], values)
        scores[name] = max(score, 1 - score)
    return max(scores.items(), key=lambda item: item[1])


def main():
    check_known_answer()
    check_empty_history()
    check_the_leak_test_can_fail()
    check_duplicates_and_late_arrivals()
    deals, events = load_finished_deals(), load_events()
    check_leakage(deals, events)
    snapshots = build_snapshots(deals, events)
    check_snapshots(snapshots, deals)
    name, auc = strongest_signal(snapshots)
    assert auc < 0.9, f"{name} predicts the result too well: {auc:.3f}"
    print(f"all feature checks passed, {len(snapshots):,} rows, strongest single feature: {name} (AUC {auc:.3f})")


if __name__ == "__main__":
    main()
