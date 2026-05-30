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
print(f"Final URL: {resp.url}")
print(f"Content-Type: {resp.headers.get('Content-Type')}")

# Print first 3000 chars of the page
print("\n=== PAGE CONTENT (first 3000 chars) ===")
print(resp.text[:3000])

# Print all script tag contents (inline JS)
from bs4 import BeautifulSoup
soup = BeautifulSoup(resp.text, "html.parser")

scripts = soup.find_all("script")
print(f"\n=== SCRIPT TAGS ({len(scripts)}) ===")
for i, script in enumerate(scripts):
    src = script.get("src", "")
    text = script.get_text().strip()
    if src:
        print(f"  Script {i}: src={src}")
    if text:
        # Print inline scripts (first 500 chars each)
        print(f"  Script {i} (inline, {len(text)} chars):")
        print(f"    {text[:500]}")
        print()
