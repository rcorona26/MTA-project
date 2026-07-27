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
