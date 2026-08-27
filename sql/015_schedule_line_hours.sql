DELETE FROM stg_unmapped_schedule_lines;
DELETE FROM dim_schedule_date_coverage;
DELETE FROM fct_schedule_line_hours;

INSERT INTO dim_schedule_date_coverage (service_date, dataset_year, dataset_id)
SELECT departure_date, min(dataset_year), min(dataset_id)
FROM raw_schedule_line_hours
GROUP BY departure_date;

INSERT INTO stg_unmapped_schedule_lines (
    dataset_id, departure_date, departure_hour, trip_line,
    scheduled_revenue_stop_departures
)
SELECT
    dataset_id,
    departure_date,
    departure_hour,
    trip_line,
    scheduled_revenue_stop_departures
FROM raw_schedule_line_hours
WHERE trip_line NOT IN (
    SELECT line FROM dim_subway_line
)
AND trip_line NOT IN ('5X', '6X', '7X', 'FX', 'SI');

INSERT INTO fct_schedule_line_hours (
    line, prediction_hour_local, scheduled_revenue_stop_departures
)
SELECT
    CASE trip_line
        WHEN '5X' THEN '5'
        WHEN '6X' THEN '6'
        WHEN '7X' THEN '7'
        WHEN 'FX' THEN 'F'
        ELSE trip_line
    END AS line,
    departure_date || ' ' || printf('%02d', departure_hour) || ':00:00',
    sum(scheduled_revenue_stop_departures)
FROM raw_schedule_line_hours
WHERE trip_line IN (
    SELECT line FROM dim_subway_line
    UNION ALL SELECT '5X'
    UNION ALL SELECT '6X'
    UNION ALL SELECT '7X'
    UNION ALL SELECT 'FX'
)
GROUP BY
    CASE trip_line
        WHEN '5X' THEN '5'
        WHEN '6X' THEN '6'
        WHEN '7X' THEN '7'
        WHEN 'FX' THEN 'F'
        ELSE trip_line
    END,
    departure_date,
    departure_hour;
