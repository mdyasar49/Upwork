#!/usr/bin/env python3
"""
Upwork Client Jobs & Freelancer Contract History Scraper.

Extracts past job contracts posted by a client or completed by freelancers,
including job titles, hired freelancer names, contract date ranges, hourly rates,
and total billed amounts.
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
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"

OUTPUT_CLIENT_CONTRACTS_CSV = OUTPUT_DIR / "upwork_client_contracts.csv"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=opts)


def scrape_client_contracts(
    job_urls: List[str],
    output_csv: Path = OUTPUT_CLIENT_CONTRACTS_CSV,
    headless: bool = True,
) -> pd.DataFrame:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = init_driver(headless=headless)
    wait = WebDriverWait(driver, 15)
    all_contracts: List[Dict[str, Any]] = []

    try:
        for idx, url in enumerate(job_urls, start=1):
            print(f"[{idx}/{len(job_urls)}] Scraping client contract history: {url}")
            driver.get(url)
            time.sleep(random.uniform(4, 7))

            try:
                # Scroll to client history section
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(1)

                job_items = driver.find_elements(By.CSS_SELECTOR, "div.item[data-cy='job'], div[data-test='client-history-item']")
                print(f"  Found {len(job_items)} client contract records on page.")

                for item in job_items:
                    try:
                        # Job title + URL
                        title_el = item.find_element(By.CSS_SELECTOR, "a[data-cy='job-title'], h4 a")
                        job_title = title_el.text.strip()
                        contract_job_url = urljoin("https://www.upwork.com", title_el.get_attribute("href"))

                        # Freelancer name + URL
                        freelancer_name = ""
                        freelancer_url = ""
                        try:
                            f_el = item.find_element(By.CSS_SELECTOR, "a[href*='/freelancers/']")
                            freelancer_name = f_el.text.strip()
                            freelancer_url = urljoin("https://www.upwork.com", f_el.get_attribute("href"))
                        except Exception:
                            pass

                        # Date range
                        date_range = ""
                        try:
                            date_el = item.find_element(By.CSS_SELECTOR, "div[data-cy='date'], .text-body-sm")
                            date_range = date_el.text.strip()
                        except Exception:
                            pass

                        # Stats (hours, rate, billed)
                        stats_text = ""
                        try:
                            stats_el = item.find_element(By.CSS_SELECTOR, "div[data-cy='stats'], .stats")
                            stats_text = stats_el.text.strip()
                        except Exception:
                            pass

                        hours = ""
                        rate = ""
                        billed = ""
                        if "hrs" in stats_text:
                            hours = stats_text.split("hrs")[0].strip()
                        if "@ $" in stats_text:
                            rate = stats_text.split("@")[1].split("/hr")[0].strip()
                        if "Billed:" in stats_text:
                            billed = stats_text.split("Billed:")[1].strip()

                        contract_data = {
                            "Parent_Job_URL": url,
                            "Contract_Job_Title": job_title,
                            "Contract_Job_URL": contract_job_url,
                            "Freelancer_Name": freelancer_name,
                            "Freelancer_URL": freelancer_url,
                            "Date_Range": date_range,
                            "Hours_Worked": hours,
                            "Rate_Per_Hour": rate,
                            "Billed_Amount": billed,
                            "Scraped_At": now_utc_iso(),
                        }
                        all_contracts.append(contract_data)

                        df_s = pd.DataFrame([contract_data])
                        write_header = not output_csv.exists() or output_csv.stat().st_size == 0
                        df_s.to_csv(output_csv, mode="a", header=write_header, index=False, encoding="utf-8-sig")

                    except Exception as parse_e:
                        continue

            except Exception as e:
                print(f"  [!] Error processing {url}: {e}")

    finally:
        driver.quit()

    df_out = pd.DataFrame(all_contracts)
    print(f"[✓] Scraped {len(df_out)} contracts. Saved to {output_csv.name}.")
    return df_out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        scrape_client_contracts([sys.argv[1]])
