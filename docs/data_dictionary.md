# Data dictionary

## Source fields

| Field | Type | Meaning |
|---|---|---|
| `alert_id` | INTEGER | Unique identifier for one published alert update. |
| `event_id` | INTEGER | Identifier shared by all updates to one incident. |
| `update_number` | INTEGER | Sequential update number within an event. |
| `published_at_local` | TEXT datetime | Source publication time, normalized to `YYYY-MM-DD HH:MM:SS` New York wall time. |
| `agency` | TEXT | MTA agency; ingestion is restricted to `NYCT Subway`. |
| `status_label` | TEXT | Pipe-delimited customer-facing status values. |
| `affected` | TEXT | Pipe-delimited affected route/line identifiers. |
| `header` | TEXT | Short customer-facing alert summary. |
| `description` | TEXT nullable | Longer optional customer-facing explanation. |

## Normalized tables

### `raw_service_alerts`

One row per source `alert_id`. It preserves the selected source fields and adds
the source dataset ID and ingestion timestamp.

### `stg_alert_status_tokens`

One row per unique normalized status token on an alert update.

Primary key: `(alert_id, status_token)`.

### `stg_alert_lines`

One row per canonical subway line affected by an alert update.

Primary key: `(alert_id, line)`.

### `stg_unmapped_affected_tokens`

Audit table for affected tokens that are not canonical subway lines or known
aliases. These records are never silently converted into target rows.

### `stg_event_instances`

Maps every source alert update to a derived event instance. The sequence starts
again whenever the same source `event_id` publishes another `update_number = 0`.
This handles the rare source-ID reuse observed at month boundaries without
discarding the original identifiers.

### `fct_significant_event_line_starts`

One row per deduplicated `(event_instance_id, line)`. `event_start_local` is the
first qualifying non-planned update for that event instance and line.

### `dim_line_hour`

The complete Cartesian product of canonical lines and fully covered source
hours, plus basic calendar fields. This guarantees explicit negative examples.

### `fct_line_hour_targets`

| Field | Type | Meaning |
|---|---|---|
| `line` | TEXT | Canonical subway line. |
| `prediction_hour_local` | TEXT datetime | Start of the prediction and label window. |
| `label_window_end_local` | TEXT datetime | Exclusive end of the next-hour label window. |
| `significant_disruption_next_hour` | INTEGER | Binary classification target. |
| `positive_event_count` | INTEGER | Number of distinct qualifying events beginning in the window. |

### `dim_schedule_date_coverage`

One row per service date present in the official schedule extract. A prediction
hour whose date is absent here has unknown schedule coverage rather than known
absence of service.

### `stg_unmapped_schedule_lines`

Audit table for schedule `trip_line` values that are neither canonical subway
lines nor known express aliases. Like `stg_unmapped_affected_tokens`, these
records are never silently folded into a canonical line.

### `fct_schedule_line_hours`

| Field | Type | Meaning |
|---|---|---|
| `line` | TEXT | Canonical subway line. Express variants `5X`, `6X`, `7X`, and `FX` are folded into their base line; `SI` is excluded. |
| `prediction_hour_local` | TEXT datetime | Start of the scheduled departure hour. |
| `scheduled_revenue_stop_departures` | INTEGER | Scheduled revenue stop departures summed across trips for that line and hour. |

### `fct_line_hour_features`

One row per `(line, prediction_hour_local)`, carrying the label alongside
features computed strictly from data available before the prediction hour. All
trailing windows end at `1 PRECEDING`, so the prediction hour never contributes
to its own features.

| Field | Type | Meaning |
|---|---|---|
| `calendar_year`, `calendar_month`, `day_of_week`, `hour_of_day`, `is_weekend` | INTEGER | Calendar fields carried from `dim_line_hour`. |
| `schedule_coverage_known` | INTEGER | 1 when the date appears in the schedule extract, else 0. |
| `scheduled_service_active` | INTEGER nullable | 1 when the line has scheduled departures that hour, 0 when covered but absent, NULL when coverage is unknown. |
| `scheduled_revenue_stop_departures` | INTEGER nullable | Scheduled departure volume for the hour; NULL outside schedule coverage. |
| `line_history_hours` | INTEGER | Count of prior observed hours for the line, so early rows with thin history are identifiable. |
| `line_event_starts_prior_1h` / `_3h` / `_6h` / `_24h` | INTEGER | Qualifying event starts on the line in the trailing window ending before the prediction hour. |
| `line_positive_rate_prior_7d` / `_30d` | REAL nullable | The line's own positive-label rate over the trailing 168 / 720 hours. |
| `hours_since_line_disruption` | REAL nullable | Hours since the line's most recent prior positive hour; NULL when it has none. |
| `system_event_line_starts_prior_1h` / `_3h` / `_6h` / `_24h` | INTEGER | Same event-start counts summed across all lines, capturing system-wide conditions. |
| `system_positive_line_rate_prior_7d` | REAL nullable | System-wide positive line-hour rate over the trailing 168 hours. |
| `significant_disruption_next_hour` | INTEGER | Binary classification target, carried from `fct_line_hour_targets`. |
| `positive_event_count` | INTEGER | Number of distinct qualifying events beginning in the label window. |
| `is_model_eligible` | INTEGER | 1 only when the line has confirmed scheduled service that hour. Training and evaluation filter on this. |

## Required quality checks

- Unique `alert_id`
- Duplicate `(event_id, update_number)` keys reported and segmented
- Nonnegative update numbers
- Valid source timestamps
- Exactly the expected canonical line dimension
- `line-hour rows = lines x fully covered hours`
- Binary target values only
- Positive and negative examples both present
- Unmapped affected tokens reported
- Per-line class prevalence reported
