"""Clean raw Maven and Enron data into data/processed/*.parquet."""
import email
import email.policy
import email.utils
import hashlib
import re
import tarfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"
OUT = ROOT / "data/processed"
MAX_REPLY_DAYS = 30
ENRON_START, ENRON_END = pd.Timestamp("1998-01-01", tz="UTC"), pd.Timestamp("2002-12-31", tz="UTC")


def slug(prefix, values):
    """Stable ids from names, sorted so reruns give the same result."""
    names = sorted(pd.Series(values).dropna().unique())
    return {name: f"{prefix}_{i:03d}" for i, name in enumerate(names, 1)}


def build_maven():
    d = RAW / "maven"
    pipeline = pd.read_csv(d / "sales_pipeline.csv", parse_dates=["engage_date", "close_date"])
    accounts = pd.read_csv(d / "accounts.csv").replace({"sector": {"technolgy": "technology"}})
    products = pd.read_csv(d / "products.csv")
    teams = pd.read_csv(d / "sales_teams.csv")
    pipeline["product"] = pipeline["product"].replace({"GTXPro": "GTX Pro"})

    account_ids = slug("acc", accounts["account"])
    rep_ids = slug("rep", pipeline["sales_agent"])
    teams = teams[teams["sales_agent"].isin(rep_ids)]  # 5 listed reps have no deals

    accounts_out = accounts.assign(account_id=accounts["account"].map(account_ids)).rename(
        columns={"account": "name", "sector": "industry", "office_location": "region"}
    )[["account_id", "name", "industry", "year_established", "revenue", "employees", "region", "subsidiary_of"]]
    reps_out = teams.assign(rep_id=teams["sales_agent"].map(rep_ids)).rename(
        columns={"sales_agent": "name", "regional_office": "region"}
    )[["rep_id", "name", "manager", "region"]]

    deals = pipeline.merge(products, on="product", how="left", validate="m:1")
    deals_out = pd.DataFrame({
        "deal_id": deals["opportunity_id"],
        "source": "maven",
        "account_id": deals["account"].map(account_ids),
        "owner_id": deals["sales_agent"].map(rep_ids),
        "product": deals["product"],
        # List price, known up front. close_value is 0 for every lost deal, so it is a label only.
        "amount": deals["sales_price"].astype(float),
        "stage": deals["deal_stage"],
        "engaged_at": deals["engage_date"],
        "closed_at": deals["close_date"],
        "outcome": deals["deal_stage"].map({"Won": "won", "Lost": "lost"}),
        "close_value": deals["close_value"],
    })
    return deals_out, accounts_out, reps_out, products


def parse_enron():
    """Read headers only, straight from the archive. Addresses are hashed and bodies never leave this function."""
    rows, seen = [], set()  # Message-ID differs between folder copies of one mail, so dedupe on content
    with tarfile.open(RAW / "enron/enron.tar.gz", "r|gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            msg = email.message_from_bytes(tar.extractfile(member).read(16384), policy=email.policy.compat32)
            sender = msg.get("From")
            recipients = re.findall(r"[\w.+'-]+@[\w.-]+", str(msg.get("To") or ""))
            if not (sender and recipients):
                continue
            key = (sender.strip().lower(), msg.get("Date"), msg.get("Subject"), tuple(sorted(recipients)))
            if key in seen:
                continue
            seen.add(key)
            try:
                sent = email.utils.parsedate_to_datetime(msg.get("Date"))
            except (TypeError, ValueError):
                continue
            if sent.tzinfo is None:
                continue
            subject = str(msg.get("Subject") or "")
            rows.append((pd.Timestamp(sent).tz_convert("UTC"), sent.hour, sent.weekday(), sender.strip().lower(),
                         {r.lower() for r in recipients}, subject))
    return pd.DataFrame(rows, columns=["sent_at", "local_hour", "weekday", "sender", "recipients", "subject"])


def build_enron():
    """One row per sent mail, marking replies matched to the earlier mail they answer."""
    mail = parse_enron()
    mail = mail[mail["sent_at"].between(ENRON_START, ENRON_END)].sort_values("sent_at").reset_index(drop=True)
    mail["is_reply"] = mail["subject"].str.match(r"(?i)^\s*re:")
    mail["topic"] = mail["subject"].str.replace(r"(?i)^(\s*(re|fw|fwd):\s*)+", "", regex=True).str.strip().str.lower()

    # ponytail: subject + sender/recipient match, as Enron headers have no In-Reply-To. Blank subjects are skipped.
    last_sent, delays = {}, []
    for row in mail.itertuples():
        delay = None
        if row.is_reply and row.topic:
            for recipient in row.recipients:
                earlier = last_sent.get((row.topic, recipient, row.sender))
                if earlier is not None and row.sent_at > earlier:
                    hours = (row.sent_at - earlier).total_seconds() / 3600
                    if hours <= MAX_REPLY_DAYS * 24:
                        delay = hours if delay is None else min(delay, hours)
        delays.append(delay)
        for recipient in row.recipients:
            last_sent[(row.topic, row.sender, recipient)] = row.sent_at
    mail["reply_delay_hours"] = pd.Series(delays, index=mail.index, dtype="float64")
    mail["thread_id"] = mail["topic"].map(lambda t: hashlib.sha256(t.encode()).hexdigest()[:12])
    return mail[["sent_at", "local_hour", "weekday", "thread_id", "is_reply", "reply_delay_hours"]]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    deals, accounts, reps, products = build_maven()
    deals.to_parquet(OUT / "deals.parquet", index=False)
    accounts.to_parquet(OUT / "accounts.parquet", index=False)
    reps.to_parquet(OUT / "reps.parquet", index=False)
    products.to_parquet(OUT / "products.parquet", index=False)
    if (RAW / "enron/enron.tar.gz").exists():
        build_enron().to_parquet(OUT / "enron_threads.parquet", index=False)


if __name__ == "__main__":
    main()
