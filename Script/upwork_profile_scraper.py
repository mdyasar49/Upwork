#!/usr/bin/env python3
"""
Upwork Talent Profile Scraper.

Extracts talent profiles, hourly rates, total earnings, completed jobs, hours worked,
languages, education, associated agencies, and skills.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import argparse
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")
PROJECT_DIR = SCRIPT_DIR.parent
INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = PROJECT_DIR / "Output"

PROFILES_INPUT_CSV = INPUT_DIR / "profile_urls.csv"
OUTPUT_PROFILES_CSV = OUTPUT_DIR / "upwork_profile_leads.csv"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_el(el: Any) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(strip=True)).strip()


def init_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=opts)


def scrape_single_profile(driver: webdriver.Chrome, profile_url: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "Profile_URL": profile_url,
        "Hourly_Rate": "",
        "City": "",
        "Country": "",
        "Total_Earnings": "",
        "Total_Jobs": "",
        "Total_Hours": "",
        "Hours_Per_Week": "",
        "Response_Time": "",
        "Contract_To_Hire": False,
        "Languages": "",
        "Education": "",
        "Associated_Agency": "",
        "Agency_Earning": "",
        "Description": "",
        "Scraped_At": now_utc_iso(),
    }

    try:
        driver.get(profile_url)
        time.sleep(random.uniform(4, 7))
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # Hourly Rate
        rate_el = soup.find("span", string=lambda x: x and "/hr" in x) or soup.find("div", {"data-test": "rate"})
        data["Hourly_Rate"] = clean_el(rate_el)

        # Location
        loc_el = soup.select_one("div.location span[itemprop='locality']") or soup.find("span", {"data-test": "locality"})
        country_el = soup.select_one("div.location span[itemprop='country-name']") or soup.find("span", {"data-test": "country"})
        data["City"] = clean_el(loc_el)
        data["Country"] = clean_el(country_el)

        # Description
        desc_el = soup.select_one("[data-cy='about-me-section'] p") or soup.find("div", {"data-test": "overview"})
        data["Description"] = clean_el(desc_el)

        # Stats
        stats = soup.select(".stat-amount span") or soup.find_all("span", class_=lambda c: c and "stat-amount" in c)
        if len(stats) > 0:
            data["Total_Earnings"] = clean_el(stats[0])
        if len(stats) > 1:
            data["Total_Jobs"] = clean_el(stats[1])
        if len(stats) > 2:
            data["Total_Hours"] = clean_el(stats[2])

        # Hours per week
        h5 = soup.find("h5", string=lambda x: x and "Hours per week" in x)
        if h5:
            data["Hours_Per_Week"] = clean_el(h5.find_next("span"))

        # Response time
        resp_el = soup.find("p", string=lambda x: x and "response time" in x)
        data["Response_Time"] = clean_el(resp_el)

        # Contract to hire
        data["Contract_To_Hire"] = bool(soup.find("span", string=lambda x: x and "Open to contract to hire" in x))

        # Languages
        lang_section = soup.find("h5", string=lambda x: x and "Languages" in x)
        if lang_section:
            ul = lang_section.find_next("ul")
            if ul:
                langs = [clean_el(li) for li in ul.find_all("li")]
                data["Languages"] = "; ".join(langs)

        # Education
        edu_section = soup.find("h5", string=lambda x: x and "Education" in x)
        if edu_section:
            ul = edu_section.find_next("ul")
            if ul:
                edus = [clean_el(li) for li in ul.find_all("li")]
                data["Education"] = "; ".join(edus)

        # Agency
        agency_el = soup.select_one("[data-test='FreelancerTileAgency'] .name")
        data["Associated_Agency"] = clean_el(agency_el)
        earn_el = soup.select_one("[data-test='agency-earning-amount']")
        data["Agency_Earning"] = clean_el(earn_el)

    except Exception as e:
        print(f"  [!] Error scraping {profile_url}: {e}")

    return data


def run_profile_scraper(
    input_csv: Path = PROFILES_INPUT_CSV,
    output_csv: Path = OUTPUT_PROFILES_CSV,
    headless: bool = True,
) -> pd.DataFrame:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not input_csv.exists():
        print(f"[!] Input CSV not found: {input_csv}")
        return pd.DataFrame()

    df_in = pd.read_csv(input_csv)
    col = [c for c in df_in.columns if "url" in c.lower()]
    if not col:
        print("[!] No profile URL column found in input CSV.")
        return pd.DataFrame()

    urls = [str(u).strip() for u in df_in[col[0]].dropna().unique() if str(u).strip().startswith("http")]
    print(f"[+] Loaded {len(urls)} profile URLs to scrape.")

    driver = init_driver(headless=headless)
    results = []

    try:
        for idx, url in enumerate(urls, start=1):
            print(f"[{idx}/{len(urls)}] Scraping profile: {url}")
            p_data = scrape_single_profile(driver, url)
            results.append(p_data)
            
            # Incremental append
            df_s = pd.DataFrame([p_data])
            write_header = not output_csv.exists() or output_csv.stat().st_size == 0
            df_s.to_csv(output_csv, mode="a", header=write_header, index=False, encoding="utf-8-sig")
            time.sleep(random.uniform(3, 6))

    finally:
        driver.quit()

    df_out = pd.DataFrame(results)
    print(f"[✓] Completed profile scraping. Saved {len(df_out)} profiles to {output_csv.name}.")
    return df_out


if __name__ == "__main__":
    run_profile_scraper()
