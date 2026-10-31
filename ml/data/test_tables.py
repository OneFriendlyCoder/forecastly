"""Run with: python3 ml/data/test_tables.py"""
from pathlib import Path

import pandas as pd

P = Path(__file__).resolve().parents[2] / "data/processed"


def main():
    d = pd.read_parquet(P / "deals.parquet")
    accounts = pd.read_parquet(P / "accounts.parquet")
    reps = pd.read_parquet(P / "reps.parquet")
    assert len(d) == 8800 and d["deal_id"].is_unique
    assert d["stage"].value_counts().to_dict() == {"Won": 4238, "Lost": 2473, "Engaging": 1589, "Prospecting": 500}
    assert (d["amount"] > 0).all(), "every deal needs a list price"
    closed = d[d["outcome"].notna()]
    assert len(closed) == 6711 and closed["account_id"].notna().all()
    assert (closed["closed_at"] >= closed["engaged_at"]).all()
    assert d.loc[d["outcome"].isna(), "closed_at"].isna().all()
    assert d["owner_id"].isin(reps["rep_id"]).all() and d["account_id"].dropna().isin(accounts["account_id"]).all()
    assert "technolgy" not in set(accounts["industry"]) and "GTXPro" not in set(d["product"])

    print("ok: deals", len(d), "closed", len(closed))

    e_path = P / "enron_threads.parquet"
    if e_path.exists():
        e = pd.read_parquet(e_path)
        assert (e["reply_delay_hours"].dropna() > 0).all()
        assert not {"subject", "sender", "body"} & set(e.columns), "no personal fields in processed Enron data"
        print("ok: enron messages", len(e), "reply pairs", int(e["reply_delay_hours"].notna().sum()))


if __name__ == "__main__":
    main()
