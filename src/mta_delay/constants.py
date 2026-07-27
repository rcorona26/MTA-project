from __future__ import annotations

DATASET_ID = "7kct-peq7"
DATASET_NAME = "MTA Service Alerts: Beginning April 2020"
DATASET_PAGE = (
    "https://data.ny.gov/Transportation/"
    "MTA-Service-Alerts-Beginning-April-2020/7kct-peq7"
)
SOCRATA_RESOURCE_URL = f"https://data.ny.gov/resource/{DATASET_ID}.json"
SUBWAY_AGENCY = "NYCT Subway"

SOURCE_COLUMNS = (
    "alert_id",
    "event_id",
    "update_number",
    "date",
    "agency",
    "status_label",
    "affected",
    "header",
    "description",
)

CANONICAL_LINES = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "FS",
    "G",
    "GS",
    "H",
    "J",
    "L",
    "M",
    "N",
    "Q",
    "R",
    "W",
    "Z",
)

LINE_ALIASES = {
    "5X": "5",
    "6X": "6",
    "7X": "7",
    "FX": "F",
}

SCHEDULE_DATASETS = {
    2021: "y63v-kht3",
    2022: "rq86-r8pt",
    2023: "7pnn-mafy",
    2024: "ebrw-j62c",
    2025: "q9nv-uegs",
    2026: "g8es-h7gb",
}

SCHEDULE_SOURCE_COLUMNS = (
    "dataset_year",
    "dataset_id",
    "departure_date",
    "departure_hour",
    "trip_line",
    "scheduled_revenue_stop_departures",
)

SIGNIFICANT_STATUS_TOKENS = frozenset(
    {
        "delays",
        "severe-delays",
        "part-suspended",
        "suspended",
    }
)

PLANNED_STATUS_TOKENS = frozenset(
    {
        "planned-work",
        "weekday-service",
        "weekend-service",
        "saturday-schedule",
        "sunday-schedule",
        "essential-service",
        "no-scheduled-service",
    }
)
