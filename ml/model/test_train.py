"""Run with: python3 ml/model/test_train.py"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from train import ALL, MODEL_PATH, load_snapshots, run, score, split_by_deal

MAX_BELIEVABLE_AUC = 0.9


def check_split(snapshots):
    train, test = split_by_deal(snapshots)
    assert not set(train["deal_id"]) & set(test["deal_id"]), "a deal is on both sides"
    assert len(train) + len(test) == len(snapshots)


def check_same_seed_same_scores(snapshots, model):
    again, _ = run(snapshots)
    assert (score(model, snapshots, ALL) == score(again, snapshots, ALL)).all()


def check_saved_model(snapshots, model, tmp=MODEL_PATH.with_suffix(".test.txt")):
    tmp.parent.mkdir(exist_ok=True)
    model.booster_.save_model(tmp)
    loaded = lgb.Booster(model_file=tmp)
    tmp.unlink()
    assert np.allclose(loaded.predict(snapshots[ALL]), score(model, snapshots, ALL))


def check_scores(results):
    for name, numbers in results["models"].items():
        assert numbers["auc"] > 0.5, f"{name} is no better than a coin flip"
        assert numbers["auc"] < MAX_BELIEVABLE_AUC, f"{name} is too good, look for a leak"


def check_leak_alarm(snapshots):
    leaked = snapshots.assign(replies_14d=snapshots["won"].astype(int))
    try:
        check_scores(run(leaked)[1])
    except AssertionError as error:
        assert "leak" in str(error)
    else:
        raise AssertionError("a leaked result must trip the alarm")


def main():
    snapshots = load_snapshots()
    check_split(snapshots)
    model, results = run(snapshots)
    check_scores(results)
    check_same_seed_same_scores(snapshots, model)
    check_saved_model(snapshots, model)
    check_leak_alarm(snapshots)
    print(f"all model checks passed, test AUC {results['models']['lightgbm_all_features']['auc']}")


if __name__ == "__main__":
    main()
