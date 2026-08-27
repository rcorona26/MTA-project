PRAGMA foreign_keys = ON;

CREATE TABLE pipeline_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE raw_service_alerts (
    alert_id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL,
    update_number INTEGER NOT NULL CHECK (update_number >= 0),
    published_at_local TEXT NOT NULL,
    agency TEXT NOT NULL,
    status_label TEXT NOT NULL,
    affected TEXT NOT NULL,
    header TEXT,
    description TEXT,
    source_dataset_id TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE INDEX ix_raw_event_update
    ON raw_service_alerts (event_id, update_number);
CREATE INDEX ix_raw_event_time
    ON raw_service_alerts (event_id, published_at_local);

CREATE TABLE dim_subway_line (
    line TEXT PRIMARY KEY
);

CREATE TABLE dim_status_policy (
    status_token TEXT PRIMARY KEY,
    qualifies_significant INTEGER NOT NULL CHECK (qualifies_significant IN (0, 1)),
    excludes_as_planned INTEGER NOT NULL CHECK (excludes_as_planned IN (0, 1))
);

CREATE TABLE stg_alert_status_tokens (
    alert_id INTEGER NOT NULL REFERENCES raw_service_alerts(alert_id),
    status_token TEXT NOT NULL,
    PRIMARY KEY (alert_id, status_token)
);

CREATE INDEX ix_status_token
    ON stg_alert_status_tokens (status_token, alert_id);

CREATE TABLE stg_alert_lines (
    alert_id INTEGER NOT NULL REFERENCES raw_service_alerts(alert_id),
    line TEXT NOT NULL REFERENCES dim_subway_line(line),
    PRIMARY KEY (alert_id, line)
);

CREATE INDEX ix_alert_lines_line
    ON stg_alert_lines (line, alert_id);

CREATE TABLE stg_unmapped_affected_tokens (
    alert_id INTEGER NOT NULL REFERENCES raw_service_alerts(alert_id),
    affected_token TEXT NOT NULL,
    PRIMARY KEY (alert_id, affected_token)
);

CREATE TABLE stg_event_instances (
    alert_id INTEGER PRIMARY KEY REFERENCES raw_service_alerts(alert_id),
    event_instance_id TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    instance_sequence INTEGER NOT NULL CHECK (instance_sequence >= 0)
);

CREATE INDEX ix_event_instances
    ON stg_event_instances (event_instance_id, alert_id);

CREATE TABLE dim_line_hour (
    line TEXT NOT NULL REFERENCES dim_subway_line(line),
    prediction_hour_local TEXT NOT NULL,
    label_window_end_local TEXT NOT NULL,
    calendar_year INTEGER NOT NULL,
    calendar_month INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    hour_of_day INTEGER NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
    is_weekend INTEGER NOT NULL CHECK (is_weekend IN (0, 1)),
    PRIMARY KEY (line, prediction_hour_local)
) WITHOUT ROWID;

CREATE TABLE raw_schedule_line_hours (
    dataset_year INTEGER NOT NULL,
    dataset_id TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    departure_hour INTEGER NOT NULL CHECK (departure_hour BETWEEN 0 AND 23),
    trip_line TEXT NOT NULL,
    scheduled_revenue_stop_departures INTEGER NOT NULL
        CHECK (scheduled_revenue_stop_departures > 0),
    PRIMARY KEY (dataset_id, departure_date, departure_hour, trip_line)
) WITHOUT ROWID;

CREATE TABLE stg_unmapped_schedule_lines (
    dataset_id TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    departure_hour INTEGER NOT NULL,
    trip_line TEXT NOT NULL,
    scheduled_revenue_stop_departures INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, departure_date, departure_hour, trip_line)
) WITHOUT ROWID;

CREATE TABLE dim_schedule_date_coverage (
    service_date TEXT PRIMARY KEY,
    dataset_year INTEGER NOT NULL,
    dataset_id TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE fct_schedule_line_hours (
    line TEXT NOT NULL REFERENCES dim_subway_line(line),
    prediction_hour_local TEXT NOT NULL,
    scheduled_revenue_stop_departures INTEGER NOT NULL
        CHECK (scheduled_revenue_stop_departures > 0),
    PRIMARY KEY (line, prediction_hour_local)
) WITHOUT ROWID;
