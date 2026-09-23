# Upwork Lead Scraper & CRM Automation Suite

Production-ready Upwork Lead Scraper and CRM Automation Pipeline with a **Modern Web Screen Dashboard (No Code Required)** and automated Google Sheets sync.

---

## 🖥️ Screen-Based Manual Search Dashboard (No Terminal / Code Needed)

You can perform manual searches directly from a **Web UI Screen** without typing terminal commands or running code:

### How to Open the Screen UI:
1. Simply double-click **[`start_search_dashboard.bat`](file:///d:/infonix/Upwork/start_search_dashboard.bat)** in the `Upwork` folder (or run `python app.py` inside `Script/`).
2. Your browser will automatically open: **`http://localhost:5000`**
3. On the screen:
   - Type or select your **Keywords** (e.g., `Shopify, Flutter, AI Integration, Python`).
   - Select or type your **Locations** (`Australia, India`, etc.).
   - Enter your **New Tab Name** (or use the auto-generated timestamp name).
   - Click **"🚀 Start Search & Create Sheet Tab"**.
4. The dashboard will show:
   - Real-time progress bar.
   - Live streaming lead cards with budget, skills, location, extracted email & phone number.
   - Real-time console logs.
5. Once complete, click **"📊 Open Google Sheet CRM"** to jump directly into your newly created tab in Google Sheets!

---

## 🔗 Configured Integrations

- **Google Sheet CRM**: [`Upwork_Leads`](https://docs.google.com/spreadsheets/d/1qLxmNGGeuFuXnQnH4ITtnEGdaUpfzquIaf7wDHJpdD0/edit?usp=sharing)
- **Target Sheet Tab**: `Sheet1` (and dynamic custom tabs created via Web Dashboard or `manual_search.py`)
- **Default Keywords Source**: 1,502 Verified Freelance & Tech Keywords ([`upwork_keywords.csv`](file:///d:/infonix/Upwork/Script/input/upwork_keywords.csv))
- **Default Target Locations**: `Australia` & `India`

---

## 📁 Project Structure

```
Upwork/
├── start_search_dashboard.bat             # 🌟 1-Click Double-Click Screen UI Launcher
├── Output/                                # Scraped datasets and lead CSVs
│   ├── manual_searches/                   # Dedicated CSVs for manual search sessions
│   ├── upwork_job_leads.csv               # Primary scraped job leads
│   ├── upwork_profile_leads.csv           # Talent profile leads
│   ├── upwork_client_contracts.csv        # Client past hiring and contract history
│   └── upwork_all_data.csv                # Deep scraped full dataset
├── logs/                                  # Execution and scheduler logs
│   └── daily_run_YYYYMMDD.log
└── Script/                                # Automation scripts & configurations
    ├── templates/
    │   └── index.html                     # Web Screen Dashboard UI
    ├── input/                             # Target keywords, URLs, and filter phrases
    │   ├── upwork_keywords.csv            # 1,502 Curated Keywords (AI, Fullstack, Python, Twilio, etc.)
    │   ├── upwork_keywords_1502.txt       # Raw keywords file from Google Drive
    │   ├── upwork_search_urls.csv         # Direct search URLs
    │   ├── upwork_filter_details.txt      # Intent / Requirement filter phrases
    │   └── profile_urls.csv              # Talent profile URLs
    ├── credentials/                       # Google Cloud service account keys
    │   └── google_service_account.json
    ├── .env                               # Active environment configuration
    ├── .env.example                       # Environment template
    ├── .gitignore                         # Git exclusion rules
    ├── requirements.txt                   # Python dependencies
    ├── app.py                             # 🚀 Flask Web UI Server for Screen Searches
    ├── manual_search.py                   # Interactive Manual Search CLI + New Tab Creator
    ├── upwork_scraper.py                  # Core Upwork job scraping engine (Australia & India)
    ├── upwork_profile_scraper.py          # Freelancer/Talent profile scraper
    ├── upwork_freelancer_scraper.py       # Client contract history scraper
    ├── freelancer_scraper.py              # Freelancer.com project scraper
    ├── clean_upwork_jobs.py               # Data cleaner & phone/email normalizer
    ├── sheets_sync.py                     # Google Sheets 28-column CRM live sync
    ├── upwork_pipeline.py                 # Continuous 800+ leads batch pipeline
    ├── deploy_check.py                    # Pre-flight environment & sheets check
    ├── upwork_analysis.ipynb              # Interactive Jupyter analysis notebook
    └── daily_run.py                       # Automated daily runner for cron/scheduler
```

---

## 💻 All Ways to Run

| Method | Command / Action | Description |
| :--- | :--- | :--- |
| **Web Screen Dashboard** | Double click [`start_search_dashboard.bat`](file:///d:/infonix/Upwork/start_search_dashboard.bat) | Visual browser UI to search & create new Google Sheet tabs without terminal |
| **Interactive Terminal** | `python manual_search.py` | Step-by-step console prompts for custom keywords & tab name |
| **CLI Search** | `python manual_search.py --keywords "Shopify" --locations "Australia" --tab "Shopify_AU"` | One-liner command for custom search & new tab creation |
| **Daily Cron Automation** | `python daily_run.py --limit 50` | Automatically scrapes default 1,502 keywords across Australia & India and syncs to Sheet1 |
| **800+ Leads Pipeline** | `python upwork_pipeline.py --target 800` | Continuous batch quota lead generation |
| **Pre-flight Check** | `python deploy_check.py` | Validates Chrome, dependencies, credentials & Google Sheets access |
