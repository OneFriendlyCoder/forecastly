"""Generate a simulated activity history for each real deal.

Real deal fields are never changed. A hidden daily health score, steered by the
real outcome, sets how likely each activity is.
"""
import argparse
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLES = ["champion", "economic_buyer", "technical_evaluator", "end_user"]
MEETING_STAGES = [(0.25, "discovery"), (0.5, "demo"), (0.8, "pricing"), (1.01, "legal")]
QUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]
NAMESPACE = uuid.UUID("6f1d2b52-3f58-4c0e-9d3b-0d6c1f6c7a10")
FULL_CYCLE = 138  # longest real deal; meeting progress on open deals is measured against it


def rng_for(seed, key):
    digest = int(hashlib.sha256(str(key).encode()).hexdigest()[:16], 16)
    return np.random.default_rng([seed, digest])


def lerp(pair, h):
    return pair[0] + (pair[1] - pair[0]) * h


def pick_story(outcome, rng, messy_share):
    if outcome is None:
        return "open"
    return f"{outcome}_messy" if rng.random() < messy_share else outcome


def health_path(story, length, rng, cfg):
    """One health value per day of the deal, from engagement to the end."""
    c = cfg["health"]
    targets = c["targets"]
    pull = min(1.0, c["pull"] / max(length, 1))
    h = np.empty(length + 1)
    h[0] = c["start"] + rng.uniform(-c["start_jitter"], c["start_jitter"])
    for day in range(length):
        target, step = targets[story], pull
        if story == "lost_messy" and day >= c["late_fall_at"] * length:
            target, step = targets["lost_messy_final"], min(1.0, pull * c["late_fall_pull"])
        h[day + 1] = np.clip(h[day] + (target - h[day]) * step + rng.normal(0, c["noise"]), 0, 1)
    return h


def expected_close(deal, cycles, rng):
    """Drawn from typical lengths for the product, never from the real close date."""
    days = np.interp(rng.uniform(0.1, 0.9), QUANTILES, [cycles[str(q)] for q in QUANTILES])
    return deal.engaged_at + timedelta(days=max(int(days), 7))


def working_time(day, rng, cfg):
    start, end = cfg["workday_hours"]
    return day + timedelta(seconds=int(rng.uniform(start, end) * 3600))


