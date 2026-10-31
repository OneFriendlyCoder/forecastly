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
make test-faults  # clean-vs-faults proof, wipes local data several times

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
| Events arrive late or out of order | Counts are unaffected, and the latest event is chosen by event time, with `event_id` breaking ties |
| Service killed outright | Kafka moves its work to the restarted service after a 10-second session timeout |

Before saving, the service rejects anything Postgres would refuse, such as a bad date or a NUL character. Otherwise one bad message would crash the service on every restart.

## What the tests confirmed

| Test | Result |
|---|---|
| First replay | All 439,821 events stored across 8,300 deals, with every deal's counts exact |
| Replaying everything again | Nothing changed |
| 4 broken events | All reached the dead-letter topic, and counts stayed the same |
| Unit tests | 8 kinds of bad message rejected |

The first pass took about 30 seconds, or roughly 15,000 events per second. That's a first measurement on a laptop, with one consumer and no scoring.

## Clean-vs-faults proof

`make test-faults` processes the same 439,821 events three times, starting empty each time. Every run must end with an identical `deal_health` table and identical stored events.

| Run | What happened | Result |
|---|---|---|
| Clean | No faults | Used as the baseline |
| Faults | 8,859 duplicates, 8,762 late events and 433 broken events | Identical to clean, and all 433 reached the dead-letter topic |
| Faults and kills | The same faults, plus 3 forced kills at 25%, 50% and 75% progress | Identical to clean, and recovered in 62 seconds in total |

The kill run works by reading unfinished batches again after a restart. It doesn't measure how many events were actually read twice.

Building this test found two problems:

- **Slow recovery:** after a kill, Kafka waited up to 45 seconds to move the dead consumer's work, so the session timeout is now 10 seconds.
- **Misleading backlog:** Kafka reports a backlog of 0 while it's reassigning work. Tests now trust that number only when the consumer group is stable.

## Differences from the project plan

- **No `processed_events` table:** the `events` primary key already prevents duplicates.
- **`events` isn't split by month:** this isn't needed at this size.
- **Typed count columns:** `deal_health` uses a column per event type, not a `features` JSON field.
- **No `deal.features` topic yet:** this comes with the scoring step.
