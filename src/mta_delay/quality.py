from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mta_delay.constants import CANONICAL_LINES


def _rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    cursor = connection.execute(sql)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name=?)",
        (name,),
    ).fetchone()[0] == 1


def build_quality_report(connection: sqlite3.Connection) -> dict[str, Any]:
    summary = _rows(
        connection,
        """
        SELECT
            count(*) AS raw_alert_updates,
            count(DISTINCT event_id) AS source_events,
            min(published_at_local) AS min_published_at_local,
            max(published_at_local) AS max_published_at_local
        FROM raw_service_alerts
        """,
    )[0]
    summary.update(
        _rows(
            connection,
            """
            SELECT
                (SELECT count(*) FROM fct_significant_event_line_starts)
                    AS qualifying_event_line_starts,
                (SELECT count(*) FROM dim_line_hour) AS line_hour_rows,
                (SELECT count(DISTINCT prediction_hour_local) FROM dim_line_hour)
                    AS covered_hours,
                (SELECT count(*) FROM fct_line_hour_targets
                    WHERE significant_disruption_next_hour = 1) AS positive_line_hours,
                (SELECT coalesce(sum(positive_event_count), 0)
                    FROM fct_line_hour_targets) AS positive_event_assignments,
                (SELECT count(*) FROM stg_unmapped_affected_tokens)
                    AS unmapped_affected_assignments,
                (SELECT count(DISTINCT event_instance_id) FROM stg_event_instances)
                    AS derived_event_instances
            """,
        )[0]
    )

    line_count = connection.execute("SELECT count(*) FROM dim_subway_line").fetchone()[0]
    duplicate_event_updates = connection.execute(
        """
        SELECT count(*) FROM (
            SELECT event_id, update_number
            FROM raw_service_alerts
            GROUP BY event_id, update_number
            HAVING count(*) > 1
        )
        """
    ).fetchone()[0]
    summary["duplicate_event_update_keys"] = duplicate_event_updates
    invalid_targets = connection.execute(
        """
        SELECT count(*) FROM fct_line_hour_targets
        WHERE significant_disruption_next_hour NOT IN (0, 1)
        """
    ).fetchone()[0]
    expected_line_hours = int(summary["covered_hours"]) * len(CANONICAL_LINES)
    target_rows = connection.execute("SELECT count(*) FROM fct_line_hour_targets").fetchone()[0]
    positive = int(summary["positive_line_hours"])
    prevalence = positive / target_rows if target_rows else 0.0

    checks = [
        {
            "name": "raw_rows_present",
            "passed": int(summary["raw_alert_updates"]) > 0,
            "observed": int(summary["raw_alert_updates"]),
        },
        {
            "name": "canonical_line_count",
            "passed": line_count == len(CANONICAL_LINES),
            "observed": line_count,
            "expected": len(CANONICAL_LINES),
        },
        {
            "name": "line_hour_cartesian_completeness",
            "passed": target_rows == expected_line_hours,
            "observed": target_rows,
            "expected": expected_line_hours,
        },
        {
            "name": "binary_target_values",
            "passed": invalid_targets == 0,
            "observed_invalid": invalid_targets,
        },
        {
            "name": "both_target_classes_present",
            "passed": 0 < positive < target_rows,
            "positive": positive,
            "negative": target_rows - positive,
        },
    ]

    schedule_summary: dict[str, Any] | None = None
    if _table_exists(connection, "fct_line_hour_features"):
        schedule_summary = _rows(
            connection,
            """
            SELECT
                (SELECT count(*) FROM raw_schedule_line_hours)
                    AS raw_schedule_line_hours,
                (SELECT count(*) FROM dim_schedule_date_coverage)
                    AS schedule_covered_dates,
                (SELECT count(*) FROM fct_schedule_line_hours)
                    AS active_schedule_line_hours,
                (SELECT count(*) FROM fct_line_hour_features)
                    AS feature_rows,
                (SELECT count(*) FROM fct_line_hour_features
                    WHERE is_model_eligible = 1) AS model_eligible_rows,
                (SELECT count(*) FROM fct_line_hour_features
                    WHERE is_model_eligible = 1
                      AND significant_disruption_next_hour = 1)
                    AS model_eligible_positive_rows,
                (SELECT count(*) FROM stg_unmapped_schedule_lines)
                    AS unmapped_schedule_rows,
                (SELECT count(*) FROM fct_line_hour_features
                    WHERE schedule_coverage_known = 1
                      AND scheduled_service_active = 0
                      AND significant_disruption_next_hour = 1)
                    AS positive_labels_during_inactive_schedule_hours
            """,
        )[0]
        checks.extend(
            [
                {
                    "name": "feature_target_row_parity",
                    "passed": int(schedule_summary["feature_rows"]) == target_rows,
                    "observed": int(schedule_summary["feature_rows"]),
                    "expected": target_rows,
                },
                {
                    "name": "schedule_rows_present",
                    "passed": int(schedule_summary["raw_schedule_line_hours"]) > 0,
                    "observed": int(schedule_summary["raw_schedule_line_hours"]),
                },
                {
                    "name": "schedule_lines_mapped",
                    "passed": int(schedule_summary["unmapped_schedule_rows"]) == 0,
                    "observed_unmapped": int(schedule_summary["unmapped_schedule_rows"]),
                },
                {
                    "name": "model_rows_have_both_target_classes",
                    "passed": (
                        0 < int(schedule_summary["model_eligible_positive_rows"])
                        < int(schedule_summary["model_eligible_rows"])
                    ),
                    "positive": int(schedule_summary["model_eligible_positive_rows"]),
                    "total": int(schedule_summary["model_eligible_rows"]),
                },
            ]
        )

    return {
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "target": "significant_disruption_next_hour",
        "summary": {**summary, "target_prevalence": prevalence},
        "checks": checks,
        "failures": [check["name"] for check in checks if not check["passed"]],
        "schedule_and_features": schedule_summary,
        "prevalence_by_line": _rows(
            connection,
            """
            SELECT
                line,
                count(*) AS line_hours,
                sum(significant_disruption_next_hour) AS positive_line_hours,
                avg(significant_disruption_next_hour * 1.0) AS prevalence
            FROM fct_line_hour_targets
            GROUP BY line
            ORDER BY line
            """,
        ),
        "top_status_tokens": _rows(
            connection,
            """
            SELECT status_token, count(*) AS alert_updates
            FROM stg_alert_status_tokens
            GROUP BY status_token
            ORDER BY alert_updates DESC, status_token
            LIMIT 30
            """,
        ),
        "unmapped_affected_tokens": _rows(
            connection,
            """
            SELECT affected_token, count(*) AS alert_updates
            FROM stg_unmapped_affected_tokens
            GROUP BY affected_token
            ORDER BY alert_updates DESC, affected_token
            LIMIT 50
            """,
        ),
    }


def assert_quality(report: dict[str, Any]) -> None:
    if report["failures"]:
        raise RuntimeError("Data-quality checks failed: " + ", ".join(report["failures"]))


def write_quality_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
