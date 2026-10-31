"""Builds the training file: finished deals, measured partway through, with the real result."""
import json
import sys
from datetime import timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from features import build_features

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/simulated/training_snapshots.parquet"
CHECKPOINT_DAYS = [7, 14, 30, 60, 90]


def load_events():
    table = pd.read_parquet(ROOT / "data/simulated/events.parquet")
    table["actor"] = table["actor"].map(json.loads)
    table["payload"] = table["payload"].map(json.loads)
    return {deal_id: rows.to_dict("records") for deal_id, rows in table.groupby("deal_id")}


def load_finished_deals():
    deals = pd.read_parquet(ROOT / "data/processed/deals.parquet")
    return deals[deals["outcome"].notna()]


def checkpoints(deal):
    """Times to measure a deal. Anything on or after its close date would already know the result."""
    engaged = deal.engaged_at.to_pydatetime().replace(tzinfo=timezone.utc)
    closed = deal.closed_at.to_pydatetime().replace(tzinfo=timezone.utc)
    moments = {day: engaged + timedelta(days=day) for day in CHECKPOINT_DAYS}
    return {day: as_of for day, as_of in moments.items() if as_of < closed}


def build_snapshots(deals, events):
    rows = []
    for deal in deals.itertuples():
        for day, as_of in checkpoints(deal).items():
            rows.append({"deal_id": deal.deal_id, "checkpoint_day": day, "as_of": as_of,
                         "product": deal.product, "amount": deal.amount,
                         **build_features(events[deal.deal_id], as_of),
                         "won": deal.outcome == "won"})
    return pd.DataFrame(rows)


def main():
    snapshots = build_snapshots(load_finished_deals(), load_events())
    snapshots.to_parquet(OUTPUT, index=False)
    print(f"wrote {len(snapshots):,} rows for {snapshots['deal_id'].nunique():,} deals to {OUTPUT}")
    print(snapshots.groupby("checkpoint_day")["won"].agg(rows="size", won_share="mean").round(3))


if __name__ == "__main__":
    main()
