"""
Gentle wayback re-fetcher: 2 concurrent, 300ms gap between requests, retry on 429
with exponential backoff. Only retries URLs from wayback bucket that aren't yet
in the articles/ directory.
"""
import asyncio, json, hashlib, pathlib, time
from curl_cffi import requests as crequests
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
ARTS = ROOT/"data/raw/articles"; ARTS.mkdir(parents=True, exist_ok=True)

# Collect wayback URLs from triage
def wayback_urls():
    urls = []
    for line in open(ROOT/"data/raw/triage/triage.jsonl"):
        try:
            r = json.loads(line)
            if r.get("engine") == "wayback" and r.get("is_chabad_related"):
                urls.append(r["url"])
        except: pass
    return urls

def slug(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]

def already_have(url):
    return (ARTS/f"{slug(url)}.txt").exists()

async def fetch_one(url, sem):
    if already_have(url): return "skip"
    async with sem:
        for attempt in range(3):
            try:
                loop = asyncio.get_event_loop()
                r = await loop.run_in_executor(None,
                    lambda: crequests.get(url, impersonate="chrome", timeout=30))
                if r.status_code == 429:
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                if r.status_code != 200:
                    return f"http_{r.status_code}"
                # extract with trafilatura
                from trafilatura import extract
                text = extract(r.text, include_comments=False) or ""
                if len(text) < 200: return "short"
                (ARTS/f"{slug(url)}.txt").write_text(text)
                await asyncio.sleep(0.3)  # politeness gap
                return "ok"
            except Exception as e:
                await asyncio.sleep(1)
        return "err"

async def main():
    urls = [u for u in wayback_urls() if not already_have(u)]
    print(f"to fetch (gentle): {len(urls)} wayback URLs")
    sem = asyncio.Semaphore(2)
    counts = {"ok":0,"skip":0,"err":0,"short":0}
    done=0
    tasks = [fetch_one(u, sem) for u in urls]
    for c in asyncio.as_completed(tasks):
        r = await c
        if r in counts: counts[r] += 1
        elif r.startswith("http_"): counts["err"] += 1
        else: counts["err"] += 1
        done += 1
        if done % 100 == 0:
            print(f"  {done}/{len(urls)} -> {counts}")
    print(f"final: {counts}")

asyncio.run(main())
