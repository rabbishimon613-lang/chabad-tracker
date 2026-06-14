"""
Fetch full text of: all chabad-related URLs from triage + all Grok-cited URLs.
Saves cleaned article text (via trafilatura) to data/raw/articles/{hash}.txt
plus a sidecar {hash}.meta.json with url + title + length.

Skips PDFs (logs URL for separate handling).
Resume-safe.
"""
import asyncio, json, hashlib, pathlib, sys, time
from urllib.parse import urlparse

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))

from curl_cffi import requests as crequests
import trafilatura

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "raw" / "articles"
OUT.mkdir(parents=True, exist_ok=True)
PDF_LOG = OUT / "_pdfs.txt"

def url_hash(u: str) -> str:
    return hashlib.sha1(u.encode()).hexdigest()[:16]

def collect_urls():
    urls = []
    # 1) triage chabad-related
    triage = ROOT / "data/raw/triage/triage.jsonl"
    for line in triage.open():
        r = json.loads(line)
        if r.get("is_chabad_related") and r.get("url"):
            urls.append((r["url"], r.get("title","")))
    # 2) Grok-cited URLs
    for b in sorted((ROOT/"data/raw/grok").glob("batch*.json")):
        for inc in json.loads(b.read_text()):
            for s in inc.get("sources") or []:
                u = s.get("url")
                if u: urls.append((u, inc.get("perpetrator_name","")))
    # dedupe by URL, keep first title
    seen, uniq = set(), []
    for u,t in urls:
        if u in seen: continue
        seen.add(u); uniq.append((u,t))
    return uniq


async def fetch_one(url: str, title: str):
    h = url_hash(url)
    out_txt  = OUT / f"{h}.txt"
    out_meta = OUT / f"{h}.meta.json"
    if out_txt.exists():
        return "skip"
    # PDF? skip + log
    if url.lower().endswith(".pdf") or "/pdf/" in url.lower():
        with PDF_LOG.open("a") as f:
            f.write(f"{url}\n")
        return "pdf"
    try:
        # blocking, run in executor
        r = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: crequests.get(url, impersonate="chrome", timeout=20)
        )
        if r.status_code != 200:
            out_meta.write_text(json.dumps({"url": url, "status": r.status_code, "title": title}))
            return f"http{r.status_code}"
        # Extract main article text
        text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
        if not text or len(text) < 200:
            # fallback to raw text strip
            text = (text or "").strip() or r.text[:5000]
        out_txt.write_text(text)
        out_meta.write_text(json.dumps({
            "url": url, "title": title, "status": 200,
            "len": len(text), "fetched_at": time.time(),
        }))
        return "ok"
    except Exception as e:
        out_meta.write_text(json.dumps({"url": url, "error": str(e), "title": title}))
        return f"err:{type(e).__name__}"


async def main():
    urls = collect_urls()
    print(f"to fetch: {len(urls)} unique URLs")

    sem = asyncio.Semaphore(6)
    counts = {"ok":0,"skip":0,"pdf":0,"http":0,"err":0}

    async def runner(u,t):
        async with sem:
            r = await fetch_one(u, t)
        bucket = "ok" if r=="ok" else "skip" if r=="skip" else "pdf" if r=="pdf" else "http" if r.startswith("http") else "err"
        counts[bucket] += 1

    t0 = time.time()
    await asyncio.gather(*[runner(u,t) for u,t in urls])
    print(f"done in {time.time()-t0:.1f}s. {counts}")
    print(f"-> {OUT}")

asyncio.run(main())
