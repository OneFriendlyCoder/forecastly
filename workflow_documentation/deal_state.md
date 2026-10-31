# Pipeline Pulse: Deal-State Service

The deal-state service is a Go program that reads activity events from Kafka and keeps a live record of each deal in Postgres. It's the first part of the pipeline that processes events as they arrive.

```text
replay tool -> Kafka (activity.events) -> deal-state -> Postgres
                                              |
                                              v
                                    activity.events.dlq (broken events)
```

## How to run it

```bash
make up        # starts Redpanda, Postgres and the service
make test      # unit tests and generator checks
make test-e2e  # full test, wipes local Kafka and Postgres data first

.venv/bin/python ml/simulator/replay.py --limit 1000  # send some events
make down      # stop everything, keep the data
```

## How it works

1. Reads up to 2,000 events at a time from Kafka.
2. Checks each event against the shared contract, `schemas/event.v1.json`.
3. Sends any broken event to `activity.events.dlq`, with the reason in a header.
4. Saves valid events and updates their deal counts in one Postgres transaction.
5. Only then tells Kafka those events are done.

If the service crashes before step 5, it reads those events again after restarting.

## Tables

| Table | Holds |
|---|---|
| `events` | Every event once, with `event_id` as the primary key |
| `deal_health` | One row per deal: a count per event type, plus the latest event |

## Reliability

Kafka can deliver the same event more than once, so the service has to tolerate repeats. Inserting an event and adding to its count happen in one SQL statement. If `event_id` already exists, nothing is inserted and nothing is counted.

Together, these give "at-least-once delivery with idempotent processing": no event is lost, and a repeat changes nothing.

| Problem | What happens |
|---|---|
| Same event delivered twice | Ignored, because `event_id` already exists |
| Service crashes mid-batch | Postgres rolls back or the batch is read again, and repeats are ignored |
| Broken event | Goes to the dead-letter topic, and the service keeps running |
| Postgres or Kafka failure | The service exits and Docker restarts it. It then reads uncommitted events again |

Before saving, the service rejects anything Postgres would refuse, such as a bad date or a NUL character. Otherwise one bad message would crash the service on every restart.

## What the tests confirmed

| Test | Result |
|---|---|
| First replay | All 439,821 events stored across 8,300 deals, with every deal's counts exact |
| Replaying everything again | Nothing changed |
| 4 broken events | All reached the dead-letter topic, and counts stayed the same |
| Unit tests | 8 kinds of bad message rejected |

The first pass took about 31 seconds, or roughly 14,000 events per second. That's a first measurement on a laptop, with one consumer and no scoring.

## Differences from the project plan

- **No `processed_events` table:** the `events` primary key already prevents duplicates.
- **`events` isn't split by month:** this isn't needed at this size.
- **Typed count columns:** `deal_health` uses a column per event type, not a `features` JSON field.
- **No `deal.features` topic yet:** this comes with the scoring step.
