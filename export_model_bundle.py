"""
Export the fitted gradient boosting model for exact in-browser inference.

The dashboard runs the real model client-side rather than approximating it or
calling a server. This transpiles disruption_gbc_model.joblib into a compact
JSON tree structure, and exports the test-set score distributions needed to
recompute the confusion matrix at any decision threshold.

Two payloads are written:

- docs/model_bundle.json  trees, feature order, reference scenario, and the
                          score histograms behind the threshold explorer.

Run after train_classifier.py, before build_dashboard.py.
"""

import json
import sqlite3

import joblib
import numpy as np
import pandas as pd

from train_classifier import (
    NUMERIC_FEATURES,
    TARGET_COL,
    best_threshold_by_f1,
    chronological_split,
    load_data,
)

MODEL_PATH = "disruption_gbc_model.joblib"
OUTPUT_PATH = "docs/model_bundle.json"
DATABASE = "data/processed/mta_alerts.sqlite"

# Threshold explorer resolution. 1000 bins over [0, 1] means the confusion
# matrix is exact to a threshold of 0.001, which is finer than the slider.
BINS = 1000


def export_trees(model):
    """Flatten HistGradientBoostingClassifier into JSON-serializable trees.

    Each node is [feature_idx, threshold, left, right, missing_go_to_left] for
    internal nodes, or [-1, leaf_value, 0, 0, 0] for leaves. Traversal in the
    browser mirrors sklearn's: go left when x <= threshold, and route NaN by
    missing_go_to_left. No categorical splits exist in this model, so bitset
    handling is not needed.

    Split thresholds are emitted at full float precision on purpose. Rounding
    them is not a small numeric error: a threshold sits at a real data value,
    so shaving a decimal flips the comparison and sends the row down a
    different subtree entirely. Rounding to 6dp moved test probabilities by up
    to 0.036. Leaf values are additive and safely rounded.
    """
    trees = []
    for iteration in model._predictors:
        # Binary classification: one predictor per iteration.
        nodes = iteration[0].nodes
        flat = []
        for node in nodes:
            if node["is_leaf"]:
                flat.append([-1, round(float(node["value"]), 9), 0, 0, 0])
            else:
                flat.append([
                    int(node["feature_idx"]),
                    float(node["num_threshold"]),
                    int(node["left"]),
                    int(node["right"]),
                    int(node["missing_go_to_left"]),
                ])
        trees.append(flat)
    return trees


def reference_scenario(train, feature_columns):
    """Baseline input the predictor starts from and attributes against.

    Medians over the training period for the dynamic features, so a user's
    change to one input reads as "relative to a typical hour" rather than
    relative to an arbitrary zero.
    """
    ref = {}
    for name in NUMERIC_FEATURES:
        ref[name] = round(float(train[name].median()), 6)
    # Calendar fields: a median month is meaningless, so pin a concrete,
    # explainable default (Wednesday, 8am, weekday, June).
    ref["calendar_month"] = 6
    ref["day_of_week"] = 3
    ref["hour_of_day"] = 8
    ref["is_weekend"] = 0
    for name in feature_columns:
        if name.startswith("line_") and name not in ref:
            ref[name] = 0
    return ref


def per_line_profile(train):
    """Typical feature values for each line, so selecting a line in the UI
    moves the line-specific inputs to that line's real operating point."""
    cols = [
        "scheduled_revenue_stop_departures", "line_history_hours",
        "line_event_starts_prior_1h", "line_event_starts_prior_3h",
        "line_event_starts_prior_6h", "line_event_starts_prior_24h",
        "line_positive_rate_prior_7d", "line_positive_rate_prior_30d",
        "hours_since_line_disruption",
    ]
    profile = {}
    for line, group in train.groupby("line"):
        profile[line] = {c: round(float(group[c].median()), 6) for c in cols}
    return profile


