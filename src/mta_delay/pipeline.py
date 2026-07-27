from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from mta_delay.constants import (
    CANONICAL_LINES,
    DATASET_ID,
    LINE_ALIASES,
    PLANNED_STATUS_TOKENS,
    SCHEDULE_DATASETS,
    SCHEDULE_SOURCE_COLUMNS,
    SIGNIFICANT_STATUS_TOKENS,
    SOURCE_COLUMNS,
    SUBWAY_AGENCY,
)
from mta_delay.quality import assert_quality, build_quality_report, write_quality_report

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SQL_DIRECTORY = REPOSITORY_ROOT / "sql"


def _execute_sql_file(connection: sqlite3.Connection, name: str) -> None:
    connection.executescript((SQL_DIRECTORY / name).read_text(encoding="utf-8"))


def _normalize_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is not None:
        raise ValueError("Source timestamps must be offset-naive New York wall time")
    return parsed.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _status_tokens(value: str) -> tuple[str, ...]:
    return tuple(sorted({part.strip().lower() for part in value.split("|") if part.strip()}))


def _affected_tokens(value: str) -> tuple[str, ...]:
    return tuple(sorted({part.strip().upper() for part in value.split("|") if part.strip()}))


def _flush(
    connection: sqlite3.Connection,
    raw_rows: list[tuple],
    status_rows: list[tuple[int, str]],
    line_rows: list[tuple[int, str]],
    unmapped_rows: list[tuple[int, str]],
) -> None:
    connection.executemany(
        """
        INSERT INTO raw_service_alerts (
            alert_id, event_id, update_number, published_at_local, agency,
            status_label, affected, header, description, source_dataset_id,
            ingested_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        raw_rows,
    )
    connection.executemany(
        "INSERT INTO stg_alert_status_tokens (alert_id, status_token) VALUES (?, ?)",
        status_rows,
    )
    connection.executemany(
        "INSERT INTO stg_alert_lines (alert_id, line) VALUES (?, ?)", line_rows
    )
    connection.executemany(
        """
        INSERT INTO stg_unmapped_affected_tokens (alert_id, affected_token)
        VALUES (?, ?)
        """,
        unmapped_rows,
    )
    raw_rows.clear()
    status_rows.clear()
    line_rows.clear()
    unmapped_rows.clear()


def _import_alerts(connection: sqlite3.Connection, input_path: Path) -> int:
    ingested_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    raw_rows: list[tuple] = []
    status_rows: list[tuple[int, str]] = []
    line_rows: list[tuple[int, str]] = []
    unmapped_rows: list[tuple[int, str]] = []
    imported = 0

    with input_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        missing = set(SOURCE_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Input CSV is missing required columns: {sorted(missing)}")

        for source_row_number, row in enumerate(reader, start=2):
            if row["agency"].strip() != SUBWAY_AGENCY:
                raise ValueError(
                    f"Unexpected agency on CSV row {source_row_number}: {row['agency']!r}"
                )
            try:
                alert_id = int(row["alert_id"])
                event_id = int(row["event_id"])
                update_number = int(row["update_number"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid identifier on CSV row {source_row_number}") from exc

            raw_rows.append(
                (
                    alert_id,
                    event_id,
                    update_number,
                    _normalize_timestamp(row["date"]),
                    SUBWAY_AGENCY,
                    row["status_label"].strip(),
                    row["affected"].strip(),
                    row.get("header", "").strip() or None,
                    row.get("description", "").strip() or None,
                    DATASET_ID,
                    ingested_at,
                )
            )

            status_rows.extend((alert_id, token) for token in _status_tokens(row["status_label"]))
            canonical_lines: set[str] = set()
            unmapped_tokens: set[str] = set()
            for token in _affected_tokens(row["affected"]):
                canonical = LINE_ALIASES.get(token, token)
                if canonical in CANONICAL_LINES:
                    canonical_lines.add(canonical)
                else:
                    unmapped_tokens.add(token)
            line_rows.extend((alert_id, line) for line in sorted(canonical_lines))
            unmapped_rows.extend((alert_id, token) for token in sorted(unmapped_tokens))

            imported += 1
            if len(raw_rows) >= 5_000:
                _flush(connection, raw_rows, status_rows, line_rows, unmapped_rows)

    if raw_rows:
        _flush(connection, raw_rows, status_rows, line_rows, unmapped_rows)
    return imported


def _populate_dimensions(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO dim_subway_line (line) VALUES (?)",
        ((line,) for line in CANONICAL_LINES),
    )
    policy_tokens = SIGNIFICANT_STATUS_TOKENS | PLANNED_STATUS_TOKENS
    connection.executemany(
        """
        INSERT INTO dim_status_policy (
            status_token, qualifies_significant, excludes_as_planned
        ) VALUES (?, ?, ?)
        """,
        (
            (
                token,
                int(token in SIGNIFICANT_STATUS_TOKENS),
                int(token in PLANNED_STATUS_TOKENS),
            )
            for token in sorted(policy_tokens)
        ),
    )


def _ceil_hour(value: datetime) -> datetime:
    floored = value.replace(minute=0, second=0, microsecond=0)
    return floored if value == floored else floored + timedelta(hours=1)


def _populate_line_hours(connection: sqlite3.Connection) -> None:
    minimum, maximum = connection.execute(
        "SELECT min(published_at_local), max(published_at_local) FROM raw_service_alerts"
    ).fetchone()
    if not minimum or not maximum:
        raise RuntimeError("No source coverage available for line-hour construction")
    minimum_dt = datetime.fromisoformat(minimum)
    maximum_dt = datetime.fromisoformat(maximum)
    start = _ceil_hour(minimum_dt)
    end_exclusive = maximum_dt.replace(minute=0, second=0, microsecond=0)
    if start >= end_exclusive:
        raise RuntimeError("Source does not contain one fully covered hour")

    start_text = start.strftime("%Y-%m-%d %H:%M:%S")
    end_text = end_exclusive.strftime("%Y-%m-%d %H:%M:%S")
    connection.execute(
        """
        WITH RECURSIVE hours(prediction_hour_local) AS (
            SELECT ?
            UNION ALL
            SELECT datetime(prediction_hour_local, '+1 hour')
            FROM hours
            WHERE datetime(prediction_hour_local, '+1 hour') < ?
        )
        INSERT INTO dim_line_hour (
            line, prediction_hour_local, label_window_end_local,
            calendar_year, calendar_month, day_of_week, hour_of_day, is_weekend
        )
        SELECT
            l.line,
            h.prediction_hour_local,
            datetime(h.prediction_hour_local, '+1 hour'),
            cast(strftime('%Y', h.prediction_hour_local) AS INTEGER),
            cast(strftime('%m', h.prediction_hour_local) AS INTEGER),
            (cast(strftime('%w', h.prediction_hour_local) AS INTEGER) + 6) % 7,
            cast(strftime('%H', h.prediction_hour_local) AS INTEGER),
            CASE WHEN strftime('%w', h.prediction_hour_local) IN ('0', '6')
                 THEN 1 ELSE 0 END
        FROM hours AS h
        CROSS JOIN dim_subway_line AS l
        """,
        (start_text, end_text),
    )
    connection.executemany(
        "INSERT INTO pipeline_metadata (key, value) VALUES (?, ?)",
        (
            ("complete_label_coverage_start_local", start.isoformat(sep=" ")),
            ("complete_label_coverage_end_local", end_exclusive.isoformat(sep=" ")),
        ),
    )


def _import_schedule_line_hours(
    connection: sqlite3.Connection, input_path: Path
) -> int:
    imported = 0
    rows: list[tuple[int, str, str, int, str, int]] = []
    with input_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        missing = set(SCHEDULE_SOURCE_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"Schedule CSV is missing required columns: {sorted(missing)}"
            )
        for source_row_number, row in enumerate(reader, start=2):
            try:
                dataset_year = int(row["dataset_year"])
                departure_date = date.fromisoformat(row["departure_date"].strip())
                departure_hour = int(row["departure_hour"])
                scheduled_departures = int(row["scheduled_revenue_stop_departures"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid schedule value on CSV row {source_row_number}"
                ) from exc
            dataset_id = row["dataset_id"].strip()
            if SCHEDULE_DATASETS.get(dataset_year) != dataset_id:
                raise ValueError(
                    f"Unexpected schedule dataset on CSV row {source_row_number}: "
                    f"{dataset_year}/{dataset_id}"
                )
            if departure_date.year != dataset_year:
                raise ValueError(
                    f"Schedule date/year mismatch on CSV row {source_row_number}"
                )
            if not 0 <= departure_hour <= 23 or scheduled_departures <= 0:
                raise ValueError(
                    f"Invalid schedule aggregate on CSV row {source_row_number}"
                )
            trip_line = row["trip_line"].strip().upper()
            if not trip_line:
                raise ValueError(f"Missing trip_line on CSV row {source_row_number}")
            rows.append(
                (
                    dataset_year,
                    dataset_id,
                    departure_date.isoformat(),
                    departure_hour,
                    trip_line,
                    scheduled_departures,
                )
            )
            imported += 1
            if len(rows) >= 10_000:
                connection.executemany(
                    "INSERT INTO raw_schedule_line_hours VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                rows.clear()
    if rows:
        connection.executemany(
            "INSERT INTO raw_schedule_line_hours VALUES (?, ?, ?, ?, ?, ?)", rows
        )
    return imported


def build_database(
    input_path: Path,
    database_path: Path,
    quality_report_path: Path,
    *,
    schedule_path: Path | None = None,
    replace: bool = False,
) -> dict:
    """Build the normalized SQLite data product atomically."""
    if database_path.exists() and not replace:
        raise FileExistsError(f"Refusing to overwrite {database_path}; pass --replace")
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if schedule_path is not None and not schedule_path.exists():
        raise FileNotFoundError(schedule_path)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{database_path.name}.", suffix=".tmp", dir=database_path.parent
    )
    os.close(descriptor)
    temp_path = Path(temp_name)

    try:
        with sqlite3.connect(temp_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            _execute_sql_file(connection, "001_schema.sql")
            _populate_dimensions(connection)
            imported = _import_alerts(connection, input_path)
            connection.execute(
                "INSERT INTO pipeline_metadata (key, value) VALUES (?, ?)",
                ("imported_source_rows", str(imported)),
            )
            _execute_sql_file(connection, "010_event_line_starts.sql")
            _populate_line_hours(connection)
            _execute_sql_file(connection, "020_line_hour_targets.sql")
            if schedule_path is not None:
                imported_schedules = _import_schedule_line_hours(
                    connection, schedule_path
                )
                connection.execute(
                    "INSERT INTO pipeline_metadata (key, value) VALUES (?, ?)",
                    ("imported_schedule_line_hour_rows", str(imported_schedules)),
                )
                _execute_sql_file(connection, "015_schedule_line_hours.sql")
                _execute_sql_file(connection, "030_line_hour_features.sql")
            report = build_quality_report(connection)
            assert_quality(report)
            connection.commit()

        os.replace(temp_path, database_path)
        write_quality_report(quality_report_path, report)
        return report
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
