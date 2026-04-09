import os
import json
import re
import hashlib
import requests
from datetime import datetime, date
from dateutil import parser as dateparser
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URL = "https://eugenieterrace.com/floor-plans/?availability-tabs=apartments-tab"
WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")
STATE_FILE = "seen_matches.json"

START_DATE = date(2026, 6, 1)
END_DATE = date(2026, 6, 30)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_state(seen):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(list(seen)), f)

def make_key(unit, move_in):
    return hashlib.sha256(f"{unit}|{move_in}".encode()).hexdigest()

def send_alert(title, body):
    requests.post(
        WEBHOOK_URL,
        json={"title": title, "body": body, "url": TARGET_URL},
        timeout=15
    )

def fetch_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)

        try:
            page.wait_for_selector("text=Available", timeout=15000)
        except Exception:
            pass

        html = page.content()
        browser.close()
        return html

def parse_date(text):
    try:
        d = dateparser.parse(text, fuzzy=True, default=datetime(2026, 6, 1))
        return d.date()
    except Exception:
        return None

def find_matches(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [l for l in text.split("\n") if l]

    matches = []

    for i in range(len(lines)):
        block = " ".join(lines[max(0, i-3):min(len(lines), i+6)])

        if not re.search(r"\bA1\b", block, re.IGNORECASE):
            continue

        if not re.search(r"\b1\s*Bed(room)?\b", block, re.IGNORECASE):
            continue

        date_match = (
            re.search(r"\b(Jun(?:e)?\s+\d{1,2}(?:,\s*2026)?)\b", block, re.IGNORECASE)
            or re.search(r"\b(0?6/\d{1,2}/2026)\b", block)
        )

        if not date_match:
            continue

        move_in = parse_date(date_match.group(1))
        if not move_in or not (START_DATE <= move_in <= END_DATE):
            continue

        unit_match = re.search(r"\b(Unit\s*)?([0-9]{3,5})\b", block)
        unit = unit_match.group(2) if unit_match else "UNKNOWN"

        matches.append({
            "unit": unit,
            "move_in": move_in.isoformat(),
            "details": block
        })

    return matches

def main():
    if not WEBHOOK_URL:
        raise RuntimeError("ZAPIER_WEBHOOK_URL not set")

    seen = load_state()
    html = fetch_page()
    matches = find_matches(html)

    new_matches = []

    for m in matches:
        key = make_key(m["unit"], m["move_in"])
        if key not in seen:
            seen.add(key)
            new_matches.append(m)

    if new_matches:
        body = "\n\n".join(
            f"A1 (~961 sq ft)\nUnit {m['unit']}\nMove-in: {m['move_in']}"
            for m in new_matches
        )
        send_alert(
            "Eugenie Terrace – A1 1‑Bed Available",
            body
        )

    save_state(seen)

if __name__ == "__main__":
    main()
