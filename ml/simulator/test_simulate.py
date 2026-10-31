"""Run with: python3 ml/simulator/test_simulate.py"""
import json
import sys
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

sys.path.insert(0, str(Path(__file__).parent))
from simulate import ROOT, load_config, load_deals, simulate

SCHEMA = json.loads((ROOT / "schemas/event.v1.json").read_text())
EARLY_FEATURES = ["email_sent", "email_replied", "meeting_held", "meeting_no_show", "contact_added", "close_date_changed"]


def check_events_follow_schema(events):
    validator = jsonschema.Draft202012Validator(SCHEMA)
    for event in events:
        validator.validate(event)
    bad = {**events[0], "payload": {}}
    assert not validator.is_valid(bad), "schema must reject an empty payload"


def check_rules(events, contacts, deals):
    table = pd.DataFrame(events)
    assert table["event_id"].is_unique
    real = deals.set_index("deal_id")
    table["when"] = pd.to_datetime(table["occurred_at"]).dt.tz_localize(None)

    last = table.groupby("deal_id")["when"].max()
    closed = real[real["closed_at"].notna()]
    assert (last[closed.index].dt.normalize() == closed["closed_at"]).all(), "activity must stop on the real close date"
    open_deals = real[real["closed_at"].isna()]
    assert (last[open_deals.index] < pd.Timestamp("2018-01-01")).all()

    results = table[table["event_type"] == "deal_closed"].set_index("deal_id")
    assert results.index.is_unique and set(results.index) == set(closed.index), "exactly one close per finished deal"
    for deal_id, event in results.iterrows():
        assert event["payload"] == {"outcome": real.at[deal_id, "outcome"], "amount": real.at[deal_id, "close_value"]}

    stages = table[table["event_type"] == "stage_changed"].set_index("deal_id")["when"]
    assert (stages == real.loc[stages.index, "engaged_at"]).all(), "real stage date must be kept"

    per_deal = pd.DataFrame(contacts).groupby("deal_id").size()
    assert per_deal.between(1, 6).all() and set(per_deal.index) == set(real.index)


def check_same_seed_gives_same_data(deals, cfg):
    assert simulate(deals, cfg) == simulate(deals, cfg)
    changed = simulate(deals, {**cfg, "seed": cfg["seed"] + 1})
    assert changed[0] != simulate(deals, cfg)[0], "a new seed must change the data"


def early_signal(events, deals):
    """How well activity from the first half of a deal predicts its result. Near 1.0 means a leak."""
    table = pd.DataFrame(events)
    closed = deals[deals["outcome"].notna()].set_index("deal_id")
    table = table[table["deal_id"].isin(closed.index) & table["event_type"].isin(EARLY_FEATURES)]
    when = pd.to_datetime(table["occurred_at"]).dt.tz_localize(None)
    engaged, ended = table["deal_id"].map(closed["engaged_at"]), table["deal_id"].map(closed["closed_at"])
    early = table[when <= engaged + (ended - engaged) / 2]
    counts = early.pivot_table(index="deal_id", columns="event_type", aggfunc="size", fill_value=0)
    counts = counts.reindex(closed.index, fill_value=0)[EARLY_FEATURES]
    days = (closed["closed_at"] - closed["engaged_at"]).dt.days.clip(lower=1)
    x = np.log1p(counts.div(days, axis=0))
    return cross_val_score(LogisticRegression(max_iter=1000), x, closed["outcome"].eq("won"), cv=5, scoring="roc_auc").mean()


def main():
    cfg = load_config()
    sample = load_deals(300)
    check_same_seed_gives_same_data(sample, cfg)
    deals = load_deals()
    events, contacts, _ = simulate(deals, cfg)
    check_events_follow_schema(events)
    check_rules(events, contacts, deals)
    auc = early_signal(events, deals)
    assert 0.55 < auc < 0.95, f"early signal {auc:.3f} is too weak or a leak"
    print(f"ok: {len(deals)} deals, {len(events)} events, early-signal AUC {auc:.3f}")


if __name__ == "__main__":
    main()
