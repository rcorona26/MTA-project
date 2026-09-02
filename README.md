# MTA Subway Disruption Prediction

This repository is a reproducible data and machine-learning project. The current
implementation creates an auditable **line-hour classification target**,
downloads historical schedule eligibility, defines leakage-safe as-of features,
trains and evaluates three classifiers, and exports an exact client-side model
for a self-contained interactive dashboard. It does not serve live predictions.

## Current target

For every canonical subway line and prediction hour `t`:

> `significant_disruption_next_hour = 1` when at least one new, unplanned MTA
> alert for that line first receives a qualifying delay or suspension status in
> the half-open window `[t, t + 1 hour)`; otherwise it is `0`.

This is a customer-facing **service-disruption proxy**. It is not an observed
individual-train lateness label. See [docs/target_definition.md](docs/target_definition.md).

## Data source

- Dataset: MTA Service Alerts: Beginning April 2020
- Publisher: Metropolitan Transportation Authority / NY Open Data
- Socrata dataset ID: `7kct-peq7`
- Source: https://data.ny.gov/Transportation/MTA-Service-Alerts-Beginning-April-2020/7kct-peq7

The downloader fixes a maximum `alert_id` at the start of a refresh, retrieves
NYCT Subway alerts in ascending key order, writes an immutable CSV snapshot,
and records a SHA-256 manifest. Raw and processed data are intentionally
gitignored.

## Quick start

Python 3.11 is required. The runtime pipeline uses only the Python standard
library and SQLite.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

mta-alerts download \
  --output data/raw/mta_service_alerts_nyct.csv \
  --manifest data/raw/mta_service_alerts_nyct.manifest.json

mta-alerts download-schedules

mta-alerts build \
  --input data/raw/mta_service_alerts_nyct.csv \
  --database data/processed/mta_alerts.sqlite \
  --quality-report data/processed/quality_report.json

mta-alerts review-sample

pytest
```

Use `--replace` explicitly when rebuilding an existing snapshot or database.
An optional `SOCRATA_APP_TOKEN` can be exported in the shell. If using the
provided `.env.example`, source it before running the command; the project does
not implicitly load `.env` files.

Without installing the package, the equivalent commands are:

```bash
PYTHONPATH=src python -m mta_delay download --help
PYTHONPATH=src python -m mta_delay build --help
```

## Data layers

1. `raw_service_alerts`: source fields for NYCT Subway alerts.
2. `stg_alert_status_tokens`: normalized pipe-delimited status values.
3. `stg_alert_lines`: exploded and canonicalized affected subway lines.
4. `fct_significant_event_line_starts`: one first qualifying timestamp per
   event and line.
5. `fct_line_hour_targets`: one binary label per line and complete source hour.
6. `fct_schedule_line_hours`: scheduled revenue-stop departure volume by line
   and hour for official schedule coverage dates.
7. `fct_line_hour_features`: schedule eligibility, calendar fields, and
   historical alert features computed strictly before the prediction hour.

SQL definitions live in [`sql/`](sql/). Column definitions and quality rules
are documented in [docs/data_dictionary.md](docs/data_dictionary.md).

## Verified snapshot

The full pipeline was verified against a snapshot through June 29, 2026:

- 285,896 NYCT Subway alert updates
- 113,106 derived event instances
- 54,081 fully covered source hours
- 1,352,025 canonical line-hour rows
- 148,926 positive line-hours (11.015%)
- SQLite `PRAGMA integrity_check`: `ok`

See [docs/data_feasibility_report.md](docs/data_feasibility_report.md) for the
snapshot hash, per-line prevalence, source-quality findings, and limitations.

## Existing notebook

[`delay_prediction.ipynb`](delay_prediction.ipynb) is preserved as the original
monthly aggregate runtime experiment. It is not used by the new alert pipeline
and should not be described as a next-hour prediction system.

## Model results

Three models were compared on `fct_line_hour_features` using a chronological
70/15/15 split, with the decision threshold tuned on validation and evaluated
once on the held-out test set.

| Model | PR-AUC | ROC-AUC | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Historical-rate baseline | 0.2214 | 0.6576 | 0.2008 | 0.6534 | 0.3072 |
| Logistic regression | 0.2502 | 0.6914 | 0.2286 | 0.6390 | 0.3368 |
| **Gradient boosting** | **0.2566** | **0.7100** | **0.2381** | 0.6284 | **0.3454** |

Gradient boosting wins, but its edge over logistic regression is small, and the
two strongest features are the line's own trailing disruption rate and the hour
of day — the model is mostly learning which lines are chronically disrupted and
when, not reacting to evolving conditions. Precision of 0.238 against a 14.4%
test base rate is a ~1.65x lift. Metrics are precision/recall/PR-AUC rather
than accuracy, since always predicting "no disruption" would score 86%.

### Intended use

At 23.8% precision, roughly three out of four flagged hours turn out to have
no disruption. Many subway disruptions stem from unpredictable, one-off events
(medical emergencies, mechanical failures, police activity) rather than
recurring patterns, so no model trained on historical data alone can reliably
forecast them in advance. This project is intended as a **prioritization
tool** — helping identify which lines are relatively more likely to see
trouble in a given hour, based on historical patterns — not as an automated
alerting system. It should not be used to trigger unattended alerts or
actions.

Full setup, feature importances, and limitations:
[docs/model_results.md](docs/model_results.md). Training code:
[`train_classifier.py`](train_classifier.py); the fitted model is saved to
`disruption_gbc_model.joblib` with its feature order and tuned threshold.

## Interactive dashboard

[Open the published dashboard](https://alafleur39.github.io/MTA-project/).

[`docs/dashboard.html`](docs/dashboard.html) is a self-contained review page —
no external scripts, styles, fonts, or server. Alongside the static charts it
carries two interactive sections:

- **Threshold explorer.** Drag the decision threshold and the confusion matrix,
  precision, recall, F1, and lift recompute against the held-out test set.
  Counts are exact, read from suffix sums over the model's test-set score
  histograms rather than a re-scored sample.
- **Live predictor.** Describe a line-hour and the fitted model scores it in the
  browser. The 300 boosted trees are embedded as JSON and traversed directly,
  reproducing scikit-learn to within 3e-9 — verified by an assertion at export
  time, which refuses to write a bundle that disagrees. Split thresholds are
  exported at full float precision on purpose; rounding them to 6dp moves
  predictions by up to 0.036, because a rounded threshold flips a comparison and
  routes the row down a different subtree.

Because inference runs client-side, the page is a static file and deploys
anywhere. Rebuild it with:

```bash
python train_classifier.py       # fits and saves disruption_gbc_model.joblib
python export_dashboard_data.py  # metrics, PR curves, calibration, prevalence
python export_model_bundle.py    # trees, reference scenario, score histograms
python build_dashboard.py        # injects both payloads into the template
```

`docs/dashboard_template.html` is the source; `docs/dashboard.html` is generated
and should not be hand-edited.

Teaching notes on how to read the results, and what not to claim from them, are
in [docs/NOTES.md](docs/NOTES.md).

## Next milestone

The current feature set has largely been mined for structural signal. The
promising directions are richer dynamic features (weather, incident text from
`header` / `description`, adjacency between lines sharing track) and calibrated
probabilities, since the tuned threshold is sensitive to the positive-rate
drift between the training and test periods.
