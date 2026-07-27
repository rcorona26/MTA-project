DROP VIEW IF EXISTS stg_subway_alert_updates;
CREATE VIEW stg_subway_alert_updates AS
SELECT
    alert_id,
    event_id,
    update_number,
    published_at_local,
    lower(trim(agency)) AS agency_normalized,
    lower(trim(status_label)) AS status_label_normalized,
    trim(affected) AS affected,
    header,
    description
FROM raw_service_alerts;

DROP TABLE IF EXISTS fct_significant_event_line_starts;
CREATE TABLE fct_significant_event_line_starts (
    event_instance_id TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    line TEXT NOT NULL REFERENCES dim_subway_line(line),
    first_alert_id INTEGER NOT NULL REFERENCES raw_service_alerts(alert_id),
    first_update_number INTEGER NOT NULL,
    event_start_local TEXT NOT NULL,
    first_status_label TEXT NOT NULL,
    first_header TEXT,
    PRIMARY KEY (event_instance_id, line)
);

DELETE FROM stg_event_instances;
INSERT INTO stg_event_instances (
    alert_id,
    event_instance_id,
    event_id,
    instance_sequence
)
WITH ordered AS (
    SELECT
        alert_id,
        event_id,
        update_number,
        published_at_local,
        sum(CASE WHEN update_number = 0 THEN 1 ELSE 0 END) OVER (
            PARTITION BY event_id
            ORDER BY published_at_local, alert_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS instance_sequence
    FROM raw_service_alerts
)
SELECT
    alert_id,
    printf('%d:%d', event_id, instance_sequence),
    event_id,
    instance_sequence
FROM ordered;

WITH event_policy AS (
    SELECT
        i.event_instance_id,
        max(CASE WHEN coalesce(p.excludes_as_planned, 0) = 1 THEN 1 ELSE 0 END)
            AS event_is_planned
    FROM raw_service_alerts AS r
    JOIN stg_event_instances AS i
        ON i.alert_id = r.alert_id
    LEFT JOIN stg_alert_status_tokens AS s
        ON s.alert_id = r.alert_id
    LEFT JOIN dim_status_policy AS p
        ON p.status_token = s.status_token
    GROUP BY i.event_instance_id
),
qualifying_updates AS (
    SELECT
        i.event_instance_id,
        r.event_id,
        l.line,
        r.alert_id,
        r.update_number,
        r.published_at_local,
        r.status_label,
        r.header
    FROM raw_service_alerts AS r
    JOIN stg_event_instances AS i
        ON i.alert_id = r.alert_id
    JOIN event_policy AS ep
        ON ep.event_instance_id = i.event_instance_id
       AND ep.event_is_planned = 0
    JOIN stg_alert_lines AS l
        ON l.alert_id = r.alert_id
    WHERE EXISTS (
        SELECT 1
        FROM stg_alert_status_tokens AS s
        JOIN dim_status_policy AS p
            ON p.status_token = s.status_token
           AND p.qualifies_significant = 1
        WHERE s.alert_id = r.alert_id
    )
),
ranked AS (
    SELECT
        q.*,
        row_number() OVER (
            PARTITION BY q.event_instance_id, q.line
            ORDER BY q.published_at_local, q.update_number, q.alert_id
        ) AS event_line_rank
    FROM qualifying_updates AS q
)
INSERT INTO fct_significant_event_line_starts (
    event_instance_id,
    event_id,
    line,
    first_alert_id,
    first_update_number,
    event_start_local,
    first_status_label,
    first_header
)
SELECT
    event_instance_id,
    event_id,
    line,
    alert_id,
    update_number,
    published_at_local,
    status_label,
    header
FROM ranked
WHERE event_line_rank = 1;

CREATE INDEX ix_event_line_start_time
    ON fct_significant_event_line_starts (line, event_start_local);
