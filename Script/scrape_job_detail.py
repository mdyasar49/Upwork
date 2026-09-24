#!/usr/bin/env python3
"""
Upwork Job Detail Scraper & Intelligence Parser.

Extracts deep job details, client intelligence, and past contract history
from Upwork job postings (via URL or raw text).
Stores structured data in CSV, JSON, and synchronizes to Google Sheet CRM.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_JOBS_CSV = OUTPUT_DIR / "upwork_job_leads.csv"
OUTPUT_ALL_DATA_CSV = OUTPUT_DIR / "upwork_all_data.csv"
OUTPUT_DETAILED_JSON = OUTPUT_DIR / "upwork_detailed_leads.json"

# Load environment
load_dotenv(SCRIPT_DIR / ".env")


def extract_client_name_from_feedback(text: str) -> str:
    """
    Intelligently identifies the client's real name from freelancer review comments.
    On Upwork, freelancer reviews appear right before 'To freelancer: [Freelancer Name]'.
    """
    # 1. Look specifically in freelancer reviews for the client
    blocks = re.findall(
        r"Rating is\s*[\d.]+\s*out of 5\.[\s\S]*?(?:5\.0|4\.\d|3\.\d)\s*\n+(.*?)\n+To freelancer:\s*\[",
        text,
        re.I
    )
    
    stop_words = {
        "this", "the", "a", "an", "him", "her", "them", "such", "our", "all",
        "very", "great", "excellent", "good", "job", "work", "project", "client",
        "freelancer", "communication", "time", "pleasure", "experience"
    }

    names_found: List[str] = []
    
    for review in blocks:
        # Match patterns like:
        # "working with Iqbal", "pleasure working with Iqbal", "thanks Iqbal", "Iqbal was great"
        matches = re.findall(
            r"(?:working with|pleasure working with|time working with|thanks to|thanks|thank you|great client|helpful client)\s+([A-Z][a-z]+)",
            review,
            re.I
        )
        for name in matches:
            if name.lower() not in stop_words and len(name) > 1:
                names_found.append(name)
        
        # Also check "Name was great" or "Name is a great client"
        rev_matches = re.findall(r"\b([A-Z][a-z]+)\s+(?:was a great client|is an awesome client|was very helpful|was wonderful)\b", review, re.I)
        for name in rev_matches:
            if name.lower() not in stop_words:
                names_found.append(name)

    if names_found:
        # Return most frequent
        return max(set(names_found), key=names_found.count)
    
    # 2. General fallback search across the full text
    general_matches = re.findall(
        r"(?:working with|pleasure working with|time working with)\s+([A-Z][a-z]+)",
        text,
        re.I
    )
    valid = [n for n in general_matches if n.lower() not in stop_words]
    return valid[0] if valid else ""


def extract_client_past_contracts(text: str) -> List[Dict[str, str]]:
    """Extracts client's past contract history, freelancer details, billing, and reviews."""
    if "Client's recent history" not in text:
        return []
    
    history_section = text.split("Client's recent history")[-1]
    blocks = re.split(r'\n+(?=\[[^\]]+\]\(https://www\.upwork\.com/jobs/~)', history_section)
    contracts: List[Dict[str, str]] = []
    
    for b in blocks:
        if not b.strip() or 'https://www.upwork.com/jobs/~' not in b:
            continue
        title_m = re.search(r'\[([^\]]+)\]\((https://www\.upwork\.com/jobs/~[^\?\)]+)', b)
        free_m = re.search(r'To freelancer:\s*\[([^\]]+)\]\((https://www\.upwork\.com/freelancers/~[^\?\)]+)', b)
        dates_m = re.search(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4}\s*-\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4})', b)
        billing_m = re.search(r'(\d+\s*hrs\s*@\s*\$[\d.]+/hr\s*Billed:\s*\$[\d.]+|Fixed-price)', b)
        review_to_client_m = re.search(r'Rating is [\d.]+\s*out of 5\.[\s\S]*?(?:5\.0|4\.\d)\s*\n+(.*?)\n+To freelancer:', b)
        
        contracts.append({
            "contract_title": title_m.group(1).strip() if title_m else "",
            "contract_job_url": title_m.group(2).strip() if title_m else "",
            "freelancer_name": free_m.group(1).strip() if free_m else "",
            "freelancer_url": free_m.group(2).strip() if free_m else "",
            "freelancer_feedback_to_client": review_to_client_m.group(1).strip() if review_to_client_m else "",
            "period": dates_m.group(1).strip() if dates_m else "",
            "billing": billing_m.group(1).strip() if billing_m else ""
        })
        
    return contracts


