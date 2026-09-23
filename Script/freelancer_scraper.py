#!/usr/bin/env python3
"""
Freelancer.com Project & Contest Scraper.

Extracts projects, budgets, client reviews, ratings, skills, tags, average bids,
currencies, and country locations from Freelancer.com.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import argparse
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pytz
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"
LOG_DIR = PROJECT_DIR / "logs"

OUTPUT_FREELANCER_CSV = OUTPUT_DIR / "freelancer_project_leads.csv"

CURRENCY_TO_COUNTRY = {
    "USD": "United States",
    "AUD": "Australia",
    "CAD": "Canada",
    "GBP": "United Kingdom",
    "EUR": "European Union",
    "INR": "India",
    "NZD": "New Zealand",
    "SGD": "Singapore",
    "JPY": "Japan",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=opts)


def scrape_freelancer_projects(
    query: str = "australia",
    start_page: int = 1,
    end_page: int = 3,
    output_csv: Path = OUTPUT_FREELANCER_CSV,
    headless: bool = True,
    save_mongo: bool = False,
) -> pd.DataFrame:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = init_driver(headless=headless)
    all_projects = []

    try:
        for page in range(start_page, end_page + 1):
            url = f"https://www.freelancer.com/search/projects?types=hourly,fixed&projectLanguages=en&projectSort=latest&q={query}&page={page}"
            print(f"\n[+] Loading Freelancer page {page}: {url}")
            driver.get(url)
            time.sleep(random.uniform(5, 8))

            soup = BeautifulSoup(driver.page_source, "html.parser")
            cards = soup.find_all("fl-project-contest-card") or soup.find_all("div", class_=lambda c: c and "ProjectTable-row" in c)
            print(f"  [✓] Found {len(cards)} project cards.")

            for card in cards:
                try:
                    title_tag = card.find("h2", class_=lambda c: c and "Title-text" in c) or card.find("a", class_=lambda c: c and "ProjectTable-title" in c)
                    title = title_tag.get_text(strip=True) if title_tag else "N/A"
                    link = title_tag.find("a")["href"] if (title_tag and title_tag.find("a")) else ""
                    if link and not link.startswith("http"):
                        link = "https://www.freelancer.com" + link

                    budget_tag = card.find("span", class_=lambda c: c and "Budget" in c)
                    budget = budget_tag.get_text(strip=True) if budget_tag else "N/A"

                    desc_tag = card.find("p", class_=lambda c: c and "mb-xxsmall" in c) or card.find("div", class_=lambda c: c and "ProjectTable-description" in c)
                    description = desc_tag.get_text(strip=True) if desc_tag else ""

                    rating_tag = card.find("div", class_=lambda c: c and "ValueBlock" in c)
                    rating = rating_tag.get_text(strip=True) if rating_tag else ""

                    review_tag = card.find("span", class_=lambda c: c and "text-foreground" in c)
                    reviews = review_tag.get_text(strip=True) if review_tag else ""

                    time_tag = card.find("fl-relative-time")
                    time_posted = time_tag.get_text(strip=True) if time_tag else ""

                    skills = [s.get_text(strip=True) for s in card.find_all("div", class_="Content")]
                    skills_str = ", ".join(skills)

                    avg_bid_elem = card.find("span", fltrackinglabel="AverageProjectBidTooltip")
                    avg_bid = avg_bid_elem.get_text(strip=True) if avg_bid_elem else ""

                    bids_elem = card.find("div", class_=lambda c: c and "BidEntryData" in c)
                    bids = bids_elem.get_text(strip=True) if bids_elem else ""

                    # Currency parse
                    parts = avg_bid.replace("$", "").split()
                    currency_code = parts[1] if len(parts) > 1 else "USD"
                    country_name = CURRENCY_TO_COUNTRY.get(currency_code, "International")

                    record = {
                        "Platform": "Freelancer",
                        "Project_Title": title,
                        "Project_URL": link,
                        "Budget": budget,
                        "Average_Bid": avg_bid,
                        "Bids_Count": bids,
                        "Client_Rating": rating,
                        "Client_Reviews": reviews,
                        "Skills": skills_str,
                        "Currency": currency_code,
                        "Country": country_name,
                        "Posted_Time": time_posted,
                        "Description": description,
                        "Scraped_At": now_utc_iso(),
                    }
                    all_projects.append(record)

                    df_s = pd.DataFrame([record])
                    write_header = not output_csv.exists() or output_csv.stat().st_size == 0
                    df_s.to_csv(output_csv, mode="a", header=write_header, index=False, encoding="utf-8-sig")

                except Exception as parse_e:
                    continue

    finally:
        driver.quit()

    df_out = pd.DataFrame(all_projects)
    print(f"\n[✓] Freelancer scraping complete! Total {len(df_out)} projects saved to {output_csv.name}.")

    if save_mongo and not df_out.empty:
        try:
            import pymongo
            mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
            client = pymongo.MongoClient(mongo_uri)
            db = client[os.environ.get("MONGO_DB_NAME", "upwork_db")]
            col = db["freelancer_jobs"]
            col.insert_many(df_out.to_dict(orient="records"), ordered=False)
            print(f"[✓] Saved records to MongoDB (freelancer_jobs).")
        except Exception as me:
            print(f"[!] MongoDB note: {me}")

    return df_out


def main() -> None:
    parser = argparse.ArgumentParser(description="Freelancer.com Scraper")
    parser.add_argument("--query", type=str, default="australia", help="Search query")
    parser.add_argument("--pages", type=int, default=3, help="Pages to scrape")
    parser.add_argument("--headed", action="store_true", help="Run with browser UI")
    parser.add_argument("--mongo", action="store_true", help="Save to MongoDB")
    args = parser.parse_args()

    scrape_freelancer_projects(
        query=args.query,
        end_page=args.pages,
        headless=not args.headed,
        save_mongo=args.mongo,
    )


if __name__ == "__main__":
    main()
