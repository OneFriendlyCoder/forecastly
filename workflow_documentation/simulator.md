# Pipeline Pulse: Simulator Architecture

This document explains how the simulator is built today. For the data it reads and the assumptions behind it, see [data.md](data.md).

Status: the generator and the replay tool are built and pass their checks, including fault injection.

## Purpose

The simulator gives each deal a believable activity history, then acts as a test tool for the pipeline. Its data only has to be believable. It doesn't need to match real sales behaviour closely.

It has two parts:

| Part | Job | Status |
|---|---|---|
| Generator | Turns deals into a dated list of events | Built |
| Replay tool | Sends those events into Kafka and injects faults | Built |

Keeping them apart means the generator knows nothing about Kafka, and the replay tool knows nothing about deals or health.

## How data flows

```text
data/processed/deals.parquet ------+
ml/simulator/distributions.json ---+--> simulate.py --> data/simulated/
ml/simulator/config.yaml ----------+                      events.parquet
                                                          contacts.parquet
                                                          health_paths.parquet
                                                                |
                                                                v
                                                     replay.py --> Kafka (activity.events)
```

## Files

| File | Job |
|---|---|
| `schemas/event.v1.json` | The event contract, for Python and Go to share |
| `ml/simulator/config.yaml` | Every rate and setting |
| `ml/simulator/distributions.json` | Numbers fitted from real data |
| `ml/simulator/simulate.py` | The generator |
| `ml/simulator/test_simulate.py` | The generator checks |
| `ml/simulator/replay.py` | The replay tool |
| `ml/simulator/test_replay.py` | The replay checks, which need Kafka running |
| `ml/requirements.txt` | Python packages |

To run it from the repo root:

```bash
python3 ml/simulator/simulate.py              # all deals
python3 ml/simulator/simulate.py --limit 100  # a small sample
python3 ml/simulator/test_simulate.py
```

## What goes in

- **Deals:** every deal with an `engaged_at` date, which is 8,300 of 8,800. Prospecting deals are left out because they have no dates.
- **Fitted numbers:** reply delays and weekday pattern from Enron, and deal lengths by product from Maven.
- **Settings:** the seed and all rates. The rates are starting guesses.

## How one deal is generated

`simulate_deal` runs these steps:

1. **Random stream:** build a stream from the seed and `deal_id`.
2. **Story:** pick one of the stories below.
3. **Health:** create the deal's daily health score.
4. **First contact:** add one buyer, 7-21 days before `engaged_at`.
5. **Expected close date:** draw it from typical lengths for the product, never from the real close date.
6. **Daily loop:** roll each activity type for every day until the deal ends.
7. **Ending:** add `deal_closed` with the real outcome if the deal finished.
8. **Finish:** sort events by time and give each one its `event_id`.

### Stories

Health moves toward a target set by the deal's story.

| Story | Who gets it | Health target |
|---|---|---|
| `won` | About 85% of won deals | 0.8 |
| `lost` | About 85% of lost deals | 0.2 |
| `won_messy` | About 15% of won deals | 0.3 |
| `lost_messy` | About 15% of lost deals | 0.8, then a late fall to 0.2 |
| `open` | All 1,589 Engaging deals | 0.5 |

### Health

Health is a hidden daily score from 0 to 1, starting near 0.5. The model never sees it.

```text
health tomorrow = health today
                + (target - health today) × (3 / deal length)
                + small random noise
```

Dividing by deal length means short and long deals both get close to their target by the end. `lost_messy` deals fall after 85% of their length. Open deals have no end, so they use a length of 90 days.

### Daily activity

Each activity depends on health, set by a pair of values in `config.yaml`: one for health 0 and one for health 1. The simulator blends between them.

```text
weekly rate = low value + (high value - low value) × health
daily rate  = weekly rate × rep's activity level × weekday weight / 7
```

| Activity | Health 0 | Health 1 |
|---|---|---|
| Emails per week | 2.5 | 2.5 |
| Chance of a reply | 10% | 60% |
| Meetings per week | 0.1 | 0.7 |
| Chance of a no-show | 30% | 5% |
| New buyers per week | 0.1 | 0.5 |
| Extra close-date pushes per week | 0.4 | 0.02 |

Details:

- **Rep activity:** each rep gets a random activity level, unrelated to outcomes, so a busy rep doesn't look like a healthy deal.
- **Reply delay:** Enron's delay × 4 (buyers are assumed slower) × up to 3 more as health falls, capped at 30 days. A reply due after the deal ends is dropped.
- **Meeting type:** follows progress through the deal: discovery, demo, pricing, then legal. Open deals measure progress against the 138-day maximum.
- **Forced push:** if the expected date passes while the deal is open, the date must move 14-45 days out.
- **Extra push:** can also happen within 14 days of the expected date.
- **Timing:** generated events fall between 9am and 6pm, and weekend activity is rare, following Enron's weekday pattern.

## What comes out

