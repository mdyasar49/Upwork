#!/usr/bin/env python3
"""
Data Cleaning & Sanitization utility for Upwork Leads.

Cleans up messy text, posted timestamps, durations, and validates contact numbers.
Works on both local CSV files and MongoDB collections.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import argparse
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"


def validate_au_phone(phone: str) -> Optional[str]:
    """Validates and normalizes phone numbers into E.164 (+61) format."""
    if not phone:
        return None
    phone_clean = re.sub(r"[^\d+]", "", str(phone).strip())

    if re.match(r"^\+?61[2-478]\d{8}$", phone_clean):
        if not phone_clean.startswith("+"):
            phone_clean = "+" + phone_clean
        return phone_clean

    if re.match(r"^04\d{8}$", phone_clean):
        return "+61" + phone_clean[1:]

    if re.match(r"^0[2378]\d{8}$", phone_clean):
        return "+61" + phone_clean[1:]

    if re.match(r"^610\d{8,9}$", phone_clean):
        return "+" + phone_clean[1:]

    digits = re.sub(r"\D", "", phone_clean)
    if 8 <= len(digits) <= 15:
        return phone_clean if phone_clean.startswith("+") else f"+{phone_clean}"

    return None


def clean_row_data(row: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(row)

    # 1. Clean Posted_On
    posted = cleaned.get("Posted_On") or cleaned.get("posted_on") or ""
    if isinstance(posted, str):
        p_clean = re.sub(r"^\s*Posted\s*", "", posted, flags=re.IGNORECASE).strip()
        if p_clean.lower() in {"n/a", "none"}:
            p_clean = ""
        cleaned["Posted_On"] = p_clean

    # 2. Clean Duration
    duration = cleaned.get("Duration") or cleaned.get("duration") or ""
    if isinstance(duration, str):
        d_clean = re.sub(r"^\s*Est\.?\s*time:\s*", "", duration, flags=re.IGNORECASE).strip()
        if d_clean.lower() in {"n/a", "none"}:
            d_clean = ""
        cleaned["Duration"] = d_clean

    # 3. Clean N/A strings in standard fields
    for field in ["Budget", "Hourly_Min", "Hourly_Max", "Client_Spent", "Client_Name", "Client_Location", "Contact_Number", "Email_Address"]:
        val = cleaned.get(field)
        if isinstance(val, str) and val.strip().upper() in {"N/A", "NONE", "NULL"}:
            cleaned[field] = ""
        elif val is None or (isinstance(val, float) and pd.isna(val)):
            cleaned[field] = ""

    # 4. Clean phone numbers
    raw_phone = cleaned.get("Contact_Number") or cleaned.get("contact_number") or ""
    if raw_phone:
        phones = [p.strip() for p in str(raw_phone).split(",") if p.strip()]
        valid_phones = []
        for p in phones:
            norm = validate_au_phone(p)
            if norm:
                valid_phones.append(norm)
        cleaned["Contact_Number"] = ", ".join(valid_phones)

    return cleaned


def clean_csv_file(input_csv: Path, output_csv: Optional[Path] = None) -> None:
    if not input_csv.exists():
        print(f"[!] Input CSV not found: {input_csv}")
        return

    out = output_csv or input_csv
    df = pd.read_csv(input_csv)
    print(f"[+] Cleaning CSV: {input_csv.name} ({len(df)} rows)...")

    cleaned_records = [clean_row_data(r) for r in df.to_dict(orient="records")]
    df_clean = pd.DataFrame(cleaned_records)
    df_clean.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[✓] Successfully cleaned and saved to: {out.name}")


def clean_mongodb(mongo_uri: Optional[str] = None, db_name: str = "upwork_db", col_name: str = "jobs") -> None:
    try:
        import pymongo
        uri = mongo_uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
        client = pymongo.MongoClient(uri)
        db = client[db_name]
        collection = db[col_name]
        
        jobs = collection.find({})
        count = 0
        for job in jobs:
            cleaned = clean_row_data(job)
            update_data = {k: v for k, v in cleaned.items() if k != "_id"}
            collection.update_one({"_id": job["_id"]}, {"$set": update_data})
            count += 1
            
        print(f"[✓] Cleaned {count} MongoDB documents in {db_name}.{col_name}.")
    except Exception as e:
        print(f"[!] MongoDB clean error: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean Upwork Leads Data")
    parser.add_argument("--csv", type=Path, default=OUTPUT_DIR / "upwork_job_leads.csv", help="CSV path to clean")
    parser.add_argument("--mongo", action="store_true", help="Clean MongoDB records")
    args = parser.parse_args()

    if args.csv.exists():
        clean_csv_file(args.csv)
    if args.mongo:
        clean_mongodb()


if __name__ == "__main__":
    main()
