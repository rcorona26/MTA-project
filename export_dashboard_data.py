"""
Export retrospective dashboard data to JSON.

Reuses the exact split, models, and thresholds from train_classifier.py so the
dashboard reports the same numbers as docs/model_results.md, then adds the
curve data (precision-recall, calibration) that the console report does not
produce.
"""

import json
import sqlite3

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

from train_classifier import (
    NUMERIC_FEATURES,
    TARGET_COL,
    best_threshold_by_f1,
    chronological_split,
    load_data,
)

OUTPUT_PATH = "docs/dashboard_data.json"
DATABASE = "data/processed/mta_alerts.sqlite"


def thin(xs, ys, n=200):
    """Downsample a curve to n points, always keeping the endpoints."""
    if len(xs) <= n:
        idx = range(len(xs))
    else:
        idx = np.unique(np.linspace(0, len(xs) - 1, n).astype(int))
    return [[round(float(xs[i]), 4), round(float(ys[i]), 4)] for i in idx]


def descriptive_stats():
    conn = sqlite3.connect(DATABASE)

    by_line = conn.execute("""
        SELECT line,
               count(*) AS line_hours,
               sum(significant_disruption_next_hour) AS positives,
               avg(significant_disruption_next_hour * 1.0) AS prevalence
        FROM fct_line_hour_features
        WHERE is_model_eligible = 1
        GROUP BY line
        ORDER BY prevalence DESC
    """).fetchall()

    by_hour = conn.execute("""
        SELECT hour_of_day,
               is_weekend,
               avg(significant_disruption_next_hour * 1.0) AS prevalence
        FROM fct_line_hour_features
        WHERE is_model_eligible = 1
        GROUP BY hour_of_day, is_weekend
        ORDER BY hour_of_day
    """).fetchall()

    by_month = conn.execute("""
        SELECT substr(prediction_hour_local, 1, 7) AS month,
               avg(significant_disruption_next_hour * 1.0) AS prevalence,
               count(*) AS line_hours
        FROM fct_line_hour_features
        WHERE is_model_eligible = 1
        GROUP BY month
        ORDER BY month
    """).fetchall()

    conn.close()

    weekday = {h: p for h, w, p in by_hour if w == 0}
    weekend = {h: p for h, w, p in by_hour if w == 1}

    return {
        "by_line": [
            {"line": l, "line_hours": n, "positives": p, "prevalence": round(r, 5)}
            for l, n, p, r in by_line
        ],
        "by_hour": [
            {
                "hour": h,
                "weekday": round(weekday.get(h, 0), 5),
                "weekend": round(weekend.get(h, 0), 5),
            }
            for h in range(24)
        ],
        "by_month": [
            {"month": m, "prevalence": round(r, 5), "line_hours": n}
            for m, r, n in by_month
        ],
    }


def main():
    df = load_data()
    train, val, test = chronological_split(df)

    line_dummies_train = pd.get_dummies(train["line"], prefix="line")
    cols = line_dummies_train.columns

    def design(frame, dummies):
        return pd.concat(
            [frame[NUMERIC_FEATURES].reset_index(drop=True), dummies.reset_index(drop=True)],
            axis=1,
        )

    X_train = design(train, line_dummies_train)
    X_val = design(val, pd.get_dummies(val["line"], prefix="line").reindex(columns=cols, fill_value=0))
    X_test = design(test, pd.get_dummies(test["line"], prefix="line").reindex(columns=cols, fill_value=0))
    y_train = train[TARGET_COL].reset_index(drop=True)
    y_val = val[TARGET_COL].reset_index(drop=True)
    y_test = test[TARGET_COL].reset_index(drop=True)

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)
    X_test_s = scaler.transform(X_test)

    logreg = LogisticRegression(max_iter=1000, class_weight="balanced").fit(X_train_s, y_train)
    gbc = HistGradientBoostingClassifier(
        max_iter=300, max_depth=6, learning_rate=0.05,
        class_weight="balanced", random_state=42,
    ).fit(X_train, y_train)

    models = {
        "Historical-rate baseline": (
            val["line_positive_rate_prior_30d"].fillna(0).to_numpy(),
            test["line_positive_rate_prior_30d"].fillna(0).to_numpy(),
        ),
        "Logistic regression": (
            logreg.predict_proba(X_val_s)[:, 1],
            logreg.predict_proba(X_test_s)[:, 1],
        ),
        "Gradient boosting": (
            gbc.predict_proba(X_val)[:, 1],
            gbc.predict_proba(X_test)[:, 1],
        ),
    }

    results, curves = [], {}
    for name, (val_probs, test_probs) in models.items():
        threshold = best_threshold_by_f1(y_val, val_probs)
        preds = (test_probs >= threshold).astype(int)
        results.append({
            "model": name,
            "threshold": round(threshold, 2),
            "pr_auc": round(float(average_precision_score(y_test, test_probs)), 4),
            "roc_auc": round(float(roc_auc_score(y_test, test_probs)), 4),
            "precision": round(float(precision_score(y_test, preds, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, preds, zero_division=0)), 4),
        })
        precision, recall, _ = precision_recall_curve(y_test, test_probs)
        curves[name] = thin(recall, precision)

    prob_true, prob_pred = calibration_curve(
        y_test, models["Gradient boosting"][1], n_bins=12, strategy="quantile"
    )
    calibration = [
        [round(float(p), 4), round(float(t), 4)] for p, t in zip(prob_pred, prob_true)
    ]

    payload = {
        "meta": {
            "rows": int(len(df)),
            "train_rows": int(len(train)),
            "val_rows": int(len(val)),
            "test_rows": int(len(test)),
            "train_rate": round(float(train[TARGET_COL].mean()), 4),
            "val_rate": round(float(val[TARGET_COL].mean()), 4),
            "test_rate": round(float(test[TARGET_COL].mean()), 4),
            "snapshot_end": str(df["prediction_hour_local"].max())[:10],
            "snapshot_start": str(df["prediction_hour_local"].min())[:10],
        },
        "models": results,
        "pr_curves": curves,
        "calibration": calibration,
        "importance": [
            {"feature": "line_positive_rate_prior_30d", "value": 0.030940},
            {"feature": "hour_of_day", "value": 0.029201},
            {"feature": "day_of_week", "value": 0.010122},
            {"feature": "scheduled_revenue_stop_departures", "value": 0.006944},
            {"feature": "line_positive_rate_prior_7d", "value": 0.005994},
            {"feature": "system_event_line_starts_prior_6h", "value": 0.005055},
            {"feature": "system_event_line_starts_prior_3h", "value": 0.003146},
            {"feature": "hours_since_line_disruption", "value": 0.002832},
        ],
        **descriptive_stats(),
    }

    with open(OUTPUT_PATH, "w") as handle:
        json.dump(payload, handle, indent=1)
    print(f"Wrote {OUTPUT_PATH}")
    for row in results:
        print(row)


if __name__ == "__main__":
    main()
