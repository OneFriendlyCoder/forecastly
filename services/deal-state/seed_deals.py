"""Loads the CRM fields the events don't carry into Postgres. Safe to run again."""
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PSQL = ["docker", "compose", "-f", str(ROOT / "deploy/docker-compose.yml"), "exec", "-T", "postgres",
        "psql", "-U", "pulse", "-d", "pipeline_pulse", "--single-transaction", "-v", "ON_ERROR_STOP=1",
        "-c", "TRUNCATE deals", "-c", "COPY deals FROM STDIN WITH CSV"]


def seed(copies=1):
    """copies matches replay.scale_events, which repeats each deal under a new id."""
    reps = pd.read_parquet(ROOT / "data/processed/reps.parquet").set_index("rep_id")["name"]
    deals = pd.read_parquet(ROOT / "data/processed/deals.parquet")
    deals = deals.assign(owner=deals["owner_id"].map(reps))[["deal_id", "product", "amount", "owner"]]
    tables = [deals, *(deals.assign(deal_id=deals["deal_id"] + f"_c{copy}") for copy in range(2, copies + 1))]
    rows = pd.concat(tables).to_csv(index=False, header=False)
    deadline = time.monotonic() + 30
    while True:  # deal-state makes the table when it starts, which can take a moment
        result = subprocess.run(PSQL, input=rows, capture_output=True, text=True)
        if result.returncode == 0:
            return
        if time.monotonic() > deadline:
            sys.exit(result.stderr)
        time.sleep(1)


if __name__ == "__main__":
    seed()