def simulate_deal(deal, rep_activity, weekday_weights, cycles, cfg):
    """Return (events, contacts, health rows) for one deal. Same inputs give the same output."""
    rng = rng_for(cfg["seed"], deal.deal_id)
    outcome = deal.outcome if isinstance(deal.outcome, str) else None
    story = pick_story(outcome, rng, cfg["messy_share"])
    closed = pd.notna(deal.closed_at)
    end_day = deal.closed_at if closed else pd.Timestamp(cfg["data_end"])
    end_time = end_day + timedelta(hours=23, minutes=59, seconds=59)
    length = (end_day - deal.engaged_at).days
    path = health_path(story, length if closed else cfg["open_deal_length"], rng, cfg)
    r = cfg["rates"]

    raw, contacts = [], []
    message_count = email_step = 0

    def emit(when, event_type, actor, payload):
        if when <= end_time:
            raw.append((when, event_type, actor, payload))

    def add_contact(when):
        contact_id = f"con_{deal.deal_id}_{len(contacts) + 1}"
        taken = {c["role"] for c in contacts}
        free = [role for role in ROLES if role not in taken] or ROLES[1:]
        role = "champion" if not contacts else str(rng.choice(free))
        contacts.append({"contact_id": contact_id, "deal_id": deal.deal_id, "role": role, "added_at": when})
        emit(when, "contact_added", {"kind": "rep", "id": deal.owner_id}, {"contact_id": contact_id, "role": role})

    def contact_actor(contact):
        return {"kind": "contact", "id": contact["contact_id"], "role": contact["role"]}

    prelude = int(rng.integers(cfg["prelude_days"][0], cfg["prelude_days"][1] + 1))
    start = deal.engaged_at - timedelta(days=prelude)
    add_contact(working_time(start, rng, cfg))
    emit(deal.engaged_at, "stage_changed", {"kind": "system", "id": "crm"}, {"from": "Prospecting", "to": "Engaging"})

    expected = expected_close(deal, cycles, rng)
    for offset in range((end_day - start).days + 1):
        day = start + timedelta(days=offset)
        age = (day - deal.engaged_at).days
        h = path[min(max(age, 0), len(path) - 1)]
        pace = rep_activity * weekday_weights[day.weekday()] / 7

        for sent in sorted(working_time(day, rng, cfg) for _ in range(rng.poisson(lerp(r["emails_per_week"], h) * pace))):
            contact = contacts[rng.integers(len(contacts))]
            message_count += 1
            email_step += 1
            message_id = f"msg_{deal.deal_id}_{message_count}"
            emit(sent, "email_sent", {"kind": "rep", "id": deal.owner_id},
                 {"message_id": message_id, "contact_id": contact["contact_id"], "sequence_step": email_step,
                  "template_id": f"tpl_{rng.integers(1, 13):02d}"})
            if rng.random() < lerp(r["reply_chance"], h):
                hours = rng.lognormal(cfg["reply_log_mean"], cfg["reply_log_std"]) * cfg["buyer_reply_slowdown"]
                hours *= lerp([cfg["reply_slowdown_at_zero_health"], 1], h)
                hours = max(min(hours, cfg["max_reply_hours"]), 1 / 60)
                sentiment = rng.choice(["positive", "neutral", "negative"], p=[0.6 * h, 0.4, 0.6 * (1 - h)])
                emit(sent + timedelta(hours=hours), "email_replied", contact_actor(contact),
                     {"message_id": message_id, "reply_delay_hours": round(hours, 2), "sentiment": str(sentiment)})

        if age >= 0:
            for _ in range(rng.poisson(lerp(r["meetings_per_week"], h) * pace)):
                progress = age / (length if closed and length else FULL_CYCLE)
                meeting_type = next(name for limit, name in MEETING_STAGES if min(progress, 1) < limit)
                size = int(rng.integers(1, len(contacts) + 1))
                attendees = [str(c) for c in rng.choice([c["contact_id"] for c in contacts], size, replace=False)]
                event = "meeting_no_show" if rng.random() < lerp(r["no_show_chance"], h) else "meeting_held"
                emit(working_time(day, rng, cfg), event, {"kind": "rep", "id": deal.owner_id},
                     {"meeting_type": meeting_type, "attendees": attendees})

            if len(contacts) < cfg["max_contacts"] and rng.random() < lerp(r["contacts_per_week"], h) * pace:
                add_contact(working_time(day, rng, cfg))

            overdue = day > expected
            near = abs((expected - day).days) <= cfg["push_window_days"]
            if overdue or (near and rng.random() < lerp(r["extra_pushes_per_week"], h) / 7):
                new = max(expected, day) + timedelta(days=int(rng.integers(cfg["push_days"][0], cfg["push_days"][1] + 1)))
                emit(working_time(day, rng, cfg), "close_date_changed", {"kind": "rep", "id": deal.owner_id},
                     {"old": expected.date().isoformat(), "new": new.date().isoformat()})
                expected = new

    if closed:
        emit(end_time, "deal_closed", {"kind": "system", "id": "crm"},
             {"outcome": outcome, "amount": float(deal.close_value)})

    raw.sort(key=lambda e: e[0])  # stable, so same-time events keep generation order
    events = [{
        "event_id": str(uuid.uuid5(NAMESPACE, f"{cfg['seed']}:{deal.deal_id}:{seq}")),
        "event_type": event_type,
        "occurred_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tenant_id": cfg["tenant_id"],
        "deal_id": deal.deal_id,
        "account_id": deal.account_id if isinstance(deal.account_id, str) else None,
        "actor": actor,
        "payload": payload,
        "schema_version": 1,
    } for seq, (when, event_type, actor, payload) in enumerate(raw)]
    health = {"deal_id": deal.deal_id, "story": story, "health": path.round(4).tolist()}
    return events, contacts, health


def load_config(path=ROOT / "ml/simulator/config.yaml"):
    cfg = yaml.safe_load(Path(path).read_text())
    fitted = json.loads((ROOT / "ml/simulator/distributions.json").read_text())
    cfg["reply_log_mean"] = fitted["reply_delay_hours"]["log_mean"]
    cfg["reply_log_std"] = fitted["reply_delay_hours"]["log_std"]
    cfg["weekday_weights"] = [fitted["weekday"][str(d)] * 7 for d in range(7)]
    cfg["cycles"] = fitted["cycle_days_by_product"]
    return cfg


def load_deals(limit=None):
    """Prospecting deals have no dates, so they are left out."""
    deals = pd.read_parquet(ROOT / "data/processed/deals.parquet")
    deals = deals[deals["engaged_at"].notna()].sort_values("deal_id")
    return deals.head(limit) if limit else deals


def simulate(deals, cfg):
    reps = {rep: float(rng_for(cfg["seed"], rep).lognormal(0, cfg["rep_activity_spread"]))
            for rep in deals["owner_id"].unique()}
    events, contacts, health = [], [], []
    for deal in deals.itertuples(index=False):
        e, c, h = simulate_deal(deal, reps[deal.owner_id], cfg["weekday_weights"], cfg["cycles"][deal.product], cfg)
        events += e
        contacts += c
        health.append(h)
    return events, contacts, health


def write(events, contacts, health, out):
    out.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(events).sort_values("occurred_at", kind="stable")  # keeps each deal's event order
    table["actor"] = table["actor"].map(json.dumps)
    table["payload"] = table["payload"].map(json.dumps)
    table.to_parquet(out / "events.parquet", index=False)
    pd.DataFrame(contacts).to_parquet(out / "contacts.parquet", index=False)
    pd.DataFrame(health).to_parquet(out / "health_paths.parquet", index=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="only simulate this many deals")
    parser.add_argument("--out", type=Path, default=ROOT / "data/simulated")
    args = parser.parse_args()
    events, contacts, health = simulate(load_deals(args.limit), load_config())
    write(events, contacts, health, args.out)
    print(f"{len(health)} deals, {len(events)} events, {len(contacts)} contacts -> {args.out}")


if __name__ == "__main__":
    main()
