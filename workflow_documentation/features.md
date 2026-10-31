# Features and Training Data

The model can't read a raw event history, so this step summarises each deal as a row of numbers. The rule is that a row may only use what was known on that day. Breaking this is called data leakage: the model looks great in testing because it has seen the answer, then fails on live deals.

## How it works

```text
events.parquet + deals.parquet
        |
        v
build_snapshots.py: pick the checkpoints for each finished deal
        |
        v
features.py: build_features(events, as_of)
        |
        v
training_snapshots.parquet
```

- `ml/features/features.py` holds `build_features(events, as_of)`. It drops everything after `as_of` before calculating anything.
- `ml/features/build_snapshots.py` builds the training file. Run it with `make snapshots`.
- `ml/features/test_features.py` runs as part of `make test`.

## Features

All windows are the 14 days up to and including `as_of`. Other counts cover the whole deal so far.

| Feature | Meaning |
|---|---|
| `days_since_engaged` | Age of the deal |
| `emails_sent_14d` | Rep emails sent recently |
| `replies_14d` | Buyer replies recently |
| `meetings_14d` | Meetings held recently |
| `days_since_last_reply` | Empty if the buyer has never replied |
| `median_reply_hours` | Typical reply delay. Empty if there are no replies |
| `negative_replies` | Replies with negative sentiment |
| `contacts_added` | Buyers added to the deal |
| `buyers_replied` | Different buyers who have replied |
| `no_shows` | Missed meetings |
| `close_date_pushes` | Times the close date moved |

`build_snapshots.py` also adds `product` and `amount` from the deal table.

## Training file

There is one row per finished deal at days 7, 14, 30, 60 and 90 after engagement. A checkpoint on or after the close date is skipped, because that row would already know the result. Open deals are left out because they have no result.

The file has 17,088 rows from 5,298 deals. `data/simulated/` is git-ignored, so `make snapshots` rebuilds it.

| Checkpoint | Rows | Share won |
|---|---|---|
| Day 7 | 5,298 | 65.7% |
| Day 14 | 3,905 | 68.7% |
| Day 30 | 3,548 | 68.2% |
| Day 60 | 2,979 | 68.6% |
| Day 90 | 1,358 | 71.1% |

`deal_id` is kept so the model step can put all of a deal's rows on the same side of the train/test split. Otherwise, nearly identical rows would inflate the test score.

## Tests

- **Known answer:** a small hand-written deal must produce exact values.
- **Leakage:** on 300 real deals, a checkpoint's features must not change when the deal's own later events or fake future events of every type are added.
- **Delivery problems:** duplicates and shuffled events must not change the features. `event_id` removes duplicates, and counts and latest times don't depend on order.
- **Training file:** no row at or after the close, no repeated checkpoints, and day counts must match.
- **No giveaway feature:** no single feature may reach an AUC of 0.9. The strongest is `replies_14d` at 0.575.

We also removed the date cutoff and the 14-day window by hand, one at a time. The tests failed both times, which shows they can catch these mistakes.

## Decisions and limits

- **Account fields are left out.** `account_id` is missing on 68% of open deals but never on finished ones, so a model trained on finished deals would never see that gap.
- **`amount` is safe.** It is always the list price, whichever way the deal ends. `close_value` would leak the result, so it isn't used.
- **Close-date pushes are safe but weak.** The expected date is drawn without looking at the real close date. Pushes barely separate won from lost deals (AUC 0.501).
- **Very short deals are missing.** The 1,413 finished deals that closed within 7 days have no checkpoint, so the model doesn't learn from them.
- **Live features aren't covered yet.** The Go service will calculate these features in the scoring step, and that step needs a test that both versions agree on the same events.
