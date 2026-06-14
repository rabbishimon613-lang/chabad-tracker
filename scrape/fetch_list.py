"""
Layer 1, step 1: fetch the global centers list + service-type lookup.

Outputs:
  data/raw/types.json          — service-type id -> name
  data/raw/centers_list.json   — all centers (lite view), one big array
"""
from curl_cffi import requests
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW  = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

BASE = "https://www.chabad.org/api/v2/chabadorg"
HEADERS = {"Accept": "application/json"}

def get(url):
    r = requests.get(url, impersonate="chrome", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    print("fetching types...")
    types = get(f"{BASE}/centers/types?format=jsonapi&lang=en")
    (RAW/"types.json").write_text(json.dumps(types, indent=2))
    print(f"  {len(types.get('data',[]))} service-types -> {RAW/'types.json'}")

    print("fetching global centers list...")
    centers = get(f"{BASE}/centers")
    (RAW/"centers_list.json").write_text(json.dumps(centers, indent=2))
    items = centers.get("data", [])
    print(f"  {len(items)} centers -> {RAW/'centers_list.json'}")

if __name__ == "__main__":
    main()
