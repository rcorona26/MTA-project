"""
Train and compare classifiers for significant_disruption_next_hour.

Three models, in increasing sophistication:
1. Historical-rate baseline (no ML): use the line's own trailing 30-day
   positive rate as the predicted probability. This is the reference point
   any real model needs to beat.
2. Logistic regression: scaled numeric features + one-hot encoded line.
3. HistGradientBoostingClassifier: same features, no scaling needed, and it
   handles the class imbalance and nonlinearity better.

Split is chronological (train / val / test by time, not shuffled), since
this is a forecasting problem and shuffling would leak the future into
training. The decision threshold is tuned on validation, then evaluated once
on the held-out test set.
"""

import sqlite3

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

NUMERIC_FEATURES = [
    "calendar_month", "day_of_week", "hour_of_day", "is_weekend",
    "scheduled_revenue_stop_departures", "line_history_hours",
    "line_event_starts_prior_1h", "line_event_starts_prior_3h",
    "line_event_starts_prior_6h", "line_event_starts_prior_24h",
    "line_positive_rate_prior_7d", "line_positive_rate_prior_30d",
    "hours_since_line_disruption", "system_event_line_starts_prior_1h",
    "system_event_line_starts_prior_3h", "system_event_line_starts_prior_6h",
    "system_event_line_starts_prior_24h", "system_positive_line_rate_prior_7d",
]
TARGET_COL = "significant_disruption_next_hour"


def load_data():
    conn = sqlite3.connect("data/processed/mta_alerts.sqlite")
    df = pd.read_sql_query(
        "SELECT * FROM fct_line_hour_features WHERE is_model_eligible = 1",
        conn,
    )
    conn.close()

    df["prediction_hour_local"] = pd.to_datetime(df["prediction_hour_local"])
    df = df.sort_values("prediction_hour_local").reset_index(drop=True)
    df[NUMERIC_FEATURES] = df[NUMERIC_FEATURES].fillna(0)
    return df


def chronological_split(df):
    train_cutoff = df["prediction_hour_local"].quantile(0.70)
    val_cutoff = df["prediction_hour_local"].quantile(0.85)
    train = df[df["prediction_hour_local"] <= train_cutoff]
    val = df[
        (df["prediction_hour_local"] > train_cutoff)
        & (df["prediction_hour_local"] <= val_cutoff)
    ]
    test = df[df["prediction_hour_local"] > val_cutoff]
    return train, val, test


def best_threshold_by_f1(y_true, probs):
    best_t, best_f1 = 0.5, -1
    for t in [i / 100 for i in range(5, 96)]:
        preds = (probs >= t).astype(int)
        f1 = f1_score(y_true, preds, zero_division=0)
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    return best_t


def report(name, y_true, probs, threshold):
    preds = (probs >= threshold).astype(int)
    print(f"\n=== {name} (threshold={threshold:.2f}) ===")
    print(f"PR-AUC (average precision): {average_precision_score(y_true, probs):.4f}")
    print(f"ROC-AUC:                    {roc_auc_score(y_true, probs):.4f}")
    print(f"Accuracy:                   {accuracy_score(y_true, preds):.4f}")
    print(f"Precision:                  {precision_score(y_true, preds, zero_division=0):.4f}")
    print(f"Recall:                     {recall_score(y_true, preds, zero_division=0):.4f}")
    print(f"F1:                         {f1_score(y_true, preds, zero_division=0):.4f}")


def main():
    df = load_data()
    print(f"Loaded {len(df)} model-eligible rows")

    train, val, test = chronological_split(df)
    print(f"Train: {len(train)}  Val: {len(val)}  Test: {len(test)}")
    print(f"Positive rate — train: {train[TARGET_COL].mean():.4f}, "
          f"val: {val[TARGET_COL].mean():.4f}, test: {test[TARGET_COL].mean():.4f}")

    # --- 1. Historical-rate baseline (no model at all) ---
    baseline_val_probs = val["line_positive_rate_prior_30d"].fillna(0)
    baseline_threshold = best_threshold_by_f1(val[TARGET_COL], baseline_val_probs)
    baseline_test_probs = test["line_positive_rate_prior_30d"].fillna(0)
    report("Historical-rate baseline", test[TARGET_COL], baseline_test_probs, baseline_threshold)

    # --- Shared feature matrices (numeric + one-hot line) ---
    line_dummies_train = pd.get_dummies(train["line"], prefix="line")
    line_dummies_val = pd.get_dummies(val["line"], prefix="line").reindex(
        columns=line_dummies_train.columns, fill_value=0
    )
    line_dummies_test = pd.get_dummies(test["line"], prefix="line").reindex(
        columns=line_dummies_train.columns, fill_value=0
    )

    X_train = pd.concat([train[NUMERIC_FEATURES].reset_index(drop=True), line_dummies_train.reset_index(drop=True)], axis=1)
    X_val = pd.concat([val[NUMERIC_FEATURES].reset_index(drop=True), line_dummies_val.reset_index(drop=True)], axis=1)
    X_test = pd.concat([test[NUMERIC_FEATURES].reset_index(drop=True), line_dummies_test.reset_index(drop=True)], axis=1)
    y_train = train[TARGET_COL].reset_index(drop=True)
    y_val = val[TARGET_COL].reset_index(drop=True)
    y_test = test[TARGET_COL].reset_index(drop=True)

    # --- 2. Logistic regression (scaled) ---
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    logreg = LogisticRegression(max_iter=1000, class_weight="balanced")
    logreg.fit(X_train_scaled, y_train)

    logreg_val_probs = logreg.predict_proba(X_val_scaled)[:, 1]
    logreg_threshold = best_threshold_by_f1(y_val, logreg_val_probs)
    logreg_test_probs = logreg.predict_proba(X_test_scaled)[:, 1]
    report("Logistic regression (scaled)", y_test, logreg_test_probs, logreg_threshold)

    # --- 3. Gradient boosting ---
    gbc = HistGradientBoostingClassifier(
        max_iter=300,
        max_depth=6,
        learning_rate=0.05,
        class_weight="balanced",
        random_state=42,
    )
    gbc.fit(X_train, y_train)

    gbc_val_probs = gbc.predict_proba(X_val)[:, 1]
    gbc_threshold = best_threshold_by_f1(y_val, gbc_val_probs)
    gbc_test_probs = gbc.predict_proba(X_test)[:, 1]
    report("Gradient boosting", y_test, gbc_test_probs, gbc_threshold)

    # HistGradientBoostingClassifier has no built-in feature_importances_,
    # so use permutation importance on a test subsample (average precision
    # drop when a feature's values are shuffled).
    sample_idx = X_test.sample(n=min(20000, len(X_test)), random_state=42).index
    perm = permutation_importance(
        gbc, X_test.loc[sample_idx], y_test.loc[sample_idx],
        scoring="average_precision", n_repeats=3, random_state=42, n_jobs=-1,
    )
    importances = pd.Series(perm.importances_mean, index=X_train.columns)
    print("\n=== Gradient boosting permutation importance (top 10) ===")
    print(importances.sort_values(ascending=False).head(10))

    joblib.dump(
        {"model": gbc, "feature_columns": list(X_train.columns), "threshold": gbc_threshold},
        "disruption_gbc_model.joblib",
        compress=3,
    )
    print("\nSaved best model to disruption_gbc_model.joblib")


if __name__ == "__main__":
    main()
