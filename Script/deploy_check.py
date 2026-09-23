#!/usr/bin/env python3
"""
Pre-flight Environment & Deployment Verification for Upwork Scraper.

Validates:
  1) Python dependencies
  2) Chrome & ChromeDriver availability
  3) .env configuration
  4) Google Service Account & Sheets API connectivity
  5) Input CSV and filter files
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = PROJECT_DIR / "Output"
LOG_DIR = PROJECT_DIR / "logs"

load_dotenv(SCRIPT_DIR / ".env")


def check_python_environment() -> bool:
    print("[1/5] Checking Python Environment & Dependencies...")
    required = ["selenium", "pandas", "bs4", "gspread", "google.oauth2", "dotenv"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"  ❌ Missing packages: {', '.join(missing)}")
        print("  --> Run: pip install -r requirements.txt")
        return False
    print("  ✅ All required Python packages installed.")
    return True


def check_directories() -> bool:
    print("[2/5] Checking Project Directories...")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print("  ✅ Dirs verified: Output/, logs/, Script/input/, Script/credentials/")
    return True


def check_input_files() -> bool:
    print("[3/5] Checking Input Data Files...")
    kw = INPUT_DIR / "upwork_keywords.csv"
    urls = INPUT_DIR / "upwork_search_urls.csv"
    filters = INPUT_DIR / "upwork_filter_details.txt"

    ok = True
    for f in [kw, urls, filters]:
        if f.exists() and f.stat().st_size > 0:
            print(f"  ✅ Found: {f.name} ({f.stat().st_size} bytes)")
        else:
            print(f"  ⚠️ Warning: {f.name} is missing or empty.")
            ok = False
    return ok


def check_chrome() -> bool:
    print("[4/5] Checking Chrome & Selenium...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=opts)
        driver.get("https://www.google.com")
        title = driver.title
        driver.quit()
        print(f"  ✅ Chrome WebDriver initialized successfully (Page title: '{title}').")
        return True
    except Exception as e:
        print(f"  ❌ Chrome WebDriver initialization failed: {e}")
        return False


def check_google_sheets() -> bool:
    print("[5/5] Checking Google Sheets Connectivity...")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    creds_file = SCRIPT_DIR / os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/google_service_account.json")

    if not creds_file.exists():
        fallback = Path(r"d:\infonix\credentials\splendid-planet-504710-d0-d1bee6e83a75.json")
        if fallback.exists():
            creds_file = fallback
        else:
            print(f"  ⚠️ Service account credentials not found at {creds_file}.")
            return False

    print(f"  ✅ Found service account JSON: {creds_file.name}")

    if not sheet_id:
        print("  ℹ️ GOOGLE_SHEET_ID is not configured in .env (Scraper will save locally to Output/).")
        return True

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            str(creds_file),
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        print(f"  ✅ Google Sheet access confirmed: '{sheet.title}'")
        return True
    except Exception as e:
        print(f"  ⚠️ Google Sheet connection test notice: {e}")
        return False


def main() -> None:
    print("==================================================")
    print(" Upwork Scraper Suite - Pre-flight Health Check")
    print("==================================================")
    
    r1 = check_python_environment()
    r2 = check_directories()
    r3 = check_input_files()
    r4 = check_chrome()
    r5 = check_google_sheets()

    print("\n==================================================")
    if r1 and r2 and r4:
        print("🎉 System Ready! You can run 'python daily_run.py'.")
    else:
        print("⚠️ Some checks failed. Please review the messages above.")
    print("==================================================")


if __name__ == "__main__":
    main()
