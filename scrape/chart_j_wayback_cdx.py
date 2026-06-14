"""
Chart J — Wayback CDX Bio Recovery (worker-pool, kill-resumable)
-----------------------------------------------------------------
Walks every chabad house website (houses.website) plus chabad.org central
subdomains via the Wayback CDX JSON API. For each domain, queries five
staff-page URL prefixes that commonly hold biographies.

Robustness:
  - Worker pool of N workers pulls from a bounded queue (not 2500 pending tasks).
  - Per CDX call: 25s hard timeout, single retry.
  - Heartbeat every 30s regardless of completion (you always see progress).
  - Cache-first: cached domains are skipped at queue-build time.
  - Every domain writes its index file (even empty) — kill at any point
    is safe; re-run resumes seamlessly.

Usage:
  python3 scrape/chart_j_wayback_cdx.py              # full sweep, resume-aware
  python3 scrape/chart_j_wayback_cdx.py --limit 50   # smoke test
  python3 scrape/chart_j_wayback_cdx.py --workers 6  # tune throughput
"""
import asyncio, json, hashlib, pathlib, sqlite3, argparse, time, sys
from urllib.parse import urlparse
from curl_cffi import requests as crequests

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB   = ROOT / "data/chabad.db"
OUT  = ROOT / "data/raw/searches/bucket_p_wayback_cdx"
OUT.mkdir(parents=True, exist_ok=True)

CDX = "https://web.archive.org/cdx/search/cdx"
PREFIXES = ["staff/*", "about/*", "team/*", "directors/*", "rabbi/*"]
CENTRAL = [
    ("chabad.org",        ["centers/*", "news/*", "about/*"]),
    ("collive.com",       ["*"]),
    ("crownheights.info", ["*"]),
]

# ---------- helpers ----------
def normalize_domain(website: str) -> str | None:
    if not website: return None
    w = website.strip().lower()
    if not w.startswith(("http://","https://")):
        w = "http://" + w
    try:
        host = urlparse(w).netloc
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host if host and "." in host else None

def slug(domain: str) -> str:
    return hashlib.sha256(domain.encode()).hexdigest()[:16]

def cache_path(domain: str) -> pathlib.Path:
    return OUT / f"{slug(domain)}.json"

def load_domains(limit, only) -> list[tuple[str, list[str]]]:
    """Return list of (domain, prefixes_to_query)."""
    if only:
        d = normalize_domain(only) or only
        return [(d, PREFIXES)]
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT website FROM houses WHERE website IS NOT NULL AND website != ''"
    ).fetchall()
    con.close()
    seen = set()
    out = []
    for (w,) in rows:
        d = normalize_domain(w)
        if d and d not in seen:
            seen.add(d)
            out.append((d, PREFIXES))
    out.sort(key=lambda t: t[0])
    if limit:
        out = out[:limit]
    return out + [(d, p) for d, p in CENTRAL if d not in seen]

# ---------- CDX call ----------
def _sync_cdx(domain: str, prefix: str, timeout: int = 25) -> tuple[list[dict], str]:
    """Returns (rows, status). status ∈ {'ok','timeout','http_NNN','exc'}"""
    params = {
        "url": f"{domain}/{prefix}",
        "output": "json",
        "collapse": "urlkey",
        "fl": "original,timestamp,statuscode,mimetype",
        "limit": "5000",
    }
    try:
        r = crequests.get(CDX, params=params, timeout=timeout, impersonate="chrome")
        if r.status_code != 200:
            return [], f"http_{r.status_code}"
        data = r.json()
        if not data or len(data) < 2:
            return [], "ok"
        header, *rows = data
        return [dict(zip(header, row)) for row in rows], "ok"
    except Exception as e:
        et = type(e).__name__
        if "timeout" in et.lower() or "timeout" in str(e).lower():
            return [], "timeout"
        return [], f"exc:{et}"

async def query_cdx(domain: str, prefix: str) -> tuple[list[dict], str]:
    loop = asyncio.get_event_loop()
    rows, status = await loop.run_in_executor(None, _sync_cdx, domain, prefix, 25)
    if status in ("timeout", "exc:ConnectionError"):
        # one retry with longer timeout
        await asyncio.sleep(1.0)
        rows, status = await loop.run_in_executor(None, _sync_cdx, domain, prefix, 40)
    return rows, status

