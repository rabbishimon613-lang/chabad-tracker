"""
Layer 1, step 2: fetch per-center detail for every mosad-aid in centers_list.json.

Concurrency: 4 workers, ~5 req/sec target.
Resume-safe: skips aids whose file already exists in data/raw/centers/.
Output: data/raw/centers/{aid}.json
"""
from curl_cffi import requests
import json, pathlib, time, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_LIST = ROOT / "data" / "raw" / "centers_list.json"
OUT_DIR  = ROOT / "data" / "raw" / "centers"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://www.chabad.org/api/v2/chabadorg"
HEADERS = {"Accept": "application/json"}

# Politeness: at most ~5 requests per second across all threads.
RATE_PER_SEC = 5
_rate_lock = threading.Lock()
_last_times: list[float] = []

def throttle():
    with _rate_lock:
        now = time.time()
        # Drop entries older than 1 second
        while _last_times and now - _last_times[0] > 1.0:
            _last_times.pop(0)
        if len(_last_times) >= RATE_PER_SEC:
            sleep_for = 1.0 - (now - _last_times[0]) + 0.01
            if sleep_for > 0:
                time.sleep(sleep_for)
        _last_times.append(time.time())

def fetch_one(aid: int, retries: int = 3) -> tuple[int, str]:
    out = OUT_DIR / f"{aid}.json"
    if out.exists() and out.stat().st_size > 50:
        return aid, "skip"
    url = f"{BASE}/centers/{aid}?format=jsonapi&lang=en"
    for attempt in range(retries):
        try:
            throttle()
            r = requests.get(url, impersonate="chrome", headers=HEADERS, timeout=30)
            if r.status_code == 200:
                out.write_text(r.text)
                return aid, "ok"
            if r.status_code in (404, 410):
                out.write_text(json.dumps({"_error": r.status_code}))
                return aid, f"err{r.status_code}"
            # 429 / 5xx → backoff
            time.sleep(2 ** attempt)
        except Exception as e:
            if attempt == retries - 1:
                return aid, f"exc:{type(e).__name__}"
            time.sleep(2 ** attempt)
    return aid, "fail"

def main():
    centers = json.loads(RAW_LIST.read_text())["data"]
    aids = [c["mosad-aid"] for c in centers]
    print(f"total centers: {len(aids)}")

    existing = {p.stem for p in OUT_DIR.glob("*.json")}
    todo = [a for a in aids if str(a) not in existing]
    print(f"already on disk: {len(existing)}; to fetch: {len(todo)}")

    if not todo:
        return

    counts = {"ok":0, "skip":0, "fail":0}
    start = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_one, a): a for a in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            aid, status = fut.result()
            if status == "ok":      counts["ok"] += 1
            elif status == "skip":  counts["skip"] += 1
            else:                   counts["fail"] += 1
            if i % 100 == 0 or i == len(todo):
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                eta  = (len(todo) - i) / rate if rate > 0 else 0
                print(f"  [{i}/{len(todo)}] ok={counts['ok']} fail={counts['fail']} "
                      f"rate={rate:.1f}/s eta={eta/60:.1f}min")

    print(f"done. {counts}")

if __name__ == "__main__":
    main()
