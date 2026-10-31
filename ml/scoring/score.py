"""Scores each deal update from Kafka and saves the result in Postgres.

Delivery is at-least-once: offsets are committed only after Postgres commits, and the deal_scores
primary key turns any redelivery into an overwrite of the same row.
"""
import hashlib
import json
import os
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import psycopg
from confluent_kafka import Consumer

TOPIC = "deal.features"
MAX_BATCH = 2000
SAVE = """
INSERT INTO deal_scores (deal_id, as_of, model_version, score, factors, features, event_published_at)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (deal_id, as_of, model_version) DO UPDATE SET
    score = EXCLUDED.score,
    factors = EXCLUDED.factors,
    features = EXCLUDED.features,
    event_published_at = EXCLUDED.event_published_at,
    scored_at = clock_timestamp()"""


def load_model(path):
    """The version is the file's own hash, so a score always traces back to the exact model."""
    data = Path(path).read_text()
    return lgb.Booster(model_str=data), hashlib.sha256(data.encode()).hexdigest()[:12]


def to_frame(updates, model):
    names = model.feature_name()
    frame = pd.DataFrame(updates).reindex(columns=names)
    numbers = [name for name in names if name != "product"]
    frame[numbers] = frame[numbers].astype(float)
    frame["product"] = pd.Categorical(frame["product"], categories=model.pandas_categorical[0])
    return frame


def top_factors(contributions, names, row, count=3):
    """The biggest pushes on this score. Positive impact raises the chance of winning."""
    largest = sorted(zip(names, contributions), key=lambda pair: abs(pair[1]), reverse=True)[:count]
    return [{"feature": name, "value": row[name], "impact": round(float(impact), 4)} for name, impact in largest]


def score_updates(updates, model):
    frame = to_frame(updates, model)
    scores = model.predict(frame)
    contributions = model.predict(frame, pred_contrib=True)[:, :-1]  # the last column is the base rate
    names = model.feature_name()
    return [(float(score), top_factors(row, names, update))
            for score, row, update in zip(scores, contributions, updates)]


def save(db, updates, scored, version):
    rows = [(u["deal_id"], u["as_of"], version, score, json.dumps(factors), json.dumps(u), u["event_published_at"])
            for u, (score, factors) in zip(updates, scored)]
    with db.cursor() as cursor:
        cursor.executemany(SAVE, rows)
    db.commit()


def main():
    model, version = load_model(os.environ["MODEL_PATH"])
    consumer = Consumer({"bootstrap.servers": os.environ["KAFKA_BROKERS"], "group.id": "scoring",
                         "auto.offset.reset": "earliest", "enable.auto.commit": False,
                         "session.timeout.ms": 10000})  # a killed scorer's partitions move on after this long
    consumer.subscribe([TOPIC])
    print(f"scoring with model {version}", flush=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        while True:
            messages = consumer.consume(MAX_BATCH, timeout=0.2)
            if not messages:
                continue
            for message in messages:
                if message.error():
                    raise RuntimeError(message.error())
            updates = [json.loads(message.value()) for message in messages]
            save(db, updates, score_updates(updates, model), version)
            consumer.commit(asynchronous=False)


if __name__ == "__main__":
    main()
