# MTA Subway Disruption Prediction

This repository is being rebuilt as a reproducible data and machine-learning
project. The current implementation creates an auditable **line-hour
classification target**, downloads historical schedule eligibility, and
defines leakage-safe as-of features. It does not yet train a model or serve
live predictions.

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

## Next milestone

Both pre-training gates are complete: the schedule-enriched feature build is
optimized (see indexes in `sql/020_line_hour_targets.sql`), and the 200-row
human label audit is done (`data/review/label_review_sample.csv`; see
[docs/target_definition.md](docs/target_definition.md) for the audit result
and the resulting planned-exclusion rule fix). Next: train historical-rate
baselines and stronger classifiers on `fct_line_hour_features`.
