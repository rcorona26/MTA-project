DROP TABLE IF EXISTS fct_line_hour_features;
CREATE TABLE fct_line_hour_features (
    line TEXT NOT NULL REFERENCES dim_subway_line(line),
    prediction_hour_local TEXT NOT NULL,
    calendar_year INTEGER NOT NULL,
    calendar_month INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    hour_of_day INTEGER NOT NULL,
    is_weekend INTEGER NOT NULL,
    schedule_coverage_known INTEGER NOT NULL CHECK (schedule_coverage_known IN (0, 1)),
    scheduled_service_active INTEGER CHECK (scheduled_service_active IN (0, 1)),
    scheduled_revenue_stop_departures INTEGER,
    line_history_hours INTEGER NOT NULL,
    line_event_starts_prior_1h INTEGER NOT NULL,
    line_event_starts_prior_3h INTEGER NOT NULL,
    line_event_starts_prior_6h INTEGER NOT NULL,
    line_event_starts_prior_24h INTEGER NOT NULL,
    line_positive_rate_prior_7d REAL,
    line_positive_rate_prior_30d REAL,
    hours_since_line_disruption REAL,
    system_event_line_starts_prior_1h INTEGER NOT NULL,
    system_event_line_starts_prior_3h INTEGER NOT NULL,
    system_event_line_starts_prior_6h INTEGER NOT NULL,
    system_event_line_starts_prior_24h INTEGER NOT NULL,
    system_positive_line_rate_prior_7d REAL,
    significant_disruption_next_hour INTEGER NOT NULL,
    positive_event_count INTEGER NOT NULL,
    is_model_eligible INTEGER NOT NULL CHECK (is_model_eligible IN (0, 1)),
    PRIMARY KEY (line, prediction_hour_local)
) WITHOUT ROWID;

-- System-wide history is materialized into a keyed temp table before the main
-- insert. As an inline CTE it has no index, and SQLite chose it as the OUTER
-- loop of the join, rescanning the 1.35M-row line_history co-routine once per
-- system hour (~7.3e10 row visits, effectively non-terminating). Materializing
-- it turns that join into a primary-key lookup.
DROP TABLE IF EXISTS temp.tmp_system_history;
CREATE TEMP TABLE tmp_system_history (
    prediction_hour_local TEXT PRIMARY KEY,
    system_events_1h INTEGER NOT NULL,
    system_events_3h INTEGER NOT NULL,
    system_events_6h INTEGER NOT NULL,
    system_events_24h INTEGER NOT NULL,
    system_rate_7d REAL
) WITHOUT ROWID;

INSERT INTO tmp_system_history (
    prediction_hour_local,
    system_events_1h,
    system_events_3h,
    system_events_6h,
    system_events_24h,
    system_rate_7d
)
WITH system_hour AS (
    SELECT
        prediction_hour_local,
        sum(positive_event_count) AS system_event_line_starts,
        avg(significant_disruption_next_hour * 1.0) AS system_positive_line_rate
    FROM fct_line_hour_targets
    GROUP BY prediction_hour_local
)
SELECT
    prediction_hour_local,
    coalesce(sum(system_event_line_starts) OVER system_1h, 0),
    coalesce(sum(system_event_line_starts) OVER system_3h, 0),
    coalesce(sum(system_event_line_starts) OVER system_6h, 0),
    coalesce(sum(system_event_line_starts) OVER system_24h, 0),
    avg(system_positive_line_rate) OVER system_7d
FROM system_hour
WINDOW
    system_1h AS (ORDER BY prediction_hour_local ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING),
    system_3h AS (ORDER BY prediction_hour_local ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING),
    system_6h AS (ORDER BY prediction_hour_local ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING),
    system_24h AS (ORDER BY prediction_hour_local ROWS BETWEEN 24 PRECEDING AND 1 PRECEDING),
    system_7d AS (ORDER BY prediction_hour_local ROWS BETWEEN 168 PRECEDING AND 1 PRECEDING);

