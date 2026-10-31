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
.venv/bin/python ml/simulator/test_replay.py                   # checks
```

At 1 simulated day = 1 second, the full history takes about 7 minutes.

## How it works

1. Reads events in time order.
2. Waits until each event is due, based on the speed setting.
3. Sends it as JSON, using `deal_id` as the key, so each deal stays on one partition and in order.
4. Stops with an error if any event fails to deliver.

## Things to know

- **Repeat runs add events:** each run sends everything again. Run `make reset`, then `make up`, for an empty topic.
- **No faults yet:** this version sends clean events only.
- **Throughput:** the first test run sent about 136,000 events per second. That only measures sending to Redpanda on a laptop, not the whole pipeline.

## What the checks confirm

`test_replay.py` uses temporary topics, so `activity.events` stays untouched. It confirms that:

- All 439,821 events arrive exactly once.
- Each deal's events arrive in order.
- Each deal stays on one partition.
- The first 5,000 received events match the schema.
- The speed setting is respected.
