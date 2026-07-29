import sqlite3
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score

conn = sqlite3.connect("data/processed/mta_alerts.sqlite")
df = pd.read_sql_query(
    "SELECT * FROM fct_line_hour_features WHERE is_model_eligible = 1",
    conn,
)
conn.close()

print(f"Loaded {len(df)} rows")

df["prediction_hour_local"] = pd.to_datetime(df["prediction_hour_local"])
df = df.sort_values("prediction_hour_local")

feature_cols = [
    "calendar_month", "day_of_week", "hour_of_day", "is_weekend",
    "scheduled_revenue_stop_departures", "line_history_hours",
    "line_event_starts_prior_1h", "line_event_starts_prior_3h",
    "line_event_starts_prior_6h", "line_event_starts_prior_24h",
    "line_positive_rate_prior_7d", "line_positive_rate_prior_30d",
    "hours_since_line_disruption", "system_event_line_starts_prior_1h",
    "system_event_line_starts_prior_3h", "system_event_line_starts_prior_6h",
    "system_event_line_starts_prior_24h", "system_positive_line_rate_prior_7d",
]
target_col = "significant_disruption_next_hour"

df[feature_cols] = df[feature_cols].fillna(0)

cutoff = df["prediction_hour_local"].quantile(0.8)
train = df[df["prediction_hour_local"] <= cutoff]
test = df[df["prediction_hour_local"] > cutoff]

print(f"Train rows: {len(train)}, Test rows: {len(test)}")

model = LogisticRegression(max_iter=1000, class_weight="balanced")
model.fit(train[feature_cols], train[target_col])

probs = model.predict_proba(test[feature_cols])[:, 1]

for threshold in [0.5, 0.6, 0.7, 0.8]:
    preds = (probs >= threshold).astype(int)
    print(f"\n--- confidence needed: {threshold} ---")
    print("Accuracy:", accuracy_score(test[target_col], preds))
    print("Precision:", precision_score(test[target_col], preds, zero_division=0))
    print("Recall:", recall_score(test[target_col], preds, zero_division=0))