WITH line_history AS (
    SELECT
        t.*,
        row_number() OVER line_order - 1 AS line_history_hours,
        coalesce(sum(positive_event_count) OVER line_1h, 0) AS line_events_1h,
        coalesce(sum(positive_event_count) OVER line_3h, 0) AS line_events_3h,
        coalesce(sum(positive_event_count) OVER line_6h, 0) AS line_events_6h,
        coalesce(sum(positive_event_count) OVER line_24h, 0) AS line_events_24h,
        avg(significant_disruption_next_hour * 1.0) OVER line_7d AS line_rate_7d,
        avg(significant_disruption_next_hour * 1.0) OVER line_30d AS line_rate_30d,
        max(CASE WHEN significant_disruption_next_hour = 1
                 THEN prediction_hour_local END) OVER line_past AS previous_disruption_hour
    FROM fct_line_hour_targets AS t
    WINDOW
        line_order AS (
            PARTITION BY line ORDER BY prediction_hour_local
        ),
        line_1h AS (
            PARTITION BY line ORDER BY prediction_hour_local
            ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING
        ),
        line_3h AS (
            PARTITION BY line ORDER BY prediction_hour_local
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ),
        line_6h AS (
            PARTITION BY line ORDER BY prediction_hour_local
            ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
        ),
        line_24h AS (
            PARTITION BY line ORDER BY prediction_hour_local
            ROWS BETWEEN 24 PRECEDING AND 1 PRECEDING
        ),
        line_7d AS (
            PARTITION BY line ORDER BY prediction_hour_local
            ROWS BETWEEN 168 PRECEDING AND 1 PRECEDING
        ),
        line_30d AS (
            PARTITION BY line ORDER BY prediction_hour_local
            ROWS BETWEEN 720 PRECEDING AND 1 PRECEDING
        ),
        line_past AS (
            PARTITION BY line ORDER BY prediction_hour_local
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        )
)
INSERT INTO fct_line_hour_features (
    line,
    prediction_hour_local,
    calendar_year,
    calendar_month,
    day_of_week,
    hour_of_day,
    is_weekend,
    schedule_coverage_known,
    scheduled_service_active,
    scheduled_revenue_stop_departures,
    line_history_hours,
    line_event_starts_prior_1h,
    line_event_starts_prior_3h,
    line_event_starts_prior_6h,
    line_event_starts_prior_24h,
    line_positive_rate_prior_7d,
    line_positive_rate_prior_30d,
    hours_since_line_disruption,
    system_event_line_starts_prior_1h,
    system_event_line_starts_prior_3h,
    system_event_line_starts_prior_6h,
    system_event_line_starts_prior_24h,
    system_positive_line_rate_prior_7d,
    significant_disruption_next_hour,
    positive_event_count,
    is_model_eligible
)
SELECT
    h.line,
    h.prediction_hour_local,
    d.calendar_year,
    d.calendar_month,
    d.day_of_week,
    d.hour_of_day,
    d.is_weekend,
    CASE WHEN c.service_date IS NULL THEN 0 ELSE 1 END,
    CASE WHEN c.service_date IS NULL THEN NULL
         WHEN s.line IS NULL THEN 0 ELSE 1 END,
    s.scheduled_revenue_stop_departures,
    h.line_history_hours,
    h.line_events_1h,
    h.line_events_3h,
    h.line_events_6h,
    h.line_events_24h,
    h.line_rate_7d,
    h.line_rate_30d,
    CASE WHEN h.previous_disruption_hour IS NULL THEN NULL
         ELSE (julianday(h.prediction_hour_local) - julianday(h.previous_disruption_hour)) * 24.0
    END,
    sh.system_events_1h,
    sh.system_events_3h,
    sh.system_events_6h,
    sh.system_events_24h,
    sh.system_rate_7d,
    h.significant_disruption_next_hour,
    h.positive_event_count,
    CASE WHEN s.line IS NOT NULL THEN 1 ELSE 0 END
FROM line_history AS h
JOIN dim_line_hour AS d
  ON d.line = h.line
 AND d.prediction_hour_local = h.prediction_hour_local
JOIN tmp_system_history AS sh
  ON sh.prediction_hour_local = h.prediction_hour_local
LEFT JOIN dim_schedule_date_coverage AS c
  ON c.service_date = substr(h.prediction_hour_local, 1, 10)
LEFT JOIN fct_schedule_line_hours AS s
  ON s.line = h.line
 AND s.prediction_hour_local = h.prediction_hour_local;

CREATE INDEX ix_line_hour_features_model_rows
    ON fct_line_hour_features (is_model_eligible, prediction_hour_local, line);
