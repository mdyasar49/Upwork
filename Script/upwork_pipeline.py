#!/usr/bin/env python3
"""
Upwork Continuous Discovery & Scraping Pipeline.

Iterates across high-priority keywords, search URL matrices, and regional filters
to collect up to a target quota of unique leads (e.g. 800 leads) with automatic
checkpointing, deduplication, and Google Sheet synchronization.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"
LOG_DIR = PROJECT_DIR / "logs"

load_dotenv(SCRIPT_DIR / ".env")

from upwork_scraper import (
    OUTPUT_JOBS_CSV,
    ensure_dirs,
    load_existing_job_urls,
    load_keywords,
    run_upwork_scraper,
)
from sheets_sync import append_upwork_records_to_sheet


def run_pipeline(
    target_leads: int = 800,
    location: str = "Australia",
    pages_per_keyword: int = 10,
    deep: bool = False,
    headless: bool = True,
    sync_sheets: bool = True,
) -> None:
    ensure_dirs()
    print("==================================================")
    print(f"🚀 Upwork Continuous Lead Pipeline (Target: {target_leads} leads)")
    print("==================================================")

    keywords = load_keywords()
    existing_urls = load_existing_job_urls([OUTPUT_JOBS_CSV])
    current_count = len(existing_urls)
    print(f"[+] Current unique leads in database: {current_count}/{target_leads}")

    if current_count >= target_leads:
        print(f"[✓] Target quota already fulfilled ({current_count} >= {target_leads}).")
        return

    needed = target_leads - current_count
    print(f"[+] Need to collect {needed} more leads.")

    df_scraped = run_upwork_scraper(
        keywords=keywords,
        search_location=location,
        limit=needed,
        max_pages=pages_per_keyword,
        deep_scrape=deep,
        headless=headless,
        output_csv=OUTPUT_JOBS_CSV,
    )

    if not df_scraped.empty and sync_sheets:
        skip_sheets = os.environ.get("SKIP_GOOGLE_SHEETS", "false").lower() in {"1", "true", "yes"}
        if not skip_sheets and os.environ.get("GOOGLE_SHEET_ID"):
            try:
                print("\n[+] Synchronizing new pipeline records to Google Sheets...")
                append_upwork_records_to_sheet(df_scraped)
            except Exception as e:
                print(f"[!] Sheet sync error: {e}")

    updated_count = len(load_existing_job_urls([OUTPUT_JOBS_CSV]))
    print("\n==================================================")
    print(f"🎉 Pipeline Batch Finished. Total Unique Leads Now: {updated_count}/{target_leads}")
    print("==================================================")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upwork Continuous Pipeline")
    parser.add_argument("--target", type=int, default=800, help="Target total leads count (default: 800)")
    parser.add_argument("--location", type=str, default="Australia", help="Search location")
    parser.add_argument("--pages", type=int, default=10, help="Pages per keyword")
    parser.add_argument("--deep", action="store_true", help="Deep page scrape")
    parser.add_argument("--headed", action="store_true", help="Visible UI mode")
    parser.add_argument("--skip-sheets", action="store_true", help="Skip Google Sheets")
    args = parser.parse_args()

    run_pipeline(
        target_leads=args.target,
        location=args.location,
        pages_per_keyword=args.pages,
        deep=args.deep,
        headless=not args.headed,
        sync_sheets=not args.skip_sheets,
    )


if __name__ == "__main__":
    main()