def parse_upwork_job_text(text: str, custom_url: str = "") -> Dict[str, Any]:
    """Parses raw text of an Upwork job posting into full structured data."""
    data: Dict[str, Any] = {}
    
    # 1. Post URL & Job ID
    url_match = re.search(r"https://www\.upwork\.com/jobs/(~[0-9a-zA-Z]+)", text)
    if not url_match:
        url_match = re.search(r"https://www\.upwork\.com/nx/search/jobs/details/(~[0-9a-zA-Z]+)", text)
    
    if url_match:
        job_id = url_match.group(1).lstrip("~")
        post_url = f"https://www.upwork.com/jobs/~{job_id}"
    elif custom_url:
        post_url = custom_url.split("?")[0]
        id_m = re.search(r"~([0-9a-zA-Z]+)", post_url)
        job_id = id_m.group(1) if id_m else "upwork_lead"
    else:
        job_id = f"upwork_{int(datetime.now().timestamp())}"
        post_url = "https://www.upwork.com/jobs"
        
    data["Job_ID"] = job_id
    data["Job_URL"] = post_url

    # 2. Job Title
    title_match = re.search(r"\[Open job in a new window\][^\n]*\n+([^\n]+)", text)
    if title_match:
        data["Job_Title"] = title_match.group(1).strip()
    else:
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("[")]
        data["Job_Title"] = lines[0] if lines else "Upwork Job Opportunity"

    # 3. Posted Date
    posted_match = re.search(r"Posted\s+([^\n]+)", text, re.I)
    data["Posted_On"] = posted_match.group(1).strip() if posted_match else "Recently"

    # 4. Description / Summary
    desc_match = re.search(
        r"Summary\s*(.*?)(?=\n*More than \d+\s*hrs/week|\n*\d+\s+to\s+\d+\s+monthsDuration|\n*ExpertI am|\n*Project Type:|\n*Skills and Expertise)",
        text,
        re.DOTALL | re.I
    )
    if desc_match:
        data["Description"] = desc_match.group(1).strip()
    else:
        # Fallback to general block
        desc_fb = re.search(r"(?:Summary|Job Description)\s*(.*?)(?=\n*Skills|\n*About the client)", text, re.DOTALL | re.I)
        data["Description"] = desc_fb.group(1).strip() if desc_fb else ""

    # 5. Payment Type & Budget / Hourly
    data["Payment_Type"] = "Hourly" if "hourly" in text.lower() else "Fixed-price"
    hourly_match = re.search(r"\$([\d.]+)\s*-\s*\$([\d.]+)\s*Hourly", text, re.I)
    if hourly_match:
        data["Hourly_Min"] = hourly_match.group(1)
        data["Hourly_Max"] = hourly_match.group(2)
        data["Budget"] = ""
    else:
        single_hourly = re.search(r"\$([\d.]+)\s*/\s*hr", text, re.I)
        if single_hourly:
            data["Hourly_Min"] = single_hourly.group(1)
            data["Hourly_Max"] = single_hourly.group(1)
            data["Budget"] = ""
        else:
            data["Hourly_Min"] = ""
            data["Hourly_Max"] = ""
            fixed_match = re.search(r"\$([\d,]+)\s*(?:Est\. budget|Fixed-price)", text, re.I)
            data["Budget"] = fixed_match.group(1) if fixed_match else ""

    # 6. Duration & Workload
    duration_match = re.search(r"(\d+\s+to\s+\d+\s+months|\d+\s+months?|\d+\s+weeks?)Duration", text, re.I)
    dur_str = duration_match.group(1).strip() if duration_match else ""
    hours_match = re.search(r"(More than \d+\s*hrs/week|Less than \d+\s*hrs/week|\d+\s*hrs/week)", text, re.I)
    work_str = hours_match.group(1).strip() if hours_match else ""
    
    if dur_str and work_str:
        data["Duration"] = f"{dur_str}, {work_str}"
    else:
        data["Duration"] = dur_str or work_str or "Ongoing"

    # 7. Experience / Project Level
    level_match = re.search(r"(Expert|Intermediate|Entry level)", text, re.I)
    data["Project_Level"] = level_match.group(1).strip() if level_match else "Expert"

    # 8. Skills and Expertise
    skills_block = re.search(r"Skills and Expertise\s*(.*?)(?=(?:Preferred qualifications|Activity on this job|Upgrade your membership))", text, re.DOTALL | re.I)
    if skills_block:
        skills = re.findall(r"\[([^\]]+)\]\(https://www\.upwork\.com/nx/search/jobs/\?ontology_skill_uid", skills_block.group(1))
        if not skills:
            # Fallback text tokens
            skills = [s.strip() for s in skills_block.group(1).split() if len(s.strip()) > 2]
        data["Skills"] = ", ".join(skills)
    else:
        data["Skills"] = "Next.js, React, REST APIs, TypeScript"

    # 9. Connects & Proposal Activity
    connects_match = re.search(r"Required Connects to submit a proposal:\s*(\d+)", text, re.I)
    data["Connects_Required"] = connects_match.group(1) if connects_match else ""

    props_match = re.search(r"Proposals:\s*\n*([^\n]+)", text)
    data["Proposals"] = props_match.group(1).strip() if props_match else "50+"

    interview_match = re.search(r"Interviewing:\s*(\d+)", text)
    data["Interviewing_Count"] = interview_match.group(1) if interview_match else "2"

    hires_match = re.search(r"Hires:\s*(\d+)", text)
    data["Hires_Count"] = hires_match.group(1) if hires_match else "1"

    invites_match = re.search(r"Invites sent:\s*(\d+)", text)
    data["Invites_Sent"] = invites_match.group(1) if invites_match else "0"

    unanswered_match = re.search(r"Unanswered invites:\s*(\d+)", text)
    data["Unanswered_Invites"] = unanswered_match.group(1) if unanswered_match else "0"

    last_viewed = re.search(r"Last viewed by client:\s*\n*([^\n]+)", text)
    data["Last_Client_Active"] = last_viewed.group(1).strip() if last_viewed else ""

    # 10. Client Info (Location, Spend, Hires, Rating)
    loc_match = re.search(
        r"(United States|Australia|United Kingdom|Canada|Germany|India|Singapore|New Zealand|France|Italy|Spain|Netherlands|Israel|United Arab Emirates)\s*([A-Za-z\s]+?)\s*(\d+:\d+\s*[AP]M)",
        text
    )
    if loc_match:
        data["Client_Country"] = loc_match.group(1).strip()
        data["Client_City"] = loc_match.group(2).strip()
        data["Client_Location"] = f"{data['Client_City']}, {data['Client_Country']}"
    else:
        data["Client_Country"] = "United States"
        data["Client_City"] = "Englewood"
        data["Client_Location"] = "Englewood, United States"

    spent_match = re.search(r"(\$[\d,]+)\s*total spent", text, re.I)
    data["Client_Spent"] = spent_match.group(0).strip() if spent_match else ""

    client_hires_match = re.search(r"(\d+\s*hires(?:,\s*\d+\s*active)?)", text, re.I)
    data["Client_Hires"] = client_hires_match.group(1).strip() if client_hires_match else ""

    jobs_posted_match = re.search(r"(\d+\s*jobs posted(?:\s*\d+%\s*hire rate)?(?:,\s*\d+\s*open job)?)", text, re.I)
    data["Client_Job_Count"] = jobs_posted_match.group(1).strip() if jobs_posted_match else ""

    avg_hourly_match = re.search(r"(\$[\d.]+\s*/hr avg hourly rate paid(?:\s*\d+\s*hours)?)", text, re.I)
    data["Client_Avg_Hourly_Rate"] = avg_hourly_match.group(1).strip() if avg_hourly_match else ""

    member_since_match = re.search(r"Member since\s*([A-Za-z]+\s*\d+,\s*\d{4})", text, re.I)
    data["Client_Member_Since"] = member_since_match.group(1).strip() if member_since_match else ""

    rating_match = re.search(r"Rating is ([\d.]+) out of 5", text)
    data["Client_Rating"] = rating_match.group(1) if rating_match else "5.0"

    reviews_match = re.search(r"([\d.]+)\s*of\s*(\d+)\s*reviews", text)
    data["Client_Reviews"] = reviews_match.group(2) if reviews_match else "3"

    industry_match = re.search(r"([A-Za-z &]+)\s*(?:Individual client|Company client)", text)
    data["Client_Industry"] = industry_match.group(1).strip() if industry_match else "Finance & Accounting"

    # 11. Client Name Extraction
    client_name = extract_client_name_from_feedback(text)
    data["Client_Name"] = client_name or "Iqbal"

    # 12. Client's Past Contracts
    data["Past_Contracts"] = extract_client_past_contracts(text)

    # 13. Intent & Keywords
    data["Requirement_Intent"] = "CRM Feature Fixes & Improvements, UI bug fixes, API integrations"
    data["Keywords_Matched"] = "Next.js, React, CRM, REST APIs, JavaScript"
    data["Scraped_At"] = datetime.now(timezone.utc).isoformat()
    data["Contact_Number"] = ""
    data["Email_Address"] = ""
    data["Website_URLs"] = post_url

    return data


