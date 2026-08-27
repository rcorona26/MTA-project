# Model results

Baseline and classifier comparison for `significant_disruption_next_hour`,
produced by [`train_classifier.py`](../train_classifier.py) against
`fct_line_hour_features`.

## Setup

- Rows: 1,052,867 model-eligible line-hours (`is_model_eligible = 1`, i.e. the
  line has confirmed scheduled service that hour).
- Split: chronological by `prediction_hour_local`, not shuffled. Train is the
  first 70% of time, validation the next 15%, test the final 15%. Shuffling
  would leak future hours into training on what is a forecasting problem.
- Threshold: tuned for F1 on validation, then applied once to the held-out
  test set. Test was not used for any tuning decision.

| Split | Rows | Positive rate |
|---|---|---|
| Train | 737,020 | 0.1180 |
| Validation | 157,925 | 0.1421 |
| Test | 157,922 | 0.1440 |

Metrics are precision/recall/PR-AUC rather than accuracy. At a ~14% positive
rate, always predicting "no disruption" scores 86% accuracy while being
useless, so accuracy is reported only for completeness.

## Results on the held-out test set

| Model | Threshold | PR-AUC | ROC-AUC | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|
| Historical-rate baseline | 0.15 | 0.2214 | 0.6576 | 0.2008 | 0.6534 | 0.3072 | 0.5755 |
| Logistic regression (scaled) | 0.60 | 0.2502 | 0.6914 | 0.2286 | 0.6390 | 0.3368 | 0.6375 |
| **Gradient boosting** | 0.58 | **0.2566** | **0.7100** | **0.2381** | 0.6284 | **0.3454** | 0.6570 |

The historical-rate baseline is not a model: it predicts each line's own
trailing 30-day positive rate. It is the reference point any real model has to
beat, and both models do, in the expected order.

The saved model is `disruption_gbc_model.joblib`
(`HistGradientBoostingClassifier`, 300 iterations, depth 6, learning rate 0.05,
balanced class weights), stored with its feature column order and tuned
threshold.

## Feature importance

Permutation importance for the gradient boosting model, measured as the drop in
average precision when a feature's values are shuffled, on a 20,000-row test
subsample over 3 repeats.

| Feature | Importance |
|---|---|
| `line_positive_rate_prior_30d` | 0.0309 |
| `hour_of_day` | 0.0292 |
| `day_of_week` | 0.0101 |
| `scheduled_revenue_stop_departures` | 0.0069 |
| `line_positive_rate_prior_7d` | 0.0060 |
| `system_event_line_starts_prior_6h` | 0.0051 |
| `system_event_line_starts_prior_3h` | 0.0031 |
| `hours_since_line_disruption` | 0.0028 |

## Interpretation and limits

The gradient boosting model is the best of the three, but the honest reading is
that its edge is modest and most of the signal is structural rather than
dynamic.

- **The lift is real but small.** At the tuned threshold, precision is 0.238
  against a test base rate of 0.144 — roughly a 1.65x lift. Of every 100 hours
  flagged, about 24 see a disruption. Recall is 0.628.
- **Gradient boosting barely beats logistic regression** on PR-AUC (0.2566 vs
  0.2502). The gap is small enough that the extra model complexity buys little;
  the larger jump is from the baseline to any model at all.
- **The top two features are "which line" and "what time of day."** The model
  is mostly learning that some lines are chronically more disrupted and that
  disruptions cluster in certain hours. The features describing recent incident
  activity (`system_event_line_starts_prior_*`, `hours_since_line_disruption`)
  contribute comparatively little, which suggests the current feature set does
  not capture much about evolving conditions.
- **Positive rate drifts across the splits** (0.118 train to 0.144 test). The
  chronological split is correct for forecasting, but it means the model trains
  on a period with meaningfully less disruption than it is tested on. The tuned
  threshold happens to transfer because validation (0.1421) and test (0.1440)
  are close; that is not guaranteed to hold for a future period.
- **The target remains a service-disruption proxy**, derived from customer-facing
  alerts rather than observed train lateness. See
  [target_definition.md](target_definition.md). A positive label means the MTA
  published a qualifying unplanned alert, not that any specific train ran late.

## Reproducing

```bash
mta-alerts build --replace   # ~35 seconds
python train_classifier.py   # ~45 seconds
```

Results above were produced against the snapshot through June 29, 2026
documented in [data_feasibility_report.md](data_feasibility_report.md).
