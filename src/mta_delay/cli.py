from __future__ import annotations

import argparse
import json
from pathlib import Path

from mta_delay.download import download_alerts
from mta_delay.pipeline import build_database
from mta_delay.review import write_label_review_sample
from mta_delay.schedules import download_schedule_line_hours


def _add_download_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/mta_service_alerts_nyct.csv"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/raw/mta_service_alerts_nyct.manifest.json"),
    )
    parser.add_argument("--page-size", type=int, default=50_000)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--replace", action="store_true")


def _add_build_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/mta_service_alerts_nyct.csv"),
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processed/mta_alerts.sqlite"),
    )
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=Path("data/processed/quality_report.json"),
    )
    parser.add_argument(
        "--schedule-input",
        type=Path,
        default=Path("data/raw/mta_subway_schedule_line_hours.csv"),
    )
    parser.add_argument("--replace", action="store_true")


def _add_download_schedule_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/mta_subway_schedule_line_hours.csv"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/raw/mta_subway_schedule_line_hours.manifest.json"),
    )
    parser.add_argument("--replace", action="store_true")


def _add_review_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processed/mta_alerts.sqlite"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/review/label_review_sample.csv"),
    )
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--replace", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mta-alerts",
        description="Build the MTA line-hour significant-disruption target.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_download_arguments(subparsers.add_parser("download"))
    _add_download_schedule_arguments(subparsers.add_parser("download-schedules"))
    _add_build_arguments(subparsers.add_parser("build"))
    _add_review_arguments(subparsers.add_parser("review-sample"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "download":
        result = download_alerts(
            args.output,
            args.manifest,
            page_size=args.page_size,
            limit=args.limit,
            replace=args.replace,
        )
    elif args.command == "download-schedules":
        result = download_schedule_line_hours(
            args.output,
            args.manifest,
            replace=args.replace,
        )
    elif args.command == "build":
        result = build_database(
            args.input,
            args.database,
            args.quality_report,
            schedule_path=args.schedule_input,
            replace=args.replace,
        )
    else:
        result = write_label_review_sample(
            args.database,
            args.output,
            sample_size=args.sample_size,
            replace=args.replace,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
