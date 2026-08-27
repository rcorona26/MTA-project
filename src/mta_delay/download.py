from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mta_delay.constants import (
    DATASET_ID,
    DATASET_NAME,
    DATASET_PAGE,
    SOCRATA_RESOURCE_URL,
    SOURCE_COLUMNS,
    SUBWAY_AGENCY,
)


def _read_socrata_json(
    resource_url: str,
    params: dict[str, str | int],
    attempts: int = 4,
) -> list[dict[str, Any]]:
    url = f"{resource_url}?{urlencode(params)}"
    headers = {"User-Agent": "mta-delay-prediction/0.1"}
    app_token = os.getenv("SOCRATA_APP_TOKEN")
    if app_token:
        headers["X-App-Token"] = app_token

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers=headers), timeout=60) as response:
                payload = json.load(response)
            if not isinstance(payload, list):
                raise ValueError("Socrata response was not a JSON list")
            return payload
        except Exception as exc:  # network failures vary by Python/platform
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"Socrata request failed after {attempts} attempts: {url}") from last_error


def _read_json(params: dict[str, str | int], attempts: int = 4) -> list[dict[str, Any]]:
    return _read_socrata_json(SOCRATA_RESOURCE_URL, params, attempts)


def _snapshot_boundary() -> dict[str, str]:
    rows = _read_json(
        {
            "$select": "max(alert_id) as max_alert_id,max(date) as max_date,count(*) as row_count",
            "$where": f"agency='{SUBWAY_AGENCY}'",
        }
    )
    if len(rows) != 1 or not rows[0].get("max_alert_id"):
        raise RuntimeError("Could not determine a stable source snapshot boundary")
    return {key: str(value) for key, value in rows[0].items()}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def download_alerts(
    output_path: Path,
    manifest_path: Path,
    *,
    page_size: int = 50_000,
    limit: int | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Download a stable, keyset-paginated NYCT Subway alert snapshot."""
    if not 1 <= page_size <= 50_000:
        raise ValueError("page_size must be between 1 and 50,000")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    for path in (output_path, manifest_path):
        if path.exists() and not replace:
            raise FileExistsError(f"Refusing to overwrite {path}; pass --replace")

    boundary = _snapshot_boundary()
    cutoff_alert_id = int(boundary["max_alert_id"])
    source_row_count = int(boundary["row_count"])
    expected_rows = min(source_row_count, limit) if limit else source_row_count
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=output_path.parent, delete=False
    )
    temp_path = Path(handle.name)
    row_count = 0
    last_alert_id = 0
    digest = hashlib.sha256()

    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
            writer.writeheader()

            while row_count < expected_rows:
                requested = min(page_size, expected_rows - row_count)
                where = (
                    f"agency='{SUBWAY_AGENCY}' AND alert_id>{last_alert_id} "
                    f"AND alert_id<={cutoff_alert_id}"
                )
                rows = _read_json(
                    {
                        "$select": ",".join(SOURCE_COLUMNS),
                        "$where": where,
                        "$order": "alert_id ASC",
                        "$limit": requested,
                    }
                )
                if not rows:
                    break

                for row in rows:
                    alert_id = int(row["alert_id"])
                    if alert_id <= last_alert_id:
                        raise RuntimeError("Socrata keyset pagination was not strictly increasing")
                    last_alert_id = alert_id
                    writer.writerow({column: row.get(column, "") for column in SOURCE_COLUMNS})
                    row_count += 1

        if row_count != expected_rows:
            raise RuntimeError(
                f"Expected {expected_rows:,} source rows but downloaded {row_count:,}"
            )

        with temp_path.open("rb") as downloaded:
            for chunk in iter(lambda: downloaded.read(1024 * 1024), b""):
                digest.update(chunk)

        os.replace(temp_path, output_path)
        manifest = {
            "dataset_id": DATASET_ID,
            "dataset_name": DATASET_NAME,
            "dataset_page": DATASET_PAGE,
            "resource_url": SOCRATA_RESOURCE_URL,
            "agency_filter": SUBWAY_AGENCY,
            "cutoff_alert_id": cutoff_alert_id,
            "cutoff_published_at_local": boundary.get("max_date"),
            "source_rows_at_cutoff": source_row_count,
            "downloaded_rows": row_count,
            "limited_download": limit is not None,
            "retrieved_at_utc": retrieved_at,
            "sha256": digest.hexdigest(),
            "columns": list(SOURCE_COLUMNS),
            "ordering": "alert_id ASC",
        }
        _atomic_json(manifest_path, manifest)
        return manifest
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
