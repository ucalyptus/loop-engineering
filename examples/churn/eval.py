"""Check: train on data/train.csv, score data/holdout.csv, require holdout AUC >= --min-auc.

Loop sensor: the agent must not edit this file or the data.
"""

import argparse
import sys

from churn.data import labels, load
from churn.features import encode
from churn.model import auc, predict_proba, train

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--min-auc", type=float, required=True)
    args = p.parse_args()

    train_rows, holdout_rows = load("train"), load("holdout")
    model = train([encode(r) for r in train_rows], labels(train_rows))
    score = auc([predict_proba(model, encode(r)) for r in holdout_rows], labels(holdout_rows))
    print(f"holdout AUC {score:.4f} (min {args.min_auc})")
    sys.exit(0 if score >= args.min_auc else 1)