Output goes to `data/simulated/`, which is not in Git.

| File | Holds | Rows in the first run |
|---|---|---|
| `events.parquet` | One row per event, sorted by time | 439,821 |
| `contacts.parquet` | Generated buyers | 27,680 |
| `health_paths.parquet` | Each deal's story and daily health, for debugging only | 8,300 |

## The event contract

Every event uses the same envelope. `actor` and `payload` are stored as JSON text in Parquet.

```json
{
  "event_id": "uuid",
  "event_type": "email_replied",
  "occurred_at": "2017-10-11T17:37:33Z",
  "tenant_id": "demo",
  "deal_id": "03H4RXBI",
  "account_id": "acc_088",
  "actor": {"kind": "contact", "id": "con_03H4RXBI_1", "role": "champion"},
  "payload": {"message_id": "msg_03H4RXBI_5", "reply_delay_hours": 8.05, "sentiment": "positive"},
  "schema_version": 1
}
```

| Event | Payload |
|---|---|
| `email_sent` | `message_id`, `contact_id`, `sequence_step`, `template_id` |
| `email_replied` | `message_id`, `reply_delay_hours`, `sentiment` |
| `meeting_held`, `meeting_no_show` | `meeting_type`, `attendees` |
| `contact_added` | `contact_id`, `role` |
| `close_date_changed` | `old`, `new` |
| `stage_changed` | `from`, `to` |
| `deal_closed` | `outcome`, `amount` |

`account_id` can be empty, because many open deals have no customer.

## Design decisions

| Decision | Why |
|---|---|
| A separate random stream per deal | One deal's result doesn't depend on the others, so runs are repeatable and can be split up later |
| `event_id` built from seed, deal and event number | A rerun gives the same ids, so a duplicate is an exact copy. This suits the idempotency tests |
| `deal_closed` stamped at 23:59:59 on the real date | All of that day's activity falls before the close |
| Expected close date not taken from the real date | Otherwise it would reveal when the deal ends |
| Generator kept separate from Kafka | It can be tested without any infrastructure |
| Settings kept in one file | Rates change without touching code |

## Checks

`test_simulate.py` checks:

- Every event follows the schema, and the schema rejects a bad event.
- Activity stops on the real close date, and open deals stop by 31 December 2017.
- Each finished deal has exactly one `deal_closed`, matching the real outcome and value.
- Real stage dates are unchanged.
- Each deal has 1-6 buyers.
- The same seed gives identical data, and a new seed changes it.
- Early signal, using activity from the first half of each finished deal, falls between 0.55 and 0.95. The first run scored 0.61, where 0.5 is guessing and 1.0 is perfect.

## Replay tool

The replay tool reads `events.parquet` and sends each event to `activity.events` as JSON, using `deal_id` as the key.

```bash
python3 -m venv .venv
.venv/bin/pip install -r ml/requirements.txt
make up

.venv/bin/python ml/simulator/replay.py                        # 1 simulated day = 1 second
.venv/bin/python ml/simulator/replay.py --seconds-per-day 0.5  # faster
.venv/bin/python ml/simulator/replay.py --fast                 # no pauses
.venv/bin/python ml/simulator/replay.py --limit 1000           # first 1,000 events
.venv/bin/python ml/simulator/test_replay.py
```

Fault injection is covered in [replay_tool.md](replay_tool.md).

- **Order:** events go out in time order, and the key keeps each deal on one partition.
- **Partitioning:** it uses the murmur2 method, matching the default in Java and common Go Kafka clients.
- **Safe delivery:** the producer runs in idempotent mode, so a retry can't create a duplicate. The tool stops with an error if any event fails.
- **Repeat runs:** every run adds the events to the topic again. Use `make reset` and `make up` to start from an empty topic.

`test_replay.py` uses temporary topics, so `activity.events` stays empty. It sends all 439,821 events, then checks that every event arrives once, each deal's events arrive in order, and each deal stays on one partition. It validates the first 5,000 received events against the schema, and also checks the speed setting.

The first run sent about 136,000 events per second. That measures sending from the tool to Redpanda on a laptop, not the whole pipeline.

## Known limits

These are accepted for now, because they affect realism and not the pipeline.

- **Close-date pushes run backwards:** won deals average 1.1 pushes and lost deals 0.9. Won deals run longer, so they pass their expected date more often. The fix would be more extra pushes on low-health deals.
- **Open deals look busy:** they average about 70 emails, because they've been open longer than any finished deal and activity never slows. The fix would be slowing activity after 138 days.
- **Rates are guesses:** they aren't fitted to real sales data, and we don't tune them to improve model scores.
- **Run time:** the generator is one process. All 8,300 deals take about 15 seconds, so there's no need for more yet.

## What's next

1. Add traffic bursts and a `--scale` setting that copies deals, for load testing.

See [replay_tool.md](replay_tool.md) for fault injection and [deal_state.md](deal_state.md) for the clean-vs-faults proof.
