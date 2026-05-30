"""Debug script to inspect the concurrent page HTML structure."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(override=False)

from src.auth import IMSAuth
import requests

base_url = os.environ.get("IMS_BASE_URL", "https://ims.marvellousfiber.com")
username = os.environ.get("IMS_USERNAME")
password = os.environ.get("IMS_PASSWORD")

auth = IMSAuth(base_url=base_url, username=username, password=password)
auth.login()
print("Logged in OK")

# Fetch the concurrent page
url = f"{base_url}/Dashboard/UserDataConcurrent?StatusName=Inactive"
resp = auth.session.get(url, timeout=30)
print(f"Page status: {resp.status_code}, size: {len(resp.text)}")

# Save full HTML for inspection
with open("debug_concurrent_page.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("Saved to debug_concurrent_page.html")

# Look for table elements and script tags with AJAX URLs
from bs4 import BeautifulSoup
soup = BeautifulSoup(resp.text, "html.parser")

# Find all tables
tables = soup.find_all("table")
print(f"\nFound {len(tables)} table(s):")
for i, t in enumerate(tables):
    attrs = dict(t.attrs)
    rows = t.find_all("tr")
    print(f"  Table {i}: id={attrs.get('id')}, class={attrs.get('class')}, rows={len(rows)}")

# Find script tags that reference DataTable or ajax
scripts = soup.find_all("script")
print(f"\nFound {len(scripts)} script tags. Looking for AJAX/DataTable URLs...")
for script in scripts:
    text = script.get_text()
    if "ajax" in text.lower() or "getdata" in text.lower() or "url" in text.lower():
        # Extract relevant lines
        lines = text.split("\n")
        for line in lines:
            line_stripped = line.strip()
            if any(kw in line_stripped.lower() for kw in ["ajax", "url", "getdata", "datatable"]):
                if len(line_stripped) < 200:
                    print(f"  >> {line_stripped}")
