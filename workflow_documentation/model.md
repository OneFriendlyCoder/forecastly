# Model

The model estimates the chance a deal will be won, using the features in [features.md](features.md). It is trained on snapshots of finished deals. This step doesn't score live deals yet.

Because the activity data is simulated, these results show that the pipeline works. They don't show that it can predict real sales.

## How it works

- `ml/model/train.py` trains three models and evaluates them. Run it with `make train`.
- `ml/model/test_train.py` runs as part of `make test`.
- `data/model_results.json` holds the full results and is committed.
- `data/models/deal_model.txt` is the saved LightGBM model. It is git-ignored and rebuilt by `make train`.

Run `make snapshots` before `make train`. `make test` does this for you.

## Train and test split

The file is split by deal, 80% for training and 20% for testing, with a fixed seed. All of a deal's rows stay on one side, because they are nearly identical and would otherwise inflate the test score.

We don't split by date. Deals that started near the end of the data only count if they finished quickly, which would skew the test set.

The test set is a held-back part of the training file, not a separate dataset. It is used in one batch and doesn't stream.

## Results

All scores are from the test set. AUC runs from 0.5 for a coin flip to 1.0 for perfect.

| Model | Overall | Day 7 | Day 14 | Day 30 | Day 60 | Day 90 |
|---|---|---|---|---|---|---|
| Baseline (logistic regression), all features | 0.653 | 0.564 | 0.592 | 0.661 | 0.776 | 0.753 |
| LightGBM, real fields only | 0.518 | 0.502 | 0.508 | 0.512 | 0.514 | 0.502 |
| LightGBM, all features | 0.653 | 0.572 | 0.595 | 0.654 | 0.760 | 0.763 |

- **Real fields only:** product, amount and deal age predict almost nothing. Nearly all the signal comes from simulated activity, which the simulator built from the known outcomes.
- **Later checkpoints:** scores rise with deal age because simulated activity moves closer to the outcome over time.
- **Overfitting:** LightGBM scores 0.717 on training data and 0.653 on test data. The baseline scores about the same on both.
- **Calibration:** the probabilities are reliable. Deals scored around 83% won 84% of the time, and those around 52% won 52%. The largest gap is about 4 points, in the 63% group.

## Why LightGBM, given the tie

LightGBM was meant to beat the baseline and didn't. Across 5 further splits, the baseline averaged 0.641 and LightGBM 0.639, with LightGBM winning 2 of the 5.

We kept LightGBM anyway. It is the model the plan names, it handles missing values on its own, and it can give per-deal reasons for the agent. It is also more likely to help on real data with more complex patterns. Logistic regression would be an equally accurate and simpler choice on this data.

## Tests

- No deal appears on both sides of the split.
- The same seed gives identical scores.
- A saved model reloads and gives the same predictions.
- Every model must beat a coin flip and stay under an AUC of 0.9.
- Feeding the outcome in as a feature must trip that leak check.

## Limits

- **No tuning:** the settings are fixed, because tuning simulated data wouldn't show much.
- **Not deployed:** the model is only a file. The scoring service will load it in the next step.
- **Very short deals:** deals that closed within 7 days aren't in the training data, so scores on deals younger than 7 days aren't backed by any examples.
