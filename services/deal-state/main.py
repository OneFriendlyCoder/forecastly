"""Reads activity events from Kafka, keeps a live record per deal in Postgres, and publishes each
changed deal's features for scoring.

Delivery is at-least-once: offsets are committed only after Postgres commits and features are
published, and the events primary key turns any redelivery into a no-op. Broken events go to a
dead-letter topic.
"""
import json
import logging
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import psycopg
from confluent_kafka import Consumer, Producer

HERE = Path(__file__).parent
TOPIC = "activity.events"
DLQ_TOPIC = "activity.events.dlq"
FEATURES_TOPIC = "deal.features"
GROUP = "deal-state"
MAX_BATCH = 2000
EVENT_TYPES = ["email_sent", "email_replied", "meeting_held", "meeting_no_show",
               "contact_added", "close_date_changed", "stage_changed", "deal_closed"]

log = logging.getLogger("deal-state")
FEATURES_SQL = (HERE / "features.sql").read_text().replace("$1", "%s")


def apply_query(event_type):
    """Built from a fixed event type, never from message data. One statement keeps the insert and count atomic."""
    return f"""
WITH inserted AS (
    INSERT INTO events (event_id, event_type, occurred_at, tenant_id, deal_id, account_id, actor, payload, schema_version, published_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (event_id) DO NOTHING
    RETURNING deal_id, occurred_at, event_id
)
INSERT INTO deal_health (deal_id, {event_type}, last_event_at, last_event_id)
SELECT deal_id, 1, occurred_at, event_id FROM inserted
ON CONFLICT (deal_id) DO UPDATE SET
    {event_type} = deal_health.{event_type} + 1,
    -- event_id breaks ties, so the result doesn't depend on arrival order
    last_event_id = CASE WHEN (EXCLUDED.last_event_at, EXCLUDED.last_event_id) > (deal_health.last_event_at, deal_health.last_event_id)
                         THEN EXCLUDED.last_event_id ELSE deal_health.last_event_id END,
    last_event_at = GREATEST(deal_health.last_event_at, EXCLUDED.last_event_at),
    updated_at = now()"""


APPLY_EVENT = {event_type: apply_query(event_type) for event_type in EVENT_TYPES}


def load_validator():
    schema = json.loads((HERE.parents[1] / "schemas/event.v1.json").read_text())
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def reject_constant(name):
    raise ValueError(f"{name} isn't valid JSON")


def parse_event(validator, value):
    """Raises ValueError for any message that must go to the dead-letter topic.

    It rejects everything Postgres would refuse, so one bad message can't stop the consumer.
    """
    if b"\\u0000" in value:
        raise ValueError("contains a NUL character")
    event = json.loads(value, parse_constant=reject_constant)  # also raises for bad JSON and bad UTF-8
    error = jsonschema.exceptions.best_match(validator.iter_errors(event))
    if error:
        raise ValueError(f"breaks the schema: {error.message[:200]}")
    json.dumps(event, ensure_ascii=False, allow_nan=False).encode()  # huge numbers and broken text fail here
    occurred_at = datetime.strptime(event["occurred_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return event, occurred_at


def save(db, events):
    with db.pipeline(), db.cursor() as cursor:
        for event, occurred_at, published_at in events:
            cursor.execute(APPLY_EVENT[event["event_type"]], (
                event["event_id"], event["event_type"], occurred_at, event["tenant_id"], event["deal_id"],
                event["account_id"], json.dumps(event["actor"]), json.dumps(event["payload"]),
                event["schema_version"], published_at))
    db.commit()


def send(producer, messages):
    """Raises unless Kafka confirmed every message."""
    failures = []

    def confirm(error, _message):
        if error:
            failures.append(error)

    for topic, key, value, headers in messages:
        producer.produce(topic, key=key, value=value, headers=headers, on_delivery=confirm)
    if producer.flush(30) or failures:
        raise RuntimeError(f"kafka didn't confirm a message: {failures[:1]}")


def publish_features(db, producer, events):
    """One update per deal in the batch, however many events it had. It runs even if every event was
    a redelivery, so a crash between saving and publishing loses nothing."""
    deal_ids = list({event["deal_id"] for event, _, _ in events})
    rows = db.execute(FEATURES_SQL, (deal_ids,)).fetchall()
    db.commit()
    send(producer, [(FEATURES_TOPIC, deal_id.encode(), features.encode(), None) for deal_id, features in rows])


def handle(validator, db, producer, messages):
    events, dead = [], []
    for message in messages:
        try:
            event, occurred_at = parse_event(validator, message.value() or b"")
            published_at = datetime.fromtimestamp(message.timestamp()[1] / 1000, timezone.utc)
            events.append((event, occurred_at, published_at))
        except ValueError as error:  # includes bad JSON, bad UTF-8 and bad dates
            log.warning("sending to dead-letter topic: partition %s offset %s: %s",
                        message.partition(), message.offset(), error)
            dead.append((DLQ_TOPIC, message.key(), message.value(), [("error", str(error).encode())]))
    if events:
        save(db, events)
    if dead:
        send(producer, dead)
    if events:
        publish_features(db, producer, events)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    brokers = os.environ.get("KAFKA_BROKERS", "localhost:19092")
    validator = load_validator()
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    signal.signal(signal.SIGINT, lambda *_: stopping.append(True))

    with psycopg.connect(os.environ.get("DATABASE_URL", "postgres://pulse:pulse@localhost:5432/pipeline_pulse")) as db:
        db.execute((HERE / "schema.sql").read_text())
        db.commit()
        producer = Producer({"bootstrap.servers": brokers, "enable.idempotence": True,
                             "partitioner": "murmur2_random"})  # matches the replay tool
        consumer = Consumer({"bootstrap.servers": brokers, "group.id": GROUP, "auto.offset.reset": "earliest",
                             "enable.auto.commit": False,
                             "session.timeout.ms": 10000})  # a killed consumer's partitions move on after this long
        consumer.subscribe([TOPIC])
        log.info("consuming %s", TOPIC)
        try:
            while not stopping:
                messages = consumer.consume(MAX_BATCH, timeout=0.2)
                if not messages:
                    continue
                for message in messages:
                    if message.error():
                        raise RuntimeError(message.error())
                handle(validator, db, producer, messages)  # a failure restarts us; the primary key makes rereading safe
                consumer.commit(asynchronous=False)
        finally:
            consumer.close()


if __name__ == "__main__":
    main()