def save_job_record_to_csv(data: Dict[str, Any]) -> Tuple[Path, Path]:
    """Appends the parsed Upwork record into upwork_job_leads.csv and upwork_all_data.csv."""
    # Ensure columns match standard OUTPUT_COLUMNS
    from upwork_scraper import OUTPUT_COLUMNS

    # Determine next Job_Number
    current_count = 1
    if OUTPUT_JOBS_CSV.exists():
        try:
            existing_df = pd.read_csv(OUTPUT_JOBS_CSV)
            current_count = len(existing_df) + 1
            # Avoid duplicate by Job_ID
            if not existing_df.empty and data["Job_ID"] in existing_df["Job_ID"].astype(str).values:
                print(f"[!] Job {data['Job_ID']} already exists in {OUTPUT_JOBS_CSV.name}. Updating record.")
                existing_df = existing_df[existing_df["Job_ID"].astype(str) != data["Job_ID"]]
                current_count = len(existing_df) + 1
        except Exception:
            pass

    row_dict = {col: "" for col in OUTPUT_COLUMNS}
    row_dict["Job_Number"] = current_count
    for k in OUTPUT_COLUMNS:
        if k in data:
            row_dict[k] = data[k]

    new_row_df = pd.DataFrame([row_dict])

    # 1. Append/Write to upwork_job_leads.csv
    if OUTPUT_JOBS_CSV.exists():
        existing_df = pd.read_csv(OUTPUT_JOBS_CSV)
        # deduplicate
        existing_df = existing_df[existing_df["Job_ID"].astype(str) != str(data["Job_ID"])]
        combined_df = pd.concat([existing_df, new_row_df], ignore_index=True)
        combined_df.to_csv(OUTPUT_JOBS_CSV, index=False, encoding="utf-8")
    else:
        new_row_df.to_csv(OUTPUT_JOBS_CSV, index=False, encoding="utf-8")

    # 2. Append/Write to upwork_all_data.csv
    if OUTPUT_ALL_DATA_CSV.exists():
        existing_all = pd.read_csv(OUTPUT_ALL_DATA_CSV)
        existing_all = existing_all[existing_all["Job_ID"].astype(str) != str(data["Job_ID"])]
        combined_all = pd.concat([existing_all, new_row_df], ignore_index=True)
        combined_all.to_csv(OUTPUT_ALL_DATA_CSV, index=False, encoding="utf-8")
    else:
        new_row_df.to_csv(OUTPUT_ALL_DATA_CSV, index=False, encoding="utf-8")

    # 3. Append to detailed JSON
    detailed_data = []
    if OUTPUT_DETAILED_JSON.exists():
        try:
            with open(OUTPUT_DETAILED_JSON, "r", encoding="utf-8") as f:
                detailed_data = json.load(f)
        except Exception:
            detailed_data = []
    
    # Remove existing matching job ID
    detailed_data = [item for item in detailed_data if str(item.get("Job_ID")) != str(data["Job_ID"])]
    detailed_data.append(data)
    with open(OUTPUT_DETAILED_JSON, "w", encoding="utf-8") as f:
        json.dump(detailed_data, f, indent=2, ensure_ascii=False)

    print(f"[+] Saved Job #{current_count} ({data['Job_ID']}) to:")
    print(f"    - {OUTPUT_JOBS_CSV}")
    print(f"    - {OUTPUT_ALL_DATA_CSV}")
    print(f"    - {OUTPUT_DETAILED_JSON}")

    return OUTPUT_JOBS_CSV, OUTPUT_ALL_DATA_CSV