# ---------- worker ----------
async def walk_domain(domain: str, prefixes: list[str], stats: dict):
    fp = cache_path(domain)
    if fp.exists():
        stats["cached"] += 1
        return
    snapshots = []
    seen = set()
    prefix_status = {}
    for prefix in prefixes:
        rows, status = await query_cdx(domain, prefix)
        prefix_status[prefix] = status
        for row in rows:
            url = row.get("original")
            ts  = row.get("timestamp")
            if not url or url in seen:
                continue
            seen.add(url)
            snapshots.append({
                "original_url": url,
                "timestamp": ts,
                "wayback_url": f"https://web.archive.org/web/{ts}/{url}",
                "status_code": row.get("statuscode"),
                "mimetype": row.get("mimetype"),
                "prefix": prefix,
            })
        await asyncio.sleep(0.2)  # polite gap between prefix calls
    out = {
        "domain": domain,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
        "prefix_status": prefix_status,
    }
    # Atomic write: write to tmp then rename
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2))
    tmp.rename(fp)
    stats["written"] += 1
    stats["snapshots"] += len(snapshots)
    if snapshots:
        stats["with_snaps"] += 1

async def worker(name: str, queue: asyncio.Queue, stats: dict):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        domain, prefixes = item
        try:
            await walk_domain(domain, prefixes, stats)
        except Exception as e:
            stats["errors"] += 1
            print(f"  [worker-{name}] {domain}: {type(e).__name__}: {e}", flush=True)
        stats["done"] += 1
        queue.task_done()

async def heartbeat(stats: dict, total: int, interval: int = 20):
    """Print a status line every `interval` seconds regardless of throughput."""
    start = time.time()
    last_done = -1
    stuck_ticks = 0
    while True:
        await asyncio.sleep(interval)
        elapsed = int(time.time() - start)
        done = stats["done"]
        rate = done / max(elapsed, 1)
        eta = int((total - done) / max(rate, 0.01))
        # detect stall
        if done == last_done:
            stuck_ticks += 1
            stall_note = f" STALL_TICKS={stuck_ticks}" if stuck_ticks else ""
        else:
            stuck_ticks = 0
            stall_note = ""
        last_done = done
        print(f"  [hb {elapsed:4d}s] done={done}/{total} "
              f"written={stats['written']} cached={stats['cached']} "
              f"with_snaps={stats['with_snaps']} snaps={stats['snapshots']:,} "
              f"errors={stats['errors']} rate={rate:.1f}/s eta={eta}s{stall_note}",
              flush=True)

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", type=str, default=None)
    ap.add_argument("--workers", type=int, default=6,
                    help="Concurrent worker tasks (default 6 — polite to CDX)")
    ap.add_argument("--heartbeat", type=int, default=20,
                    help="Heartbeat interval in seconds")
    args = ap.parse_args()

    all_jobs = load_domains(args.limit, args.only)
    # Filter resume-aware
    pending = [(d, p) for d, p in all_jobs if not cache_path(d).exists()]
    cached_n = len(all_jobs) - len(pending)
    print(f"[chart-j] total domains: {len(all_jobs)}  cached: {cached_n}  to walk: {len(pending)}", flush=True)
    if not pending:
        print(f"[chart-j] nothing to do — all cached", flush=True)
        return

    queue: asyncio.Queue = asyncio.Queue()
    for job in pending:
        queue.put_nowait(job)
    # poison pills for clean shutdown
    for _ in range(args.workers):
        queue.put_nowait(None)

    stats = {"done": 0, "cached": 0, "written": 0,
             "with_snaps": 0, "snapshots": 0, "errors": 0}

    hb = asyncio.create_task(heartbeat(stats, len(pending), args.heartbeat))
    workers = [asyncio.create_task(worker(f"w{i}", queue, stats))
               for i in range(args.workers)]
    await asyncio.gather(*workers)
    hb.cancel()
    try: await hb
    except asyncio.CancelledError: pass

    print(f"[chart-j] DONE — written={stats['written']} cached={stats['cached']} "
          f"with_snaps={stats['with_snaps']} snapshots={stats['snapshots']:,} "
          f"errors={stats['errors']}", flush=True)
    print(f"[chart-j] index dir: {OUT}", flush=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[chart-j] interrupted — cache is intact, re-run resumes", flush=True)
        sys.exit(130)
