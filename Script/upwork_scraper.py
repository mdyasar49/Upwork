#!/usr/bin/env python3
"""
Upwork Job Leads & Opportunities Scraper.

Extracts job listings, client contact details, budgets, skills, and project requirements
from Upwork search results and job detail pages.
Outputs are written under the project Output/ folder, Google Sheets, and/or MongoDB.
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Paths / Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")
PROJECT_DIR = SCRIPT_DIR.parent
INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = PROJECT_DIR / "Output"
LOG_DIR = PROJECT_DIR / "logs"

KEYWORDS_CSV = INPUT_DIR / "upwork_keywords.csv"
SEARCH_URLS_CSV = INPUT_DIR / "upwork_search_urls.csv"
FILTER_DETAILS_TXT = INPUT_DIR / "upwork_filter_details.txt"

OUTPUT_JOBS_CSV = OUTPUT_DIR / "upwork_job_leads.csv"
OUTPUT_ALL_DATA_CSV = OUTPUT_DIR / "upwork_all_data.csv"

# Comprehensive Output Columns
OUTPUT_COLUMNS = [
    "Job_Number",
    "Job_ID",
    "Job_Title",
    "Job_URL",
    "Posted_On",
    "Payment_Type",
    "Budget",
    "Hourly_Min",
    "Hourly_Max",
    "Project_Level",
    "Duration",
    "Skills",
    "Client_Name",
    "Client_Location",
    "Client_Spent",
    "Client_Hires",
    "Client_Rating",
    "Client_Reviews",
    "Client_Job_Count",
    "Client_Member_Since",
    "Proposals",
    "Last_Client_Active",
    "Interviewing_Count",
    "Invites_Sent",
    "Unanswered_Invites",
    "Contact_Number",
    "Email_Address",
    "Website_URLs",
    "Requirement_Intent",
    "Keywords_Matched",
    "Description",
    "Scraped_At",
]

DEFAULT_LOCATIONS = [
    loc.strip() for loc in os.environ.get("DEFAULT_LOCATIONS", "Australia,India").split(",") if loc.strip()
]

INTENT_KEYWORDS = [
    "looking", "seeking", "need someone", "i need", "require",
    "develop", "implementation", "build", "we need", "upgrade"
]

# ---------------------------------------------------------------------------
# Helpers & Sanitizers
# ---------------------------------------------------------------------------

def ensure_dirs() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_job_url(raw_url: str) -> str:
    if not raw_url or raw_url.strip() in {"", "N/A", "None"}:
        return "N/A"
    raw_url = raw_url.strip()
    if raw_url.startswith("/"):
        raw_url = "https://www.upwork.com" + raw_url
    elif not raw_url.startswith("http"):
        raw_url = "https://www.upwork.com/" + raw_url.lstrip("/")
    
    clean_url = re.sub(r"(\~[a-zA-Z0-9]+)[^/]*.*", r"\1", raw_url)
    clean_url = clean_url.split("?")[0]
    return clean_url


def extract_job_id(url: str, raw_id: str | None = None) -> str:
    if raw_id and str(raw_id).strip() not in {"", "None", "N/A"}:
        return str(raw_id).strip()
    if url and url != "N/A":
        m = re.search(r"~(\d+)", url)
        if m:
            return m.group(1)
        m2 = re.search(r"~([a-zA-Z0-9]+)", url)
        if m2:
            return m2.group(1)
        parts = url.rstrip("/").split("-")
        if parts and parts[-1].isdigit():
            return parts[-1]
    return url if url else "N/A"


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def validate_au_or_intl_phone(phone: str) -> Optional[str]:
    if not phone:
        return None
    phone_clean = re.sub(r"[^\d+]", "", str(phone).strip())
    
    # Australian landline / mobile
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
    
    # Indian mobile format (+91 XXXXXXXXXX)
    if re.match(r"^\+?91[6-9]\d{9}$", phone_clean):
        return phone_clean if phone_clean.startswith("+") else f"+{phone_clean}"
    if re.match(r"^[6-9]\d{9}$", phone_clean):
        return f"+91{phone_clean}"

    # General international valid format (8 to 15 digits)
    digits = re.sub(r"\D", "", phone_clean)
    if 8 <= len(digits) <= 15:
        return phone_clean if phone_clean.startswith("+") else f"+{phone_clean}"
    return None


def extract_contacts_from_text(text: str) -> Tuple[str, str, str, str]:
    """Extracts (email, phone, websites, requirement_intent) from text descriptions."""
    if not text:
        return "", "", "", ""
    
    # 1. Emails
    email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    emails = set(email_pattern.findall(text))
    valid_emails = [
        e for e in emails 
        if not any(junk in e.lower() for junk in ["upwork.com", "example.com", "placeholder", "w3.org"])
    ]
    email_str = ", ".join(valid_emails)
    
    # 2. Phone Numbers
    phone_pattern = re.compile(r"(\+?\d[\d\s\-().]{7,}\d)")
    raw_phones = phone_pattern.findall(text)
    valid_phones = set()
    for p in raw_phones:
        cleaned = validate_au_or_intl_phone(p)
        if cleaned:
            valid_phones.add(cleaned)
    phone_str = ", ".join(valid_phones)
    
    # 3. Websites & URLs
    url_pattern = re.compile(
        r"(https?://[^\s\"'>)]+|www\.[^\s\"'>)]+|[a-zA-Z0-9.-]+\.(?:com|org|net|io|ai|co|in|edu|gov|au|dev|app)\b[^\s\"'>)]*)",
        re.I
    )
    raw_urls = url_pattern.findall(text)
    valid_urls = set()
    for u in raw_urls:
        u_str = u.strip().rstrip(".,;)")
        if not any(skip in u_str.lower() for skip in ["upwork.com", "google.com", "schema.org", "w3.org"]):
            valid_urls.add(u_str)
    url_str = ", ".join(valid_urls)
    
    # 4. Intent extraction
    words = text.split()
    intents = []
    for i, w in enumerate(words):
        if w.lower() in INTENT_KEYWORDS and i + 2 < len(words):
            intents.append(f"{w} {words[i+1]} {words[i+2]}")
    intent_str = "; ".join(set(intents[:3]))
    
    return email_str, phone_str, url_str, intent_str


def match_keywords(text: str, keywords_list: List[str]) -> str:
    if not text:
        return ""
    text_lower = text.lower()
    found = []
    for kw in keywords_list:
        if kw.lower() in text_lower:
            found.append(kw)
    return ", ".join(list(dict.fromkeys(found)))

# ---------------------------------------------------------------------------
# WebDriver Setup
# ---------------------------------------------------------------------------

def init_driver(headless: bool = False) -> Any:
    """Initializes undetected_chromedriver to bypass Cloudflare anti-bot checks seamlessly."""
    try:
        import undetected_chromedriver as uc
        opts = uc.ChromeOptions()
        
        # In undetected_chromedriver, standard --headless triggers Cloudflare bot challenges.
        # Running off-screen or compact window bypasses Cloudflare 100% reliably.
        if headless:
            opts.add_argument("--window-position=-32000,-32000")
            opts.add_argument("--window-size=1600,1000")
        else:
            opts.add_argument("--window-position=0,0")
            opts.add_argument("--window-size=1600,1000")
            
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-popup-blocking")
        
        proxy_server = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        if proxy_server:
            opts.add_argument(f"--proxy-server={proxy_server}")

        driver = uc.Chrome(options=opts, version_main=153)
        driver.set_page_load_timeout(45)
        return driver
    except Exception as e:
        print(f"[!] Warning initializing undetected_chromedriver: {e}. Falling back to standard Chrome...")
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
        except Exception:
            driver = webdriver.Chrome(options=opts)
            
        driver.set_page_load_timeout(45)
        return driver

def safe_quit_driver(driver: Any) -> None:
    """Closes and quits driver gracefully ignoring winerror handle exceptions."""
    if not driver:
        return
    try:
        driver.close()
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Upwork Parser Engine
# ---------------------------------------------------------------------------

def parse_job_tile(tile_soup: BeautifulSoup, keywords_list: List[str]) -> Optional[Dict[str, Any]]:
    try:
        # Title & URL
        title_elem = (
            tile_soup.find("h2", class_=lambda c: c and "job-tile-title" in c)
            or tile_soup.find("h2")
            or tile_soup.find("a", href=lambda h: h and "/jobs/" in h)
        )
        title = clean_text(title_elem.get_text()) if title_elem else ""
        if not title or title.lower() in {"n/a", "none"}:
            return None

        link_elem = (
            tile_soup.find("a", href=lambda h: h and ("/jobs/" in h or "~" in h))
            or tile_soup.find("a", href=True)
        )
        raw_href = link_elem["href"] if link_elem else ""
        job_url = normalize_job_url(raw_href)
        
        job_id = (
            tile_soup.get("data-test-job-tile-id")
            or tile_soup.get("data-job-id")
            or extract_job_id(job_url)
        )

        # Posted Date
        posted_elem = (
            tile_soup.find("small", {"data-test": "job-published-date"})
            or tile_soup.find("small", class_=lambda c: c and "text-light" in c)
            or tile_soup.find("span", {"data-test": "posted-on"})
            or tile_soup.find("span", class_=lambda c: c and "posted" in c)
        )
        posted_on = clean_text(posted_elem.get_text()) if posted_elem else ""
        posted_on = re.sub(r"^\s*Posted\s*", "", posted_on, flags=re.I).strip()

        # Description
        desc_elem = (
            tile_soup.find("p", class_=lambda c: c and ("text-body-sm" in c or "job-description" in c))
            or tile_soup.find("span", {"data-test": "job-description-text"})
            or tile_soup.find("div", class_=lambda c: c and "description" in c)
        )
        description = clean_text(desc_elem.get_text()) if desc_elem else ""

        # Payment details & Budget / Hourly
        tile_full_text = tile_soup.get_text(separator=" ")
        payment_elem = tile_soup.find("li", {"data-test": "job-type-label"}) or tile_soup.find("strong", {"data-test": "job-type"})
        payment_type = clean_text(payment_elem.get_text()) if payment_elem else ""

        budget = ""
        hourly_min = ""
        hourly_max = ""
        project_level = ""
        
        if "Hourly" in payment_type or "Hourly" in tile_full_text:
            matches = re.findall(r"\$([\d,.]+)", payment_type or tile_full_text)
            if len(matches) >= 2:
                hourly_min, hourly_max = matches[0].replace(",", ""), matches[1].replace(",", "")
                payment_type = "Hourly"
            elif len(matches) == 1:
                hourly_min = hourly_max = matches[0].replace(",", "")
                payment_type = "Hourly"
        if "Fixed" in payment_type or "$" in payment_type or "Est. budget" in tile_full_text:
            budget_elem = tile_soup.find("span", attrs={"data-test": "budget"}) or tile_soup.find("strong", attrs={"data-test": "budget"})
            if budget_elem:
                budget = re.sub(r"[^\d.]", "", budget_elem.get_text().strip())
                payment_type = "Fixed-price"
            else:
                matches = re.findall(r"\$([\d,.]+)", payment_type or tile_full_text)
                if matches:
                    budget = matches[0].replace(",", "")
                    payment_type = "Fixed-price"

        # Project level
        level_elem = tile_soup.find("li", {"data-test": "contractor-tier"}) or tile_soup.find("span", {"data-test": "tier-label"})
        if level_elem:
            project_level = clean_text(level_elem.get_text())

        # Duration
        duration_elem = tile_soup.find("span", attrs={"data-test": "duration"}) or tile_soup.find("li", attrs={"data-test": "duration-label"})
        duration = clean_text(duration_elem.get_text()) if duration_elem else ""
        duration = re.sub(r"^\s*Est\.\s*time:\s*", "", duration, flags=re.I).strip()

        # Client Info
        client_spent = ""
        client_location = ""
        client_name = ""
        client_rating = ""
        client_reviews = ""

        client_info_list = tile_soup.find("ul", {"data-test": "JobInfoClient"}) or tile_soup.find("div", class_=lambda c: c and "client-info" in c)
        if client_info_list:
            spent_el = client_info_list.find("li", {"data-test": "total-spent"}) or client_info_list.find("span", string=lambda s: s and "spent" in str(s).lower())
            if spent_el:
                client_spent = clean_text(spent_el.get_text()).replace("spent", "").strip()

            loc_el = client_info_list.find("li", {"data-test": "location"}) or client_info_list.find("span", {"data-test": "client-country"})
            if loc_el:
                client_location = clean_text(loc_el.get_text())
                client_location = re.sub(r"^\s*Location\s*", "", client_location, flags=re.I).strip()

            rating_el = client_info_list.find("span", class_=lambda c: c and "air3-rating" in c) or client_info_list.find("span", attrs={"aria-label": lambda a: a and "Rating is" in a})
            if rating_el:
                client_rating = clean_text(rating_el.get_text())

        client_name_el = tile_soup.find("strong", {"data-test": "client-name"})
        if client_name_el:
            client_name = clean_text(client_name_el.get_text())

        # Skills
        skills = []
        skills_container = tile_soup.find("div", class_=lambda c: c and ("air3-token-container" in c or "skills" in c)) or tile_soup
        for btn in skills_container.find_all(["button", "a", "span"], attrs={"data-test": ["token", "skill"]}):
            sk = clean_text(btn.get_text())
            if sk and len(sk) < 50 and sk not in skills:
                skills.append(sk)
        skills_str = ", ".join(skills)

        # Proposals
        proposals_el = tile_soup.find("li", {"data-test": "proposals-tier"}) or tile_soup.find("strong", {"data-test": "proposals"})
        proposals = clean_text(proposals_el.get_text()).replace("Proposals:", "").strip() if proposals_el else ""

        # Contacts, Intent & URLs extraction
        combined_text = f"{title} {description}"
        email_str, phone_str, website_urls, intent_str = extract_contacts_from_text(combined_text)
        keywords_matched = match_keywords(combined_text, keywords_list)

        return {
            "Job_Number": 0,
            "Job_ID": job_id,
            "Job_Title": title,
            "Job_URL": job_url,
            "Posted_On": posted_on,
            "Payment_Type": payment_type,
            "Budget": budget,
            "Hourly_Min": hourly_min,
            "Hourly_Max": hourly_max,
            "Project_Level": project_level,
            "Duration": duration,
            "Skills": skills_str,
            "Client_Name": client_name,
            "Client_Location": client_location,
            "Client_Spent": client_spent,
            "Client_Hires": "",
            "Client_Rating": client_rating,
            "Client_Reviews": client_reviews,
            "Client_Job_Count": "",
            "Client_Member_Since": "",
            "Proposals": proposals,
            "Last_Client_Active": "",
            "Interviewing_Count": "",
            "Invites_Sent": "",
            "Unanswered_Invites": "",
            "Contact_Number": phone_str,
            "Email_Address": email_str,
            "Website_URLs": website_urls,
            "Requirement_Intent": intent_str,
            "Keywords_Matched": keywords_matched,
            "Description": description,
            "Scraped_At": now_utc_iso(),
        }
    except Exception as exc:
        print(f"  [!] Error parsing tile: {exc}")
        return None


def scrape_job_details_page(driver: webdriver.Chrome, job_url: str, keywords_list: List[str]) -> Dict[str, Any]:
    """Deep scrapes an individual Upwork job page for comprehensive details and client metrics."""
    details: Dict[str, Any] = {
        "Job_URL": job_url,
        "Scraped_At": now_utc_iso(),
    }
    try:
        driver.get(job_url)
        time.sleep(random.uniform(4, 7))
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        title_elem = soup.find("header", class_=lambda c: c and "air3-card-section" in c)
        if title_elem and title_elem.find("h1"):
            details["Job_Title"] = clean_text(title_elem.find("h1").get_text())
        elif soup.find("h1"):
            details["Job_Title"] = clean_text(soup.find("h1").get_text())
            
        posted_elem = soup.find("div", {"data-test": "PostedOn"}) or soup.find("span", class_=lambda c: c and "posted-on" in c)
        if posted_elem:
            details["Posted_On"] = clean_text(posted_elem.get_text()).replace("Posted", "").strip()

        desc_elements = soup.find_all("p", class_=lambda c: c and ("text-body-sm" in c or "break" in c))
        raw_description = " ".join([clean_text(p.get_text()) for p in desc_elements if p.get_text()])
        details["Description"] = raw_description

        skills_elements = soup.find_all("section", {"data-test": "Expertise"}) or soup.find_all("div", class_=lambda c: c and "air3-token-container" in c)
        skills = []
        for sec in skills_elements:
            for tok in sec.find_all(["a", "button", "span"]):
                sk = clean_text(tok.get_text())
                if sk and len(sk) < 40 and sk not in skills:
                    skills.append(sk)
        details["Skills"] = ", ".join(skills)

        budget_amounts = soup.find_all("div", {"data-test": "BudgetAmount"}) or soup.find_all("span", class_=lambda c: c and "budget" in c)
        for amt in budget_amounts:
            txt = amt.get_text()
            nums = re.findall(r"\$([\d,.]+)", txt)
            if len(nums) >= 2:
                details["Hourly_Min"] = nums[0].replace(",", "")
                details["Hourly_Max"] = nums[1].replace(",", "")
                details["Payment_Type"] = "Hourly"
            elif len(nums) == 1:
                details["Budget"] = nums[0].replace(",", "")
                details["Payment_Type"] = "Fixed-price"

        client_sec = soup.find("section", class_=lambda c: c and "air3-card-section" in c, attrs={"data-test": "ClientInfo"}) or soup.find("div", class_=lambda c: c and "client-info" in c)
        if client_sec:
            details["Client_Location"] = clean_text(client_sec.get_text())
            spend_el = client_sec.find("li", {"data-qa": "client-spend"}) or client_sec.find("strong", string=lambda s: s and "$" in str(s))
            if spend_el:
                details["Client_Spent"] = clean_text(spend_el.get_text())
                
            hires_el = client_sec.find("li", {"data-qa": "client-hires"}) or client_sec.find("div", string=lambda s: s and "hires" in str(s).lower())
            if hires_el:
                details["Client_Hires"] = clean_text(hires_el.get_text())

            since_el = client_sec.find("li", {"data-qa": "client-contract-date"}) or client_sec.find("small", string=lambda s: s and "Member since" in str(s))
            if since_el:
                details["Client_Member_Since"] = clean_text(since_el.get_text()).replace("Member since", "").strip()

        activity_sec = soup.find("section", {"data-test": "Activity"}) or soup.find("div", class_=lambda c: c and "activity-section" in c)
        if activity_sec:
            props_match = re.search(r"Proposals:\s*([^\n\r<]+)", activity_sec.get_text())
            if props_match:
                details["Proposals"] = clean_text(props_match.group(1))
            
            interview_match = re.search(r"Interviewing:\s*(\d+)", activity_sec.get_text())
            if interview_match:
                details["Interviewing_Count"] = interview_match.group(1)

            invites_match = re.search(r"Invites sent:\s*(\d+)", activity_sec.get_text())
            if invites_match:
                details["Invites_Sent"] = invites_match.group(1)

            unanswered_match = re.search(r"Unanswered invites:\s*(\d+)", activity_sec.get_text())
            if unanswered_match:
                details["Unanswered_Invites"] = unanswered_match.group(1)

        combined_text = f"{details.get('Job_Title', '')} {details.get('Description', '')}"
        email_str, phone_str, website_urls, intent_str = extract_contacts_from_text(combined_text)
        details["Email_Address"] = email_str
        details["Contact_Number"] = phone_str
        details["Website_URLs"] = website_urls
        details["Requirement_Intent"] = intent_str
        details["Keywords_Matched"] = match_keywords(combined_text, keywords_list)

    except Exception as e:
        print(f"  [!] Error deep scraping job page {job_url}: {e}")
        
    return details

# ---------------------------------------------------------------------------
# Main Scraping Pipeline
# ---------------------------------------------------------------------------

def load_keywords(csv_path: Path = KEYWORDS_CSV) -> List[str]:
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            col = [c for c in df.columns if "keyword" in c.lower()]
            if col:
                return [str(k).strip() for k in df[col[0]].dropna().unique() if str(k).strip()]
        except Exception as e:
            print(f"[!] Warning reading keywords CSV: {e}")
    return ["AI Integration", "React.js", "Python", "Twilio", "Automation", "Django", "Web Scraping"]


def load_existing_job_urls(csv_paths: List[Path]) -> Set[str]:
    urls = set()
    for path in csv_paths:
        if path.exists() and path.stat().st_size > 0:
            try:
                df = pd.read_csv(path)
                col = [c for c in df.columns if "url" in c.lower()]
                if col:
                    for u in df[col[0]].dropna():
                        norm = normalize_job_url(str(u))
                        if norm != "N/A":
                            urls.add(norm)
            except Exception:
                pass
    return urls


def run_upwork_scraper(
    keywords: Optional[List[str]] = None,
    locations: Optional[List[str]] = None,
    limit: int = 50,
    max_pages: int = 5,
    deep_scrape: bool = False,
    headless: bool = True,
    output_csv: Path = OUTPUT_JOBS_CSV,
    save_mongo: bool = False,
) -> pd.DataFrame:
    ensure_dirs()
    driver = init_driver(headless=headless)
    
    keywords_list = keywords or load_keywords()
    target_locations = locations or DEFAULT_LOCATIONS
    existing_urls = load_existing_job_urls([output_csv, OUTPUT_ALL_DATA_CSV])
    
    print(f"[+] Loaded {len(keywords_list)} keywords across locations: {', '.join(target_locations)}.")
    print(f"[+] Found {len(existing_urls)} existing job URLs to avoid duplicates.")

    collected_records: List[Dict[str, Any]] = []
    total_valid = 0

    try:
        for loc in target_locations:
            if total_valid >= limit:
                break

            print(f"\n=======================================================")
            print(f"🌍 SEARCHING TARGET REGION: {loc.upper()}")
            print(f"=======================================================")

            for kw_idx, keyword in enumerate(keywords_list, start=1):
                if total_valid >= limit:
                    print(f"[+] Reached scrape limit of {limit} jobs.")
                    break

                print(f"\n[{kw_idx}/{len(keywords_list)}] Keyword: '{keyword}' ({loc})")

                for page in range(1, max_pages + 1):
                    if total_valid >= limit:
                        break

                    if loc and loc.lower() != "all":
                        search_url = f"https://www.upwork.com/nx/search/jobs/?location={quote(loc)}&q={quote(keyword)}&sort=recency&page={page}"
                    else:
                        search_url = f"https://www.upwork.com/nx/search/jobs/?q={quote(keyword)}&sort=recency&page={page}"

                    print(f"  --> [Page {page}] Fetching: {search_url}")
                    try:
                        driver.get(search_url)
                        time.sleep(random.uniform(4, 7))

                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
                        time.sleep(1)
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight*2/3);")
                        time.sleep(1)
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(random.uniform(1.5, 3.0))

                        soup = BeautifulSoup(driver.page_source, "html.parser")
                        job_tiles = (
                            soup.find_all("article", {"data-test": "JobTile"})
                            or soup.find_all("article")
                            or soup.find_all("section", class_=lambda c: c and "up-card-section" in c)
                        )
                        
                        if not job_tiles:
                            print(f"  [i] No job tiles found on page {page} for '{keyword}' ({loc}). Moving next.")
                            break

                        print(f"  [✓] Found {len(job_tiles)} job tiles on page {page}.")

                        for tile in job_tiles:
                            if total_valid >= limit:
                                break

                            job_data = parse_job_tile(tile, keywords_list)
                            if not job_data:
                                continue

                            job_url = job_data["Job_URL"]
                            if job_url in existing_urls:
                                continue

                            if deep_scrape and job_url != "N/A":
                                print(f"    - Deep scraping: {job_url}")
                                deep_details = scrape_job_details_page(driver, job_url, keywords_list)
                                job_data.update({k: v for k, v in deep_details.items() if v})

                            total_valid += 1
                            job_data["Job_Number"] = total_valid
                            if not job_data.get("Client_Location"):
                                job_data["Client_Location"] = loc

                            existing_urls.add(job_url)
                            collected_records.append(job_data)

                            print(f"    [+] #{total_valid} Extracted: {job_data['Job_Title'][:50]} | Budget: {job_data['Budget'] or job_data['Hourly_Min']} | Loc: {job_data['Client_Location']}")

                            df_single = pd.DataFrame([job_data])
                            for col in OUTPUT_COLUMNS:
                                if col not in df_single.columns:
                                    df_single[col] = ""
                            df_single = df_single[OUTPUT_COLUMNS]

                            write_header = not output_csv.exists() or output_csv.stat().st_size == 0
                            df_single.to_csv(output_csv, mode="a", header=write_header, index=False, encoding="utf-8-sig")

                    except Exception as page_err:
                        print(f"  [!] Error scraping page {page}: {page_err}")
                        time.sleep(3)

                    time.sleep(random.uniform(3, 6))

    finally:
        safe_quit_driver(driver)
        print("\n[+] Browser session closed.")

    df_result = pd.DataFrame(collected_records)
    print(f"\n=======================================================")
    print(f"[✓] Scraping complete! Collected {len(df_result)} new job leads.")
    print(f"[✓] Output saved to: {output_csv}")
    print(f"=======================================================")

    if save_mongo and not df_result.empty:
        try:
            import pymongo
            mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
            db_name = os.environ.get("MONGO_DB_NAME", "upwork_db")
            col_name = os.environ.get("MONGO_JOBS_COLLECTION", "jobs")
            client = pymongo.MongoClient(mongo_uri)
            db = client[db_name]
            col = db[col_name]
            records = df_result.to_dict(orient="records")
            col.insert_many(records, ordered=False)
            print(f"[✓] Inserted {len(records)} records into MongoDB ({db_name}.{col_name}).")
        except Exception as me:
            print(f"[!] MongoDB sync notice: {me}")

    return df_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upwork Job Leads Scraper")
    parser.add_argument("--keyword", type=str, default=None, help="Specific search keyword")
    parser.add_argument("--locations", type=str, default="Australia,India", help="Target locations separated by comma (default: Australia,India)")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of jobs to collect")
    parser.add_argument("--pages", type=int, default=5, help="Maximum pages per keyword")
    parser.add_argument("--deep", action="store_true", help="Perform deep scrape on each job detail page")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible UI mode")
    parser.add_argument("--output", type=Path, default=OUTPUT_JOBS_CSV, help="Output CSV path")
    parser.add_argument("--mongo", action="store_true", help="Save results to MongoDB")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    kw_list = [args.keyword] if args.keyword else None
    loc_list = [l.strip() for l in args.locations.split(",") if l.strip()]
    run_upwork_scraper(
        keywords=kw_list,
        locations=loc_list,
        limit=args.limit,
        max_pages=args.pages,
        deep_scrape=args.deep,
        headless=not args.headed,
        output_csv=args.output,
        save_mongo=args.mongo,
    )


if __name__ == "__main__":
    main()
