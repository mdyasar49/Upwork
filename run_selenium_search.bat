@echo off
title Upwork Lead Scraper - Selenium Manual Search
color 0A
cd /d "%~dp0Script"

echo ======================================================================
echo           UPWORK INTELLIGENCE SCRAPER - LIVE SELENIUM ENGINE
echo ======================================================================
echo.

python manual_search.py

echo.
echo ======================================================================
echo  Scraping and Google Sheets sync complete.
echo ======================================================================
pause
