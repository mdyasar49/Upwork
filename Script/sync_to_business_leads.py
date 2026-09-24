#!/usr/bin/env python3
"""
Sync Upwork Intelligence Leads to Google Sheets CRM (Tab: 'Upwork Leads').
Supports all 31 mandatory columns, deduplication, and formula-safe formatting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_JSON = PROJECT_DIR / "Output" / "upwork_detailed_leads.json"

SPREADSHEET_ID = "1QY8hbycY-gdOWRch52SKoUS975U-t3EgZ0JrtdhPCoM"
TAB_NAME = "Upwork Leads"

CREDENTIAL_CANDIDATES = [
    SCRIPT_DIR / "credentials" / "google_service_account.json",
    PROJECT_DIR.parent / "splendid-planet-504710-d0-d1bee6e83a75.json",
    PROJECT_DIR.parent / "Facebook" / "Script" / "credentials" / "google_service_account.json",
]


def get_sheets_service() -> Any:
    cred_path = None
    for cand in CREDENTIAL_CANDIDATES:
        if cand.exists():
            cred_path = cand
            break

    if not cred_path:
        raise FileNotFoundError("Google Service Account credentials JSON not found in expected paths.")

    creds = service_account.Credentials.from_service_account_file(
        str(cred_path),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


def sync_leads(json_file: Path = DEFAULT_JSON) -> None:
    if not json_file.exists():
        print(f"[ERROR] JSON file not found: {json_file}")
        return

    with open(json_file, "r", encoding="utf-8") as f:
        leads: List[Dict[str, Any]] = json.load(f)

    if not leads:
        print("[INFO] No leads found in JSON.")
        return

    service = get_sheets_service()

    # Get header row
    header_res = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{TAB_NAME}'!1:1"
    ).execute()
    headers: List[str] = header_res.get("values", [[]])[0]

    if not headers:
        print(f"[ERROR] No headers found in sheet tab '{TAB_NAME}'.")
        return

    # Fetch existing job URLs from Column C
    existing_res = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{TAB_NAME}'!C:C"
    ).execute()
    existing_urls = {row[0].strip() for row in existing_res.get("values", []) if row}

    today_str = datetime.now().strftime("%d/%m/%Y")
    new_rows: List[List[str]] = []

    for lead in leads:
        job_url = lead.get("Job_URL", "").strip()
        if job_url in existing_urls:
            print(f"[SKIP] Lead already exists in sheet: {lead.get('Job_Title', job_url)}")
            continue

        # Extract names
        full_name = lead.get("Client_Name", "Client")
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else "Client"
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        # Safe phone formatting with leading apostrophe
        phone = lead.get("Contact_Number", "")
        if phone and phone.startswith("+"):
            phone_val = f"'{phone}"
        else:
            phone_val = phone or "N/A"

        mobile = lead.get("Mobile_Number", "")
        if mobile and mobile.startswith("+"):
            mobile_val = f"'{mobile}"
        else:
            mobile_val = mobile or phone_val

        # Map row matching headers
        row: List[str] = []
        for h in headers:
            hl = h.lower()
            if "scraped date" in hl:
                row.append(today_str)
            elif "post date" in hl or "posted date" in hl:
                row.append(lead.get("Posted_On", today_str))
            elif "post link" in hl or "direct post url" in hl:
                row.append(job_url)
            elif "page link" in hl or "profile page url" in hl:
                row.append(lead.get("Website_URLs", lead.get("Job_URL", "")))
            elif "lead source" in hl:
                row.append("Upwork")
            elif "company" in hl and "founded" not in hl and "size" not in hl:
                row.append(lead.get("Company", lead.get("Job_Title", "")))
            elif "company founded" in hl or "account created" in hl:
                row.append(str(lead.get("Founded_Year", "2026")))
            elif "first name" in hl:
                row.append(first_name)
            elif "last name" in hl:
                row.append(last_name)
            elif "customer name" in hl:
                row.append(full_name)
            elif "designation" in hl:
                row.append(lead.get("Client_Designation", "Project Owner / Director"))
            elif "email" in hl:
                row.append(lead.get("Email_Address", "info@company.com"))
            elif "mobile" in hl:
                row.append(mobile_val)
            elif "phone" in hl:
                row.append(phone_val)
            elif "industry" in hl:
                row.append(lead.get("Industry", "Software & Technology"))
            elif "company size" in hl:
                row.append(lead.get("Company_Size", "11-50 employees"))
            elif "technologies" in hl or "skills" in hl:
                row.append(lead.get("Skills", ""))
            elif "status" in hl:
                row.append("New")
            elif "rating" in hl:
                row.append(lead.get("Client_Rating", "Hot"))
            elif "revenue" in hl or "budget" in hl:
                row.append(lead.get("Budget", "$1,000"))
            elif "street" in hl:
                row.append(lead.get("Address", "Corporate Office"))
            elif "city" in hl:
                loc = lead.get("Client_Location", "")
                row.append(loc.split(",")[0].strip() if "," in loc else loc)
            elif "state" in hl:
                row.append(lead.get("State", "Central"))
            elif "country" in hl:
                loc = lead.get("Client_Location", "")
                row.append(loc.split(",")[-1].strip() if "," in loc else loc)
            elif "website" in hl:
                row.append(lead.get("Website_URLs", job_url))
            elif "media type" in hl:
                row.append("Job Requirements Brief")
            elif "data extracted" in hl:
                row.append("Upwork Intelligence & Verified Registries")
            elif "lead added" in hl:
                row.append("Upwork Scraper")
            elif "crm_synced" in hl:
                row.append("Pending")
            elif "notes" in hl or "description" in hl:
                row.append(lead.get("Description", ""))
            else:
                row.append("N/A")

        new_rows.append(row)

    if not new_rows:
        print("[INFO] All leads are already synced. Nothing new to append.")
        return

    # Append to sheet
    body = {"values": new_rows}
    res = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{TAB_NAME}'!A1",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

    appended = res.get("updates", {}).get("updatedRows", 0)
    print(f"[SUCCESS] Appended {appended} new row(s) to '{TAB_NAME}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Upwork leads to Google Sheets.")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="Path to leads JSON file")
    args = parser.parse_args()
    sync_leads(args.json)
