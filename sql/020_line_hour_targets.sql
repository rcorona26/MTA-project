DROP TABLE IF EXISTS fct_line_hour_targets;
DROP TABLE IF EXISTS temp.tmp_positive_line_hours;
CREATE TEMP TABLE tmp_positive_line_hours (
    line TEXT NOT NULL,
    prediction_hour_local TEXT NOT NULL,
    positive_event_count INTEGER NOT NULL,
    PRIMARY KEY (line, prediction_hour_local)
) WITHOUT ROWID;

INSERT INTO tmp_positive_line_hours (
    line,
    prediction_hour_local,
    positive_event_count
)
SELECT
    line,
    substr(event_start_local, 1, 13) || ':00:00',
    count(DISTINCT event_instance_id)
FROM fct_significant_event_line_starts
GROUP BY line, substr(event_start_local, 1, 13);

CREATE TABLE fct_line_hour_targets (
    line TEXT NOT NULL,
    prediction_hour_local TEXT NOT NULL,
    label_window_end_local TEXT NOT NULL,
    significant_disruption_next_hour INTEGER NOT NULL
        CHECK (significant_disruption_next_hour IN (0, 1)),
    positive_event_count INTEGER NOT NULL CHECK (positive_event_count >= 0),
    PRIMARY KEY (line, prediction_hour_local)
) WITHOUT ROWID;

INSERT INTO fct_line_hour_targets (
    line,
    prediction_hour_local,
    label_window_end_local,
    significant_disruption_next_hour,
    positive_event_count
)
SELECT
    h.line,
    h.prediction_hour_local,
    h.label_window_end_local,
    CASE WHEN coalesce(p.positive_event_count, 0) > 0 THEN 1 ELSE 0 END
        AS significant_disruption_next_hour,
    coalesce(p.positive_event_count, 0) AS positive_event_count
FROM dim_line_hour AS h
LEFT JOIN tmp_positive_line_hours AS p
    ON p.line = h.line
   AND p.prediction_hour_local = h.prediction_hour_local;

CREATE INDEX ix_line_hour_target_value
    ON fct_line_hour_targets (significant_disruption_next_hour, prediction_hour_local);

DROP TABLE temp.tmp_positive_line_hours;
