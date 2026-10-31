"""Turns one deal's events into model features, using only what was known at a given moment."""
import statistics
from datetime import datetime, timedelta, timezone

RECENT = timedelta(days=14)


def parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def days_between(earlier, later):
    return (later - earlier).total_seconds() / 86400


def build_features(events, as_of):
    """events: one deal's events in the contract's shape. as_of: timezone-aware datetime.

    Counts and latest times don't depend on order, so late events are safe, and event_id
    removes the duplicates at-least-once delivery can send.
    """
    known = {}
    for event in events:
        when = parse_time(event["occurred_at"])
        if when <= as_of:
            known[event["event_id"]] = (when, event)

    def happened(event_type):
        return [(when, e) for when, e in known.values() if e["event_type"] == event_type]

    def recent(rows):
        return sum(when > as_of - RECENT for when, _ in rows)

    sent, replies = happened("email_sent"), happened("email_replied")
    meetings, no_shows = happened("meeting_held"), happened("meeting_no_show")
    engaged = happened("stage_changed")
    return {
        "days_since_engaged": days_between(min(when for when, _ in engaged), as_of) if engaged else None,
        "emails_sent_14d": recent(sent),
        "replies_14d": recent(replies),
        "meetings_14d": recent(meetings),
        "days_since_last_reply": days_between(max(when for when, _ in replies), as_of) if replies else None,
        "median_reply_hours": statistics.median(e["payload"]["reply_delay_hours"] for _, e in replies) if replies else None,
        "negative_replies": sum(e["payload"]["sentiment"] == "negative" for _, e in replies),
        "contacts_added": len(happened("contact_added")),
        "buyers_replied": len({e["actor"]["id"] for _, e in replies}),
        "no_shows": len(no_shows),
        "close_date_pushes": len(happened("close_date_changed")),
    }
