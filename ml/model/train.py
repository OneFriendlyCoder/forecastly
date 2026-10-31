"""Trains the deal result model and reports how it does on deals it has never seen."""
import json
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.compose import make_column_transformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "data/simulated/training_snapshots.parquet"
MODEL_PATH = ROOT / "data/models/deal_model.txt"
RESULTS_PATH = ROOT / "data/model_results.json"
SEED = 42

# Fields from the real CRM data. Everything else comes from the simulator.
REAL_NUMBERS = ["amount", "days_since_engaged"]
ACTIVITY = ["emails_sent_14d", "replies_14d", "meetings_14d", "days_since_last_reply", "median_reply_hours",
            "negative_replies", "contacts_added", "buyers_replied", "no_shows", "close_date_pushes"]
REAL = ["product", *REAL_NUMBERS]
ALL = [*REAL, *ACTIVITY]


def load_snapshots():
    snapshots = pd.read_parquet(SNAPSHOTS)
    snapshots["product"] = snapshots["product"].astype("category")
    return snapshots


def split_by_deal(snapshots):
    """A deal's rows are nearly identical, so they must all land on one side."""
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
    train, test = next(splitter.split(snapshots, groups=snapshots["deal_id"]))
    return snapshots.iloc[train], snapshots.iloc[test]


def train_baseline(train):
    numbers = [*REAL_NUMBERS, *ACTIVITY]
    model = make_pipeline(
        make_column_transformer(
            (OneHotEncoder(handle_unknown="ignore"), ["product"]),
            (make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), numbers)),
        LogisticRegression(max_iter=1000))
    return model.fit(train[ALL], train["won"])


def train_lightgbm(train, columns):
    # ponytail: fixed settings, tune them when the data is real
    model = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=50,
                               random_state=SEED, deterministic=True, force_row_wise=True, verbose=-1)
    return model.fit(train[columns], train["won"])


def evaluate(scores, rows):
    actual, predicted = calibration_curve(rows["won"], scores, n_bins=5, strategy="quantile")
    scored = rows.assign(score=scores)
    return {
        "auc": round(roc_auc_score(rows["won"], scores), 4),
        "auc_by_checkpoint": {str(day): round(roc_auc_score(group["won"], group["score"]), 4)
                              for day, group in scored.groupby("checkpoint_day")},
        "calibration": [{"predicted": round(float(p), 3), "actual": round(float(a), 3)}
                        for p, a in zip(predicted, actual)],
    }


def score(model, rows, columns):
    return model.predict_proba(rows[columns])[:, 1]


def run(snapshots):
    train, test = split_by_deal(snapshots)
    models = {"baseline_all_features": (train_baseline(train), ALL),
              "lightgbm_real_only": (train_lightgbm(train, REAL), REAL),
              "lightgbm_all_features": (train_lightgbm(train, ALL), ALL)}
    results = {"train_rows": len(train), "test_rows": len(test), "test_deals": test["deal_id"].nunique(),
               "test_won_share": round(float(test["won"].mean()), 4), "models": {}}
    for name, (model, columns) in models.items():
        results["models"][name] = evaluate(score(model, test, columns), test)
        results["models"][name]["train_auc"] = round(roc_auc_score(train["won"], score(model, train, columns)), 4)
    return models["lightgbm_all_features"][0], results


def main():
    model, results = run(load_snapshots())
    MODEL_PATH.parent.mkdir(exist_ok=True)
    model.booster_.save_model(MODEL_PATH)
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n")
    for name, numbers in results["models"].items():
        print(f"{name}: test AUC {numbers['auc']}, train AUC {numbers['train_auc']}, by day {numbers['auc_by_checkpoint']}")
    print("calibration:", results["models"]["lightgbm_all_features"]["calibration"])


if __name__ == "__main__":
    main()
