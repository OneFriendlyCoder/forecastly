# Pipeline Pulse: Replay Tool

The replay tool plays saved simulator events into Kafka as if they were happening live. It stands in for real data sources such as a CRM, so the rest of the pipeline can run without any real customer data.

```text
events.parquet -> replay.py -> Kafka (activity.events) -> Go deal-state service
```

The tool only knows about Kafka, and readers only know about Kafka. A real source could replace it by writing to the same topic.

## How to run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r ml/requirements.txt
make up

.venv/bin/python ml/simulator/replay.py                        # 1 simulated day = 1 second
.venv/bin/python ml/simulator/replay.py --seconds-per-day 0.5  # faster
.venv/bin/python ml/simulator/replay.py --fast                 # no pauses
.venv/bin/python ml/simulator/replay.py --limit 1000           # first 1,000 events
.venv/bin/python ml/simulator/replay.py --fast --faults        # inject faults
.venv/bin/python ml/simulator/replay.py --fast --scale 3       # 3 copies of every deal
.venv/bin/python ml/simulator/replay.py --scale 2 --profile 30:2000,10:50000,60:2000  # burst
.venv/bin/python ml/simulator/test_replay.py                   # checks
```

At 1 simulated day = 1 second, the full history takes about 7 minutes.

## How it works

1. Reads events in time order.
2. Waits until each event is due, based on the speed setting.
3. Sends it as JSON, using `deal_id` as the key, so each deal stays on one partition and in order.
4. Stops with an error if any event fails to deliver.

## Fault injection

`--faults` changes what goes into Kafka, using a fixed seed so every run injects the same faults.

| Fault | Share of events | What it does |
|---|---|---|
| Duplicates | 2% | Sends an extra exact copy shortly after |
| Late | 2% | Sends the event up to 5,000 positions later |
| Broken | 0.1% | Adds a corrupted copy: cut short, or with a wrong `schema_version` |

Every real event is still sent, so the final deal state must not change. `make test-faults` proves that, as described in [deal_state.md](deal_state.md).

## Load settings

- **`--scale N`:** repeats every deal N times under new deal and event ids, so volume grows without creating duplicates.
- **`--profile`:** sets the send rate directly. `30:2000,10:50000` means 30 seconds at 2,000 events/s, then 10 seconds at 50,000. It ignores event times and needs enough events to fill the profile.

`make load-test` uses both. The results are in [deal_state.md](deal_state.md).

## Things to know

- **Repeat runs add events:** each run sends everything again. Run `make reset`, then `make up`, for an empty topic.
- **Fault runs break the send order on purpose:** late events can arrive out of order, so `--faults` isn't meant for checking order.
- **Throughput:** the first test run sent about 136,000 events per second. That only measures sending to Redpanda on a laptop, not the whole pipeline.

## What the checks confirm

`test_replay.py` uses temporary topics, so `activity.events` stays untouched. It confirms that:

- All 439,821 events arrive exactly once.
- Each deal's events arrive in order.
- Each deal stays on one partition.
- The first 5,000 received events match the schema.
- The speed setting is respected.
