# Live Features and Scoring

This step turns the saved model into a running system. An event arrives, the deal's features update, and a fresh score lands in Postgres.

```text
activity.events -> deal-state -> deal.features -> Python scoring -> Postgres: deal_scores
```

## How it works

1. `deal-state` saves a batch of events, then runs `services/deal-state/features.sql` for each deal in that batch.
2. It publishes one update per deal to `deal.features`, keyed by `deal_id`. If 50 events for a deal arrive together, one update goes out.
3. `ml/scoring/score.py` reads the updates, runs the model, and saves to `deal_scores`.

Each score stores the top 3 factors behind it, the features it used, and a model version taken from the model file's hash. A positive factor impact raises the chance of winning.

The `deals` table holds product and amount, which events don't carry. It acts as the CRM record, and `make up` fills it using `services/deal-state/seed_deals.py`.

The model file comes from `make train` and is mounted read-only into the scoring container, so `make train` must run before `make up`.

## Which deals get scored

- A deal is scored only if it is open and at least 7 days past engagement, because the model has no training examples younger than that.
- "Now" is the time of the deal's latest event, because replayed events are years old.
- A deal not in the `deals` table gets no score.

## Crash and duplicate safety

Delivery is at-least-once. `deal-state` commits its Kafka offsets after saving and publishing, and it publishes even if every event in the batch was a redelivery. A crash between those steps loses nothing.

The scorer commits offsets after Postgres commits. The `deal_scores` primary key is deal, moment and model version, so a redelivery overwrites the same row.

## Proof

`make test-scoring` runs against the real stack and wipes local data.

| Check | Result |
|---|---|
| SQL and Python features match | 3,000 live updates match `build_features` |
| Live and saved model scores match | Same 3,000 updates match |
| Who gets scored | No scores under 7 days old or after a close |
| Unseen deals, scored up to day 30 | AUC of 0.61 to 0.62 across two runs |
| Faults and kills | 1,588 open deals end on identical scores, with about 18,000 injected faults and 6 forced kills |

The test deliberately fails if the features drift. Changing one SQL window from 14 to 15 days was caught at once: `emails_sent_14d` read 11 live and 10 in training code.

The test compares open deals only. Which moment a closed deal was last scored depends on how its events were batched, so run totals also vary slightly (about 68,000 scores across 5,900 deals).

## Speed

These are from `make load-test`, on one laptop in Docker. **They were measured on the Go version of `deal-state`.** The Python version needs a new load test, and it should be slower: a first replay took 124 seconds, or about 3,500 events/s. Full figures are in `data/load_test_results.json`.

| Scenario | Consumers | Throughput | p95 event to score |
|---|---|---|---|
| Target rate (1M events/hour) | 1 | 278/s, the rate requested | 0.237 s |
| As fast as possible | 1 | 7,597/s | 153 s |
| As fast as possible | 3 | 10,824/s | 112 s |
| Burst | 1 | Not a limit test | 50 s |

The plan's under-2-second target is met at the target rate, with a worst case of 0.374 s. In the other runs, the latency is mostly time waiting in the backlog.

Calculating features cost a lot of throughput. It fell from 11,888/s to 7,597/s with one consumer, and from 24,199/s to 10,824/s with three. The plan's target rate is still far below these numbers.

## Limits

- **Quiet deals aren't rescored:** a deal with no new events keeps its old score, even though going quiet is a warning sign. A real deployment would need a periodic rescore.
- **Very young deals have no score.** Deals that close within 7 days are never scored.
- **Scoring isn't scaled out.** There is one scorer, and it read 100% CPU in one sample of the 3-consumer run. The scorer can run as several copies, but we haven't tested that.
- **Outages are untested:** we killed the services, but not Postgres or Redpanda.
- **`deal.features` has no schema contract.** Only our own code writes to it, and the feature comparison test covers the fields.

## Differences from the project plan

- **No `deal.scores` topic:** nothing would read it yet, so it can wait for the API.
- **No MLflow:** the file hash records which model made each score.
- **No isotonic calibration:** the model's calibration already looks good.
- **No time-based evaluation:** we split by deal, for the reason in [model.md](model.md).
