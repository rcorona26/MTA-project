from __future__ import annotations

import csv
import hashlib
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mta_delay.constants import SCHEDULE_DATASETS, SCHEDULE_SOURCE_COLUMNS
from mta_delay.download import _atomic_json, _read_socrata_json


def _next_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


def _schedule_rows(dataset_id: str, year: int, month: int) -> list[dict[str, Any]]:
    start = date(year, month, 1)
    end = _next_month(year, month)
    resource_url = f"https://data.ny.gov/resource/{dataset_id}.json"
    rows = _read_socrata_json(
        resource_url,
        {
            "$select": (
                "date_trunc_ymd(departure_time) as departure_date,"
                "date_extract_hh(departure_time) as departure_hour,"
                "trip_line,count(*) as scheduled_revenue_stop_departures"
            ),
            "$where": (
                f"departure_time >= '{start.isoformat()}T00:00:00.000' "
                f"AND departure_time < '{end.isoformat()}T00:00:00.000' "
                "AND departure_time is not null "
                "AND trip_type='0' AND revenue_service='1'"
            ),
            "$group": "departure_date,departure_hour,trip_line",
            "$order": "departure_date,departure_hour,trip_line",
            "$limit": 50_000,
        },
    )
    if len(rows) >= 50_000:
        raise RuntimeError(
            f"Schedule aggregate for {year}-{month:02d} reached the safety limit"
        )
    return rows


def download_schedule_line_hours(
    output_path: Path,
    manifest_path: Path,
    *,
    dataset_ids: dict[int, str] | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Download official schedules already aggregated to route/date/hour."""
    datasets = dict(dataset_ids or SCHEDULE_DATASETS)
    if not datasets:
        raise ValueError("At least one schedule dataset is required")
    for path in (output_path, manifest_path):
        if path.exists() and not replace:
            raise FileExistsError(f"Refusing to overwrite {path}; pass --replace")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=output_path.parent, delete=False
    )
    temp_path = Path(handle.name)
    digest = hashlib.sha256()
    row_count = 0
    dataset_summaries: list[dict[str, Any]] = []

    try:
        with handle:
            writer = csv.DictWriter(
                handle, fieldnames=SCHEDULE_SOURCE_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            for year, dataset_id in sorted(datasets.items()):
                dataset_rows = 0
                minimum: str | None = None
                maximum: str | None = None
                with ThreadPoolExecutor(max_workers=6) as executor:
                    monthly_rows = {
                        month: executor.submit(_schedule_rows, dataset_id, year, month)
                        for month in range(1, 13)
                    }
                    results = [
                        (month, monthly_rows[month].result())
                        for month in range(1, 13)
                    ]
                for month, rows in results:
                    for row in rows:
                        departure_date = str(row["departure_date"])[:10]
                        departure_hour = int(row["departure_hour"])
                        scheduled_departures = int(
                            row["scheduled_revenue_stop_departures"]
                        )
                        if not 0 <= departure_hour <= 23 or scheduled_departures <= 0:
                            raise RuntimeError("Official schedule aggregate was invalid")
                        writer.writerow(
                            {
                                "dataset_year": year,
                                "dataset_id": dataset_id,
                                "departure_date": departure_date,
                                "departure_hour": departure_hour,
                                "trip_line": str(row["trip_line"]).strip().upper(),
                                "scheduled_revenue_stop_departures": scheduled_departures,
                            }
                        )
                        minimum = min(minimum, departure_date) if minimum else departure_date
                        maximum = max(maximum, departure_date) if maximum else departure_date
                        dataset_rows += 1
                        row_count += 1
                dataset_summaries.append(
                    {
                        "year": year,
                        "dataset_id": dataset_id,
                        "rows": dataset_rows,
                        "min_departure_date": minimum,
                        "max_departure_date": maximum,
                    }
                )

        with temp_path.open("rb") as downloaded:
            for chunk in iter(lambda: downloaded.read(1024 * 1024), b""):
                digest.update(chunk)
        os.replace(temp_path, output_path)
        manifest = {
            "dataset_name": "MTA Subway Schedules annual datasets",
            "dataset_pages": {
                str(year): f"https://data.ny.gov/d/{dataset_id}"
                for year, dataset_id in sorted(datasets.items())
            },
            "aggregation": (
                "departure date x departure hour x trip_line; count of scheduled "
                "departures from revenue stops"
            ),
            "filters": "trip_type='0' AND revenue_service='1'",
            "retrieved_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "downloaded_rows": row_count,
            "sha256": digest.hexdigest(),
            "columns": list(SCHEDULE_SOURCE_COLUMNS),
            "datasets": dataset_summaries,
            "known_gap": "No annual official MTA Subway Schedules dataset was found for 2020.",
        }
        _atomic_json(manifest_path, manifest)
        return manifest
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