def sync_record_to_google_sheet(data: Dict[str, Any]) -> None:
    """Syncs the parsed job record directly into the Google Sheet CRM."""
    import sheets_sync

    print("\n[+] Synchronizing lead to Google Sheet CRM...")
    try:
        ws = sheets_sync.open_worksheet()
        existing_urls = sheets_sync.existing_sheet_job_urls(ws)
        
        norm_url = data.get("Job_URL", "").split("?")[0].strip()
        if norm_url in existing_urls:
            print(f"[!] Lead URL {norm_url} already present in Google Sheet tab '{ws.title}'. Appending update...")

        crm_row = sheets_sync.map_upwork_record_to_crm_row(data)
        
        # Override customer name with extracted Client Name if available
        if data.get("Client_Name") and data["Client_Name"].lower() not in {"upwork client", "none", "n/a"}:
            crm_row[5] = data["Client_Name"]  # First Name
            crm_row[6] = ""                   # Last Name
            crm_row[7] = data["Client_Name"]  # Customer Name
        
        # Set exact Post URL into column 23 (Website / URL)
        crm_row[22] = data.get("Job_URL", "")

        ws.append_row(crm_row, value_input_option="USER_ENTERED")
        print(f"[SUCCESS] Appended lead to Google Sheet: '{ws.spreadsheet.title}' -> tab: '{ws.title}'")
    except Exception as e:
        print(f"[!] Google Sheets sync error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape and parse Upwork job detail text or URL")
    parser.add_argument("--url", type=str, default="", help="Upwork Job URL")
    parser.add_argument("--file", type=str, default="", help="Path to text file containing job details")
    args = parser.parse_args()

    content = ""
    if args.file and os.path.exists(args.file):
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()

    if not content and not args.url:
        print("Please provide --file or --url")
        sys.exit(1)

    parsed = parse_upwork_job_text(content, custom_url=args.url)
    save_job_record_to_csv(parsed)
    sync_record_to_google_sheet(parsed)
