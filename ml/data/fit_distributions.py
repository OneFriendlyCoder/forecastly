"""Fit the real-data targets the simulator must match; writes ml/simulator/distributions.json."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "data/processed"
QUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]


def quantiles(s):
    return {str(q): round(float(s.quantile(q)), 2) for q in QUANTILES}


def main():
    deals = pd.read_parquet(P / "deals.parquet")
    accounts = pd.read_parquet(P / "accounts.parquet")
    closed = deals[deals["outcome"].notna()].assign(
        cycle_days=lambda d: (d["closed_at"] - d["engaged_at"]).dt.days,
        won=lambda d: d["outcome"].eq("won"),
    ).merge(accounts[["account_id", "industry"]], on="account_id")

    won = closed[closed["won"]]
    out = {
        "win_rate": round(float(closed["won"].mean()), 4),
        "win_rate_by_product": closed.groupby("product")["won"].mean().round(4).to_dict(),
        "win_rate_by_industry": closed.groupby("industry")["won"].mean().round(4).to_dict(),
        "win_rate_by_rep": closed.groupby("owner_id")["won"].mean().round(4).to_dict(),
        "cycle_days_by_outcome": {k: quantiles(g) for k, g in closed.groupby("outcome")["cycle_days"]},
        "cycle_days_by_product": {k: quantiles(g) for k, g in closed.groupby("product")["cycle_days"]},
        # Won deals only: lost deals have no recorded value.
        "discount_vs_list": quantiles(won["close_value"] / won["amount"]),
        "deals_per_rep": quantiles(deals.groupby("owner_id").size()),
    }
    enron_path = P / "enron_threads.parquet"
    if enron_path.exists():
        mail = pd.read_parquet(enron_path)
        delays = mail["reply_delay_hours"].dropna()
        log_delays = np.log(delays[delays > 0])
        out["reply_delay_hours"] = quantiles(delays) | {"log_mean": round(float(log_delays.mean()), 4),
                                                       "log_std": round(float(log_delays.std()), 4)}
        out["thread_length"] = quantiles(mail.groupby("thread_id").size())
        out["hour_of_day"] = mail["local_hour"].value_counts(normalize=True).sort_index().round(4).to_dict()
        out["weekday"] = mail["weekday"].value_counts(normalize=True).sort_index().round(4).to_dict()
    target = ROOT / "ml/simulator/distributions.json"
    target.write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
