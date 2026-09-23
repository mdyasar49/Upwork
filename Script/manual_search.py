#!/usr/bin/env python3
"""
Interactive & Custom Manual Search for Upwork Leads.

Allows entering custom search keywords and target locations manually.
Automatically creates a NEW TAB in the configured Google Sheet
and stores all newly scraped leads matching the 28 CRM columns.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"
MANUAL_OUTPUT_DIR = OUTPUT_DIR / "manual_searches"
LOG_DIR = PROJECT_DIR / "logs"

load_dotenv(SCRIPT_DIR / ".env")

from upwork_scraper import (
    OUTPUT_COLUMNS,
    ensure_dirs,
    run_upwork_scraper,
)
from sheets_sync import (
    SHEET_COLUMNS,
    append_upwork_records_to_sheet,
    open_worksheet,
)


def prompt_user_input() -> tuple[List[str], List[str], str, int, bool, bool]:
    """Interactive CLI prompts for manual search."""
    print("==================================================")
    print(" 🎯 UPWORK MANUAL LEAD SEARCH & NEW TAB CREATOR")
    print("==================================================")

    # 1. Keywords
    print("\n[Step 1/5] Enter Target Keywords (comma separated)")
    print("  Example: React.js, Python, Twilio, Web Scraping, Shopify")
    kw_input = input("  👉 Keywords: ").strip()
    if not kw_input:
        keywords = ["AI Integration", "React.js", "Python"]
        print(f"  [i] No input provided. Using defaults: {', '.join(keywords)}")
    else:
        keywords = [k.strip() for k in kw_input.split(",") if k.strip()]

    # 2. Locations
    print("\n[Step 2/5] Enter Target Locations (comma separated)")
    print("  Example: Australia, India, United States (or leave blank for Australia,India)")
    loc_input = input("  👉 Locations: ").strip()
    if not loc_input:
        locations = ["Australia", "India"]
        print(f"  [i] Using default locations: {', '.join(locations)}")
    else:
        locations = [l.strip() for l in loc_input.split(",") if l.strip()]

    # 3. New Tab Name
    default_tab_name = f"Search_{datetime.now().strftime('%Y%m%d_%H%M')}"
    print(f"\n[Step 3/5] Enter NEW Google Sheet Tab Name (Default: {default_tab_name})")
    tab_input = input("  👉 Tab Name: ").strip()
    tab_name = tab_input if tab_input else default_tab_name
    # Clean tab name (Google Sheets tab naming rules)
    tab_name = re.sub(r"[:\\/?*\[\]]", "_", tab_name)[:80]

    # 4. Limit
    print("\n[Step 4/5] Maximum Jobs to Scrape (Default: 30)")
    limit_input = input("  👉 Max Jobs: ").strip()
    try:
        limit = int(limit_input) if limit_input else 30
    except ValueError:
        limit = 30

    # 5. UI Mode & Deep Scrape
    print("\n[Step 5/5] Browser & Extraction Settings")
    headed_input = input("  👉 Visible Browser UI? (y/N, default: headless): ").strip().lower()
    headed = headed_input in {"y", "yes", "1"}

    deep_input = input("  👉 Deep Scrape Job Pages for detailed client history? (y/N, default: no): ").strip().lower()
    deep = deep_input in {"y", "yes", "1"}

    return keywords, locations, tab_name, limit, headed, deep


def run_manual_search(
    keywords: List[str],
    locations: List[str],
    tab_name: str,
    limit: int = 30,
    headed: bool = False,
    deep: bool = False,
    pages_per_keyword: int = 5,
) -> None:
    ensure_dirs()
    MANUAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n==================================================")
    print(f"🚀 Starting Manual Search...")
    print(f"  • Keywords  : {', '.join(keywords)}")
    print(f"  • Locations : {', '.join(locations)}")
    print(f"  • Target Tab: '{tab_name}'")
    print(f"  • Job Limit : {limit}")
    print(f"  • Mode      : {'Visible Browser' if headed else 'Headless'}")
    print("==================================================")

    # 1. Output CSV Path for this manual search session
    safe_tab_filename = re.sub(r"[^\w\-]", "_", tab_name)
    session_csv = MANUAL_OUTPUT_DIR / f"{safe_tab_filename}.csv"

    # 2. Run Scraper
    scraped_df = run_upwork_scraper(
        keywords=keywords,
        locations=locations,
        limit=limit,
        max_pages=pages_per_keyword,
        deep_scrape=deep,
        headless=not headed,
        output_csv=session_csv,
    )

    if scraped_df.empty:
        print("\n[!] No new job leads collected during this manual search.")
        return

    print(f"\n[✓] Scraped {len(scraped_df)} job leads saved locally to: {session_csv}")

    # 3. Create NEW TAB in Google Sheets and Sync
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "1qLxmNGGeuFuXnQnH4ITtnEGdaUpfzquIaf7wDHJpdD0").strip()
    if sheet_id:
        try:
            print(f"\n[+] Connecting to Google Sheet ID: {sheet_id}")
            print(f"[+] Creating/Opening Tab: '{tab_name}'...")
            
            worksheet = open_worksheet(sheet_id=sheet_id, tab_name=tab_name)
            
            # Ensure headers exist in the new tab
            if not worksheet.row_values(1):
                worksheet.append_row(SHEET_COLUMNS)
                print(f"[✓] Added 28 CRM columns header to new tab '{tab_name}'.")

            print(f"[+] Synchronizing {len(scraped_df)} leads to tab '{tab_name}'...")
            appended = append_upwork_records_to_sheet(scraped_df, worksheet=worksheet)

            sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={worksheet.id}"
            print("\n==================================================")
            print(f"🎉 SUCCESS! {appended} leads added to NEW Google Sheet Tab!")
            print(f"🔗 View Live Tab: {sheet_url}")
            print("==================================================")

        except Exception as e:
            print(f"\n[!] Error synchronizing to Google Sheet: {e}")
            print(f"[i] All leads are safely preserved locally at: {session_csv}")
    else:
        print("\n[i] GOOGLE_SHEET_ID not set. Data saved to local CSV.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual Upwork Search & New Tab Creator")
    parser.add_argument("--keywords", type=str, default=None, help="Keywords separated by comma")
    parser.add_argument("--locations", type=str, default=None, help="Locations separated by comma (e.g. Australia,India)")
    parser.add_argument("--tab", type=str, default=None, help="New Google Sheet tab name to create")
    parser.add_argument("--limit", type=int, default=None, help="Maximum jobs to scrape")
    parser.add_argument("--pages", type=int, default=5, help="Pages per keyword")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window")
    parser.add_argument("--deep", action="store_true", help="Enable deep job page extraction")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # If CLI arguments are not provided, launch interactive prompt mode
    if not args.keywords and not args.tab:
        keywords, locations, tab_name, limit, headed, deep = prompt_user_input()
        run_manual_search(
            keywords=keywords,
            locations=locations,
            tab_name=tab_name,
            limit=limit,
            headed=headed,
            deep=deep,
        )
    else:
        # CLI Argument Mode
        kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else ["React.js", "Python"]
        loc_list = [l.strip() for l in args.locations.split(",") if l.strip()] if args.locations else ["Australia", "India"]
        tab = args.tab or f"Manual_{datetime.now().strftime('%Y%m%d_%H%M')}"
        lim = args.limit or 30

        run_manual_search(
            keywords=kw_list,
            locations=loc_list,
            tab_name=tab,
            limit=lim,
            headed=args.headed,
            deep=args.deep,
            pages_per_keyword=args.pages,
        )


if __name__ == "__main__":
    main()
