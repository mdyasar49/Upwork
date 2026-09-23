#!/usr/bin/env python3
"""
Upwork Lead Scraper - Interactive Web Dashboard & UI Server.

Provides a clean browser-based GUI to enter keywords, locations, and new Google Sheet
tab names, start live scraping, and watch real-time lead extraction without touching code.
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "Output"
MANUAL_OUTPUT_DIR = OUTPUT_DIR / "manual_searches"
LOG_DIR = PROJECT_DIR / "logs"

load_dotenv(SCRIPT_DIR / ".env")

from upwork_scraper import (
    DEFAULT_LOCATIONS,
    OUTPUT_COLUMNS,
    ensure_dirs,
    load_keywords,
    run_upwork_scraper,
)
from sheets_sync import (
    DEFAULT_SHEET_ID,
    SHEET_COLUMNS,
    append_upwork_records_to_sheet,
    open_worksheet,
)

app = Flask(__name__, template_folder=str(SCRIPT_DIR / "templates"), static_folder=str(SCRIPT_DIR / "static"))

# Global scraping state and message event queue for Server-Sent Events (SSE)
scrape_state = {
    "is_running": False,
    "progress": 0,
    "total_target": 0,
    "current_keyword": "",
    "current_location": "",
    "found_jobs": [],
    "logs": [],
    "last_tab_name": "",
    "sheet_url": f"https://docs.google.com/spreadsheets/d/{DEFAULT_SHEET_ID}/edit",
    "error": None,
}

event_queue: queue.Queue = queue.Queue()


def emit_event(event_type: str, data: Dict[str, Any]) -> None:
    payload = json.dumps({"event": event_type, "data": data})
    event_queue.put(payload)


@app.route("/")
def index():
    default_keywords = load_keywords()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID)
    return render_template(
        "index.html",
        default_keywords=default_keywords[:100],  # send top 100 for auto-complete
        total_keywords_count=len(default_keywords),
        default_locations=DEFAULT_LOCATIONS,
        sheet_id=sheet_id,
        sheet_url=f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
    )


@app.route("/api/keywords", methods=["GET"])
def api_keywords():
    keywords = load_keywords()
    return jsonify({"keywords": keywords, "count": len(keywords)})


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify(scrape_state)


@app.route("/api/events")
def sse_events():
    def event_stream():
        while True:
            try:
                msg = event_queue.get(timeout=25)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                # Keep-alive heartbeat
                yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


def worker_scrape_task(
    keywords: List[str],
    locations: List[str],
    tab_name: str,
    limit: int,
    headed: bool,
    deep: bool,
    sync_sheet: bool,
):
    global scrape_state
    ensure_dirs()
    MANUAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    scrape_state["is_running"] = True
    scrape_state["progress"] = 0
    scrape_state["total_target"] = limit
    scrape_state["found_jobs"] = []
    scrape_state["logs"] = []
    scrape_state["error"] = None
    scrape_state["last_tab_name"] = tab_name

    sheet_id = os.environ.get("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID).strip()
    safe_tab_filename = re.sub(r"[^\w\-]", "_", tab_name)
    session_csv = MANUAL_OUTPUT_DIR / f"{safe_tab_filename}.csv"

    emit_event("log", {"message": f"🚀 Starting Search for {len(keywords)} keywords across {len(locations)} locations..."})

    try:
        from upwork_scraper import init_driver, parse_job_tile, scrape_job_details_page, safe_quit_driver
        from urllib.parse import quote
        from bs4 import BeautifulSoup
        import random
        import pandas as pd

        driver = init_driver(headless=not headed)
        collected_records = []
        total_valid = 0
        existing_urls = set()

        try:
            for loc in locations:
                if total_valid >= limit:
                    break
                scrape_state["current_location"] = loc
                emit_event("log", {"message": f"🌍 Target Location: {loc.upper()}"})

                for kw_idx, keyword in enumerate(keywords, start=1):
                    if total_valid >= limit:
                        break
                    scrape_state["current_keyword"] = keyword
                    emit_event("status_update", {
                        "keyword": keyword,
                        "location": loc,
                        "progress": total_valid,
                        "limit": limit
                    })
                    emit_event("log", {"message": f"🔍 Searching: '{keyword}' ({loc})"})

                    for page in range(1, 6):
                        if total_valid >= limit:
                            break

                        if loc and loc.lower() != "all":
                            search_url = f"https://www.upwork.com/nx/search/jobs/?location={quote(loc)}&q={quote(keyword)}&sort=recency&page={page}"
                        else:
                            search_url = f"https://www.upwork.com/nx/search/jobs/?q={quote(keyword)}&sort=recency&page={page}"

                        try:
                            driver.get(search_url)
                            time.sleep(random.uniform(4, 6))

                            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                            time.sleep(1)
                            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                            time.sleep(random.uniform(1.5, 2.5))

                            soup = BeautifulSoup(driver.page_source, "html.parser")
                            job_tiles = (
                                soup.find_all("article", {"data-test": "JobTile"})
                                or soup.find_all("article")
                                or soup.find_all("section", class_=lambda c: c and "up-card-section" in c)
                            )

                            if not job_tiles:
                                break

                            for tile in job_tiles:
                                if total_valid >= limit:
                                    break

                                job_data = parse_job_tile(tile, keywords)
                                if not job_data:
                                    continue

                                job_url = job_data["Job_URL"]
                                if job_url in existing_urls:
                                    continue

                                if deep and job_url != "N/A":
                                    emit_event("log", {"message": f"  -> Deep scraping job details: {job_data['Job_Title'][:40]}..."})
                                    deep_details = scrape_job_details_page(driver, job_url, keywords)
                                    job_data.update({k: v for k, v in deep_details.items() if v})

                                total_valid += 1
                                job_data["Job_Number"] = total_valid
                                if not job_data.get("Client_Location"):
                                    job_data["Client_Location"] = loc

                                existing_urls.add(job_url)
                                collected_records.append(job_data)
                                scrape_state["found_jobs"].append(job_data)
                                scrape_state["progress"] = total_valid

                                # Incremental CSV append
                                df_single = pd.DataFrame([job_data])
                                for col in OUTPUT_COLUMNS:
                                    if col not in df_single.columns:
                                        df_single[col] = ""
                                df_single = df_single[OUTPUT_COLUMNS]
                                write_header = not session_csv.exists() or session_csv.stat().st_size == 0
                                df_single.to_csv(session_csv, mode="a", header=write_header, index=False, encoding="utf-8-sig")

                                # Emit lead card to frontend
                                emit_event("new_lead", {
                                    "job": job_data,
                                    "progress": total_valid,
                                    "total": limit,
                                })
                                emit_event("log", {"message": f"  ✅ Extracted #{total_valid}: {job_data['Job_Title'][:50]} | {job_data['Budget'] or job_data['Hourly_Min']}"})

                        except Exception as pe:
                            emit_event("log", {"message": f"  ⚠️ Page Notice: {pe}"})

                        time.sleep(random.uniform(2, 4))
        finally:
            safe_quit_driver(driver)

        # Google Sheets New Tab Sync
        if sync_sheet and sheet_id and collected_records:
            emit_event("log", {"message": f"📊 Creating NEW TAB '{tab_name}' in Google Spreadsheet..."})
            try:
                worksheet = open_worksheet(sheet_id=sheet_id, tab_name=tab_name)
                if not worksheet.row_values(1):
                    worksheet.append_row(SHEET_COLUMNS)

                appended = append_upwork_records_to_sheet(collected_records, worksheet=worksheet)
                tab_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={worksheet.id}"
                scrape_state["sheet_url"] = tab_url

                emit_event("log", {"message": f"🎉 Successfully added {appended} rows into Google Sheet Tab: '{tab_name}'!"})
                emit_event("sheet_synced", {
                    "tab_name": tab_name,
                    "sheet_url": tab_url,
                    "rows_added": appended
                })
            except Exception as se:
                emit_event("log", {"message": f"⚠️ Google Sheet notice: {se}"})

        emit_event("complete", {
            "total_extracted": total_valid,
            "tab_name": tab_name,
            "sheet_url": scrape_state["sheet_url"],
            "csv_file": str(session_csv.name)
        })
        emit_event("log", {"message": f"🏁 Search Finished! Collected {total_valid} jobs."})

    except Exception as exc:
        scrape_state["error"] = str(exc)
        emit_event("error", {"message": str(exc)})
        emit_event("log", {"message": f"❌ Error: {exc}"})

    finally:
        scrape_state["is_running"] = False


@app.route("/api/start", methods=["POST"])
def api_start():
    if scrape_state["is_running"]:
        return jsonify({"success": False, "error": "A search job is already running."}), 400

    data = request.json or {}
    raw_kw = data.get("keywords", "")
    if isinstance(raw_kw, str):
        keywords = [k.strip() for k in raw_kw.split(",") if k.strip()]
    else:
        keywords = list(raw_kw)

    if not keywords:
        keywords = ["AI Integration", "React.js", "Python"]

    raw_loc = data.get("locations", "")
    if isinstance(raw_loc, str):
        locations = [l.strip() for l in raw_loc.split(",") if l.strip()]
    else:
        locations = list(raw_loc)

    if not locations:
        locations = ["Australia", "India"]

    tab_name = data.get("tab_name", "").strip()
    if not tab_name:
        tab_name = f"Search_{datetime.now().strftime('%Y%m%d_%H%M')}"
    tab_name = re.sub(r"[:\\/?*\[\]]", "_", tab_name)[:80]

    limit = int(data.get("limit", 30))
    headed = bool(data.get("headed", False))
    deep = bool(data.get("deep", False))
    sync_sheet = bool(data.get("sync_sheet", True))

    t = threading.Thread(
        target=worker_scrape_task,
        args=(keywords, locations, tab_name, limit, headed, deep, sync_sheet),
        daemon=True,
    )
    t.start()

    return jsonify({
        "success": True,
        "message": f"Search started for '{tab_name}'",
        "keywords": keywords,
        "locations": locations,
        "limit": limit
    })


def main():
    port = int(os.environ.get("PORT", 5000))
    print(f"\n==================================================")
    print(f"🌟 UPWORK LEAD SEARCH DASHBOARD IS RUNNING!")
    print(f"👉 Open in your browser: http://localhost:{port}")
    print(f"==================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