def score_histograms(y_true, probs):
    """Counts of positive and negative test rows per score bin.

    Cumulative sums from the top give exact TP/FP at any bin edge, which is
    what the threshold explorer needs. Storing 2x1000 integers is far smaller
    than 157,922 raw scores and loses nothing at slider resolution.
    """
    edges = np.linspace(0.0, 1.0, BINS + 1)
    y_true = np.asarray(y_true)
    probs = np.clip(np.asarray(probs), 0.0, 1.0)
    pos, _ = np.histogram(probs[y_true == 1], bins=edges)
    neg, _ = np.histogram(probs[y_true == 0], bins=edges)
    return [int(v) for v in pos], [int(v) for v in neg]


def main():
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    feature_columns = bundle["feature_columns"]

    df = load_data()
    train, val, test = chronological_split(df)

    # Rebuild the exact design matrices train_classifier.py used, so the
    # exported scores match docs/model_results.md rather than approximating it.
    dummies_train = pd.get_dummies(train["line"], prefix="line")
    cols = dummies_train.columns

    def design(frame, dummies):
        return pd.concat(
            [frame[NUMERIC_FEATURES].reset_index(drop=True),
             dummies.reset_index(drop=True)],
            axis=1,
        )

    X_test = design(
        test,
        pd.get_dummies(test["line"], prefix="line").reindex(columns=cols, fill_value=0),
    )
    X_val = design(
        val,
        pd.get_dummies(val["line"], prefix="line").reindex(columns=cols, fill_value=0),
    )
    y_test = test[TARGET_COL].reset_index(drop=True)
    y_val = val[TARGET_COL].reset_index(drop=True)

    assert list(X_test.columns) == feature_columns, "feature order drifted from saved model"

    val_probs = model.predict_proba(X_val)[:, 1]
    test_probs = model.predict_proba(X_test)[:, 1]
    threshold = best_threshold_by_f1(y_val, val_probs)

    pos_hist, neg_hist = score_histograms(y_test, test_probs)

    # Verify the transpiled trees reproduce sklearn before shipping them.
    trees = export_trees(model)
    baseline = float(np.ravel(model._baseline_prediction)[0])
    check = X_test.head(500).to_numpy(dtype=float)
    ours = np.array([predict_python(trees, baseline, row) for row in check])
    theirs = test_probs[:500]
    max_err = float(np.max(np.abs(ours - theirs)))
    print(f"Transpile check: max |JS-path - sklearn| = {max_err:.3e} over 500 rows")
    assert max_err < 1e-5, "transpiled trees disagree with sklearn"

    conn = sqlite3.connect(DATABASE)
    lines = [r[0] for r in conn.execute(
        "SELECT DISTINCT line FROM fct_line_hour_features "
        "WHERE is_model_eligible = 1 ORDER BY line"
    )]
    conn.close()

    payload = {
        "feature_columns": feature_columns,
        "numeric_features": NUMERIC_FEATURES,
        "baseline_prediction": round(baseline, 8),
        "trees": trees,
        "threshold": threshold,
        "lines": lines,
        "reference": reference_scenario(train, feature_columns),
        "line_profile": per_line_profile(train),
        "test_scores": {
            "bins": BINS,
            "positives": pos_hist,
            "negatives": neg_hist,
            "n_pos": int(y_test.sum()),
            "n_neg": int(len(y_test) - y_test.sum()),
        },
    }

    with open(OUTPUT_PATH, "w") as handle:
        json.dump(payload, handle, separators=(",", ":"))

    import os
    size = os.path.getsize(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH} ({size:,} bytes, {len(trees)} trees, "
          f"{sum(len(t) for t in trees):,} nodes)")


def predict_python(trees, baseline, row):
    """Reference implementation of the browser traversal, used to verify the
    export. Kept in Python so the check runs in CI alongside the export."""
    total = baseline
    for tree in trees:
        i = 0
        while True:
            node = tree[i]
            if node[0] == -1:
                total += node[1]
                break
            value = row[node[0]]
            if value != value:  # NaN
                i = node[2] if node[4] else node[3]
            else:
                i = node[2] if value <= node[1] else node[3]
    return 1.0 / (1.0 + np.exp(-total))


if __name__ == "__main__":
    main()
