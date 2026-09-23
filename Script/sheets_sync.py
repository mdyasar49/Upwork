#!/usr/bin/env python3
"""
Google Sheets Sync module for Upwork Lead Scraper.

Synchronizes scraped Upwork jobs and leads directly into the CRM Google Sheet (Sheet1)
matching the exact 28 enterprise CRM columns.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import gspread
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"

DEFAULT_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "1qLxmNGGeuFuXnQnH4ITtnEGdaUpfzquIaf7wDHJpdD0")
DEFAULT_SHEET_TAB = os.environ.get("GOOGLE_SHEET_TAB", "Sheet1")
DEFAULT_CREDS_FILE = SCRIPT_DIR / os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/google_service_account.json")

# Exact 28 CRM Columns Matching the Google Sheet
SHEET_COLUMNS = [
    "Date",
    "Lead Source",
    "Company",
    "Company Founded Year",
    "Account Created Year",
    "First Name",
    "Last Name",
    "Customer Name",
    "Designation / Title",
    "Email",
    "Phone Number",
    "Mobile Number",
    "Industry",
    "Company Size",
    "Key Technologies / Skills",
    "Lead Status",
    "Rating",
    "Annual Revenue / Budget",
    "Street",
    "City",
    "State",
    "Country",
    "Website / URL",
    "Media Type (Image / Video / Reel / Flyer)",
    "Data Extracted From",
    "Lead Added By",
    "CRM_Synced",
    "Notes / Description (OCR & Video Analysis Insights)",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_service_account_credentials(creds_path: Optional[Path] = None) -> Credentials:
    path = creds_path or DEFAULT_CREDS_FILE
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    if not path.exists():
        fallback = Path(r"d:\infonix\credentials\splendid-planet-504710-d0-d1bee6e83a75.json")
        if fallback.exists():
            path = fallback
        else:
            raise FileNotFoundError(f"Service account credentials not found at: {path}")
            
    return Credentials.from_service_account_file(str(path), scopes=SCOPES)


def open_worksheet(
    sheet_id: Optional[str] = None,
    tab_name: Optional[str] = None,
    creds_path: Optional[Path] = None,
) -> gspread.Worksheet:
    sheet_id = sheet_id or DEFAULT_SHEET_ID
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID is not set in .env")

    tab_name = tab_name or DEFAULT_SHEET_TAB
    creds = get_service_account_credentials(creds_path)
    client = gspread.authorize(creds)
    
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(SHEET_COLUMNS))
        worksheet.append_row(SHEET_COLUMNS)
        print(f"[+] Created new tab '{tab_name}' with header row.")
        
    return worksheet


def existing_sheet_job_urls(worksheet: gspread.Worksheet) -> Set[str]:
    try:
        col_values = worksheet.col_values(23)  # Column 23 is Website / URL
        urls = set()
        for u in col_values[1:]:  # Skip header
            if u:
                clean_u = str(u).strip().split("?")[0]
                urls.add(clean_u)
        return urls
    except Exception as e:
        print(f"[!] Warning reading existing sheet URLs: {e}")
        return set()


def map_upwork_record_to_crm_row(rec: Dict[str, Any]) -> List[str]:
    """Maps an Upwork scraped job record to the 28 Google Sheet CRM columns."""
    date_str = datetime.now().strftime("%d/%m/%Y")
    lead_source = os.environ.get("LEAD_SOURCE", "Upwork")
    lead_status = os.environ.get("LEAD_STATUS", "New")
    lead_added_by = os.environ.get("LEAD_ADDED_BY", "Upwork Scraper")
    crm_synced = os.environ.get("CRM_SYNCED_DEFAULT", "Pending")

    title = str(rec.get("Job_Title", "")).strip()
    client_name = str(rec.get("Client_Name", "")).strip()
    if not client_name or client_name.lower() in {"n/a", "none"}:
        client_name = "Upwork Client"
        first_name = "Upwork"
        last_name = "Client"
    else:
        parts = client_name.split()
        first_name = parts[0] if parts else "Client"
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    # Budget formatting
    budget_raw = str(rec.get("Budget", "")).strip()
    hourly_min = str(rec.get("Hourly_Min", "")).strip()
    hourly_max = str(rec.get("Hourly_Max", "")).strip()
    
    if budget_raw and budget_raw not in {"", "N/A", "None"}:
        annual_budget = f"${budget_raw}"
    elif hourly_min or hourly_max:
        annual_budget = f"${hourly_min}-${hourly_max}/hr" if (hourly_min and hourly_max and hourly_min != hourly_max) else f"${hourly_min or hourly_max}/hr"
    else:
        annual_budget = "Negotiable / Open"

    # Location & Country
    location_raw = str(rec.get("Client_Location", "")).strip()
    city = ""
    country = "Australia"
    if "india" in location_raw.lower():
        country = "India"
        city = location_raw.replace("India", "").strip(", ")
    elif "australia" in location_raw.lower():
        country = "Australia"
        city = location_raw.replace("Australia", "").strip(", ")
    elif location_raw:
        city = location_raw
        country = location_raw

    # Year
    member_since = str(rec.get("Client_Member_Since", "")).strip()
    year_match = re.search(r"\b(20\d\d|19\d\d)\b", member_since)
    year_val = year_match.group(1) if year_match else ""

    # Rating
    rating_val = str(rec.get("Client_Rating", "")).strip()
    if not rating_val or rating_val in {"", "N/A"}:
        rating_val = "Hot"

    # Notes & Description
    description = str(rec.get("Description", "")).strip()
    skills = str(rec.get("Skills", "")).strip()
    proposals = str(rec.get("Proposals", "")).strip()
    notes = f"Budget: {annual_budget} | Proposals: {proposals or 'N/A'} | Skills: {skills} | Scope: {description[:800]}"

    url = str(rec.get("Job_URL", "")).strip()
    email = str(rec.get("Email_Address", "")).strip()
    phone = str(rec.get("Contact_Number", "")).strip()

    return [
        date_str,                                              # 1. Date
        lead_source,                                           # 2. Lead Source
        title[:120],                                           # 3. Company / Job Subject
        year_val,                                              # 4. Company Founded Year
        year_val,                                              # 5. Account Created Year
        first_name,                                            # 6. First Name
        last_name,                                             # 7. Last Name
        client_name,                                           # 8. Customer Name
        "Hiring Manager / Project Owner",                      # 9. Designation / Title
        email,                                                 # 10. Email
        phone,                                                 # 11. Phone Number
        phone,                                                 # 12. Mobile Number
        "Software & Web Development",                          # 13. Industry
        str(rec.get("Client_Hires", "Verified Client")),       # 14. Company Size
        skills[:250],                                          # 15. Key Technologies / Skills
        lead_status,                                           # 16. Lead Status
        rating_val,                                            # 17. Rating
        annual_budget,                                         # 18. Annual Revenue / Budget
        "",                                                    # 19. Street
        city,                                                  # 20. City
        "",                                                    # 21. State
        country,                                               # 22. Country
        url,                                                   # 23. Website / URL
        "Job Requirements Brief & Scope Document",             # 24. Media Type
        "Upwork Verified Client Feed",                         # 25. Data Extracted From
        lead_added_by,                                         # 26. Lead Added By
        crm_synced,                                            # 27. CRM_Synced
        notes[:1500],                                          # 28. Notes / Description
    ]


def append_upwork_records_to_sheet(
    df_or_records: pd.DataFrame | List[Dict[str, Any]],
    worksheet: Optional[gspread.Worksheet] = None,
    sheet_id: Optional[str] = None,
    tab_name: Optional[str] = None,
) -> int:
    """Appends new scraped Upwork records to Google Sheets matching the 28 columns."""
    if isinstance(df_or_records, pd.DataFrame):
        records = df_or_records.to_dict(orient="records")
    else:
        records = df_or_records

    if not records:
        print("[i] No records to sync to Google Sheet.")
        return 0

    if worksheet is None:
        worksheet = open_worksheet(sheet_id=sheet_id, tab_name=tab_name)

    existing_headers = worksheet.row_values(1)
    if not existing_headers:
        worksheet.append_row(SHEET_COLUMNS)

    existing_urls = existing_sheet_job_urls(worksheet)
    rows_to_append = []

    for rec in records:
        url = str(rec.get("Job_URL", "")).strip()
        clean_url = url.split("?")[0]
        if clean_url in existing_urls:
            continue

        row_data = map_upwork_record_to_crm_row(rec)
        rows_to_append.append(row_data)
        existing_urls.add(clean_url)

    if rows_to_append:
        worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print(f"[✓] Successfully appended {len(rows_to_append)} rows to Google Sheet ('{worksheet.spreadsheet.title}' -> '{worksheet.title}').")
        return len(rows_to_append)
    else:
        print("[i] All records are already present in Google Sheet. No new rows added.")
        return 0


def sync_local_csv_to_sheet(csv_path: Optional[Path] = None) -> None:
    csv_file = csv_path or (OUTPUT_DIR / "upwork_job_leads.csv")
    if not csv_file.exists() or csv_file.stat().st_size == 0:
        print(f"[!] CSV file not found or empty: {csv_file}")
        return

    df = pd.read_csv(csv_file)
    print(f"[+] Loaded {len(df)} rows from {csv_file.name}. Syncing to Google Sheets...")
    append_upwork_records_to_sheet(df)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sync_local_csv_to_sheet(Path(sys.argv[1]))
    else:
        sync_local_csv_to_sheet()
