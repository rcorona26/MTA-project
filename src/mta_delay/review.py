from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


REVIEW_COLUMNS = (
    "review_stratum",
    "policy_assigned_label",
    "event_instance_id",
    "event_id",
    "line",
    "prediction_hour_local",
    "published_at_local",
    "status_label",
    "header",
    "reviewer",
    "is_significant_yes_no_uncertain",
    "is_unplanned_yes_no_uncertain",
    "policy_label_correct_yes_no_uncertain",
    "review_notes",
)


def _query_rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    cursor = connection.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _candidate_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    positives = _query_rows(
        connection,
        """
        SELECT
            'included_positive' AS review_stratum,
            1 AS policy_assigned_label,
            f.event_instance_id,
            f.event_id,
            f.line,
            substr(f.event_start_local, 1, 13) || ':00:00' AS prediction_hour_local,
            f.event_start_local AS published_at_local,
            f.first_status_label AS status_label,
            coalesce(f.first_header, '') AS header
        FROM fct_significant_event_line_starts AS f
        """,
    )
    exclusions = _query_rows(
        connection,
        """
        WITH event_policy AS (
            SELECT
                i.event_instance_id,
                max(CASE WHEN coalesce(p.excludes_as_planned, 0) = 1
                         THEN 1 ELSE 0 END) AS is_planned,
                max(CASE WHEN coalesce(p.qualifies_significant, 0) = 1
                         THEN 1 ELSE 0 END) AS has_significant
            FROM stg_event_instances AS i
            JOIN stg_alert_status_tokens AS s ON s.alert_id = i.alert_id
            LEFT JOIN dim_status_policy AS p ON p.status_token = s.status_token
            GROUP BY i.event_instance_id
        ),
        ranked AS (
            SELECT
                CASE WHEN ep.is_planned = 1 AND ep.has_significant = 1
                     THEN 'excluded_as_planned'
                     ELSE 'excluded_nonqualifying_status' END AS review_stratum,
                0 AS policy_assigned_label,
                i.event_instance_id,
                r.event_id,
                l.line,
                substr(r.published_at_local, 1, 13) || ':00:00'
                    AS prediction_hour_local,
                r.published_at_local,
                r.status_label,
                coalesce(r.header, '') AS header,
                row_number() OVER (
                    PARTITION BY i.event_instance_id, l.line
                    ORDER BY r.published_at_local, r.alert_id
                ) AS row_rank
            FROM raw_service_alerts AS r
            JOIN stg_event_instances AS i ON i.alert_id = r.alert_id
            JOIN stg_alert_lines AS l ON l.alert_id = r.alert_id
            JOIN event_policy AS ep ON ep.event_instance_id = i.event_instance_id
            WHERE (ep.is_planned = 1 AND ep.has_significant = 1)
               OR (ep.is_planned = 0 AND ep.has_significant = 0)
        )
        SELECT
            review_stratum,
            policy_assigned_label,
            event_instance_id,
            event_id,
            line,
            prediction_hour_local,
            published_at_local,
            status_label,
            header
        FROM ranked
        WHERE row_rank = 1
        """,
    )
    return positives + exclusions


def _stable_rank(row: dict[str, Any]) -> str:
    key = "|".join(
        str(row[column])
        for column in ("review_stratum", "event_instance_id", "line")
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _allocate_sample(rows: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    desired = {
        "included_positive": sample_size // 2,
        "excluded_as_planned": sample_size // 4,
        "excluded_nonqualifying_status": sample_size - (sample_size // 2 + sample_size // 4),
    }
    selected: list[dict[str, Any]] = []
    for stratum, count in desired.items():
        candidates = [row for row in rows if row["review_stratum"] == stratum]
        candidates.sort(key=_stable_rank)
        selected.extend(candidates[:count])
    selected.sort(key=lambda row: (row["review_stratum"], _stable_rank(row)))
    return selected


def write_label_review_sample(
    database_path: Path,
    output_path: Path,
    *,
    sample_size: int = 200,
    replace: bool = False,
) -> dict[str, Any]:
    if output_path.exists() and not replace:
        raise FileExistsError(f"Refusing to overwrite {output_path}; pass --replace")
    if not database_path.exists():
        raise FileNotFoundError(database_path)
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        sample = _allocate_sample(_candidate_rows(connection), sample_size)
    if len(sample) != sample_size:
        raise RuntimeError(
            f"Requested {sample_size} review rows but only selected {len(sample)}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=output_path.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in sample:
                writer.writerow(
                    {
                        **row,
                        "reviewer": "",
                        "is_significant_yes_no_uncertain": "",
                        "is_unplanned_yes_no_uncertain": "",
                        "policy_label_correct_yes_no_uncertain": "",
                        "review_notes": "",
                    }
                )
        os.replace(temp_path, output_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    counts: dict[str, int] = {}
    for row in sample:
        counts[row["review_stratum"]] = counts.get(row["review_stratum"], 0) + 1
    return {"output": str(output_path), "sample_size": len(sample), "strata": counts}
