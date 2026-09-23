#!/usr/bin/env python3
"""
Daily Upwork Scraper & Sync Runner.

Automates scheduled execution of the Upwork scraper:
  1) Reads default 1,502 keywords and default locations (Australia & India)
  2) Runs scraper to extract new job opportunities
  3) Performs local and remote deduplication
  4) Appends new records to Output/upwork_job_leads.csv
  5) Pushes new leads directly into Google Sheet (Sheet1) matching the 28 CRM columns
  6) Logs full execution metrics to logs/daily_run_YYYYMMDD.log
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"
LOG_DIR = PROJECT_DIR / "logs"

sys.path.insert(0, str(SCRIPT_DIR))
load_dotenv(SCRIPT_DIR / ".env")

from upwork_scraper import (  # noqa: E402
    DEFAULT_LOCATIONS,
    OUTPUT_JOBS_CSV,
    ensure_dirs,
    load_keywords,
    run_upwork_scraper,
)
from sheets_sync import (  # noqa: E402
    append_upwork_records_to_sheet,
    open_worksheet,
)


def log(msg: str) -> None:
    ensure_dirs()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    log_file = LOG_DIR / f"daily_run_{datetime.now().strftime('%Y%m%d')}.log"
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_daily(
    limit: int | None = None,
    locations: Optional[List[str]] = None,
    pages: int = 5,
    deep: bool = False,
    headless: bool = True,
    sync_sheet: bool = True,
) -> None:
    ensure_dirs()
    target_locations = locations or DEFAULT_LOCATIONS
    scrape_limit = limit or int(os.environ.get("DAILY_SCRAPE_LIMIT", "50"))
    log(f"--- Starting Daily Upwork Run (limit={scrape_limit}, locations={', '.join(target_locations)}, pages={pages}) ---")

    try:
        # 1. Run Scraper
        scraped_df = run_upwork_scraper(
            locations=target_locations,
            limit=scrape_limit,
            max_pages=pages,
            deep_scrape=deep,
            headless=headless,
            output_csv=OUTPUT_JOBS_CSV,
        )
        
        log(f"Scraper execution completed. Newly scraped records: {len(scraped_df)}")

        if scraped_df.empty:
            log("No new jobs found in this run. Finished.")
            return

        # 2. Google Sheets Sync
        skip_sheets = os.environ.get("SKIP_GOOGLE_SHEETS", "false").lower() in {"1", "true", "yes"}
        if sync_sheet and not skip_sheets and os.environ.get("GOOGLE_SHEET_ID"):
            try:
                log("Starting Google Sheets synchronization...")
                appended_count = append_upwork_records_to_sheet(scraped_df)
                log(f"Google Sheets sync finished. Appended {appended_count} new row(s) to Sheet1.")
            except Exception as se:
                log(f"Google Sheets sync encountered an error: {se}")
        else:
            log("Google Sheets sync skipped (SKIP_GOOGLE_SHEETS=true or GOOGLE_SHEET_ID missing).")

        log("--- Daily Run Completed Successfully ---")

    except Exception as e:
        log(f"Fatal error during daily run: {e}")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Upwork Scraper Runner")
    parser.add_argument("--limit", type=int, default=None, help="Job limit for this run")
    parser.add_argument("--locations", type=str, default="Australia,India", help="Target locations separated by comma")
    parser.add_argument("--pages", type=int, default=5, help="Max pages per keyword")
    parser.add_argument("--deep", action="store_true", help="Enable deep page extraction")
    parser.add_argument("--headed", action="store_true", help="Run in visible browser mode")
    parser.add_argument("--skip-sheets", action="store_true", help="Skip Google Sheets sync")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    locs = [l.strip() for l in args.locations.split(",") if l.strip()]
    run_daily(
        limit=args.limit,
        locations=locs,
        pages=args.pages,
        deep=args.deep,
        headless=not args.headed,
        sync_sheet=not args.skip_sheets,
    )


if __name__ == "__main__":
    main()
