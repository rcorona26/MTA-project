import csv
import json
import sqlite3
from pathlib import Path

from mta_delay.pipeline import build_database
from mta_delay.review import write_label_review_sample


FIXTURE = Path(__file__).parent / "fixtures" / "service_alerts.csv"
SCHEDULE_FIXTURE = Path(__file__).parent / "fixtures" / "schedule_line_hours.csv"


def test_builds_complete_deduplicated_line_hour_target(tmp_path: Path) -> None:
    database = tmp_path / "alerts.sqlite"
    quality = tmp_path / "quality.json"

    report = build_database(FIXTURE, database, quality)

    assert report["failures"] == []
    assert report["summary"]["raw_alert_updates"] == 14
    assert report["summary"]["duplicate_event_update_keys"] == 1
    assert report["summary"]["covered_hours"] == 10
    assert report["summary"]["line_hour_rows"] == 250
    assert report["summary"]["positive_line_hours"] == 7
    assert report["summary"]["positive_event_assignments"] == 7
    assert json.loads(quality.read_text())["target"] == "significant_disruption_next_hour"

    with sqlite3.connect(database) as connection:
        starts = connection.execute(
            """
            SELECT event_instance_id, event_id, line, event_start_local
            FROM fct_significant_event_line_starts
            ORDER BY event_id, event_instance_id, line
            """
        ).fetchall()
        assert starts == [
            ("100:1", 100, "A", "2024-01-01 01:15:00"),
            ("100:1", 100, "C", "2024-01-01 01:30:00"),
            ("103:1", 103, "6", "2024-01-01 04:15:00"),
            ("104:1", 104, "F", "2024-01-01 05:15:00"),
            ("106:1", 106, "A", "2024-01-01 07:00:00"),
            ("108:1", 108, "Q", "2024-01-01 08:15:00"),
            ("108:2", 108, "Q", "2024-01-01 09:15:00"),
        ]

        positives = connection.execute(
            """
            SELECT line, prediction_hour_local, positive_event_count
            FROM fct_line_hour_targets
            WHERE significant_disruption_next_hour = 1
            ORDER BY prediction_hour_local, line
            """
        ).fetchall()
        assert positives == [
            ("A", "2024-01-01 01:00:00", 1),
            ("C", "2024-01-01 01:00:00", 1),
            ("6", "2024-01-01 04:00:00", 1),
            ("F", "2024-01-01 05:00:00", 1),
            ("A", "2024-01-01 07:00:00", 1),
            ("Q", "2024-01-01 08:00:00", 1),
            ("Q", "2024-01-01 09:00:00", 1),
        ]


def test_reports_unmapped_routes_without_silently_mapping_them(tmp_path: Path) -> None:
    database = tmp_path / "alerts.sqlite"
    quality = tmp_path / "quality.json"
    report = build_database(FIXTURE, database, quality)

    unmapped = {item["affected_token"] for item in report["unmapped_affected_tokens"]}
    assert unmapped == {"SI", "SIM7"}


def test_refuses_to_overwrite_database_without_explicit_replace(tmp_path: Path) -> None:
    database = tmp_path / "alerts.sqlite"
    quality = tmp_path / "quality.json"
    build_database(FIXTURE, database, quality)

    try:
        build_database(FIXTURE, database, quality)
    except FileExistsError as exc:
        assert "--replace" in str(exc)
    else:
        raise AssertionError("Expected overwrite protection")


def test_schedule_eligibility_and_features_are_strictly_as_of(tmp_path: Path) -> None:
    database = tmp_path / "alerts.sqlite"
    quality = tmp_path / "quality.json"
    report = build_database(
        FIXTURE,
        database,
        quality,
        schedule_path=SCHEDULE_FIXTURE,
    )

    assert report["failures"] == []
    assert report["schedule_and_features"]["raw_schedule_line_hours"] == 6
    assert report["schedule_and_features"]["feature_rows"] == 250
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT
                prediction_hour_local,
                scheduled_revenue_stop_departures,
                line_event_starts_prior_1h,
                system_event_line_starts_prior_1h,
                significant_disruption_next_hour,
                is_model_eligible
            FROM fct_line_hour_features
            WHERE line = 'A' AND prediction_hour_local IN (
                '2024-01-01 01:00:00', '2024-01-01 02:00:00'
            )
            ORDER BY prediction_hour_local
            """
        ).fetchall()
        assert rows == [
            ("2024-01-01 01:00:00", 4, 0, 0, 1, 1),
            ("2024-01-01 02:00:00", 5, 1, 2, 0, 1),
        ]
        aliases = connection.execute(
            """
            SELECT line, prediction_hour_local, scheduled_revenue_stop_departures
            FROM fct_schedule_line_hours
            WHERE line IN ('5', '6', 'F')
            ORDER BY line
            """
        ).fetchall()
        assert aliases == [
            ("5", "2024-01-01 04:00:00", 2),
            ("6", "2024-01-01 04:00:00", 3),
            ("F", "2024-01-01 05:00:00", 4),
        ]


def test_writes_deterministic_review_sheet_with_blank_review_fields(
    tmp_path: Path,
) -> None:
    database = tmp_path / "alerts.sqlite"
    quality = tmp_path / "quality.json"
    output = tmp_path / "review.csv"
    build_database(FIXTURE, database, quality)

    result = write_label_review_sample(database, output, sample_size=6)

    assert result["strata"] == {
        "excluded_as_planned": 1,
        "excluded_nonqualifying_status": 2,
        "included_positive": 3,
    }
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert len(rows) == 6
    assert all(row["policy_label_correct_yes_no_uncertain"] == "" for row in rows)
