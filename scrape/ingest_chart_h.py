"""
Chart H ingestion: 801 CourtListener hits → live DB.
Token-cheap by design — all judgment work goes to fleet fast workers,
not Claude.

Pipeline:
  1. Load courtlistener_hits.jsonl
  2. Pre-dedup against existing incidents (skip ~80% of work)
  3. Fan out to fleet_batch with one tight prompt per hit, asking for
     strict JSON in the snippet_extracts schema.
  4. Parse responses → snippet_extracts.jsonl
  5. Hand off to load_snippet_extracts.py (existing script does DB writes)

Usage:
  python3 scrape/ingest_chart_h.py            # full run
  python3 scrape/ingest_chart_h.py --limit 20 # smoke
  python3 scrape/ingest_chart_h.py --dry-run  # no DB write
"""
import json, pathlib, sqlite3, asyncio, argparse, subprocess, sys, time

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
# Use the fleet's own venv site-packages so providers (Groq, etc.) resolve
import site
site.addsitedir(str(FLEET / ".venv/lib/python3.10/site-packages"))
from providers import build_providers
from roles import dispatch_role
DB   = ROOT / "data/chabad.db"
HITS = ROOT / "data/courtlistener_hits.jsonl"
OUT  = ROOT / "data/raw/triage/snippet_extracts.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)

PROMPT_TEMPLATE = """You are extracting a structured incident record from a U.S. federal court record metadata blob. The court record mentions Chabad / Lubavitch or a person known to be a Chabad-affiliated rabbi.

INPUT:
- query: {query}
- case_title: {title}
- snippet: {snippet}
- court: {court}
- date_filed: {date_filed}
- nature_of_suit: {nature_of_suit}
- url: {url}

Return STRICTLY ONE LINE of JSON with this exact schema. No prose. No code block.
If the record is NOT actually about Chabad/Lubavitch wrongdoing (e.g. property tax case, civil lawsuit unrelated to misconduct, organization is plaintiff not defendant), return {{"skip": true}}.

Schema:
{{"name": "<full name of perpetrator, or organization name if institutional>",
  "type": "<one of: financial_fraud, tax_evasion, money_laundering, sexual_abuse, assault, cover_up, drug_trafficking, immigration_fraud, insurance_fraud, other>",
  "severity": "<one of: allegation, investigation, charged, indicted, convicted, settled, acquitted>",
  "year": <YYYY int from date_filed, or null>,
  "location": "<court jurisdiction, e.g. 'Eastern District of New York'>",
  "entity": "<chabad house / yeshiva / nonprofit name if identifiable, else null>",
  "summary": "<one sentence describing what the case is about>",
  "source_url": "{url}",
  "source_title": "{title}"}}"""

def already_in_db() -> set[str]:
    """Pre-dedup signal: existing source URLs in the DB."""
    con = sqlite3.connect(DB)
    urls = {r[0] for r in con.execute("SELECT url FROM sources WHERE url IS NOT NULL")}
    con.close()
    return urls

def load_hits(limit: int | None):
    hits = []
    for line in HITS.read_text().splitlines():
        try:
            hits.append(json.loads(line))
        except: pass
    if limit:
        hits = hits[:limit]
    return hits

def build_prompt(hit: dict) -> str:
    return PROMPT_TEMPLATE.format(
        query=(hit.get("query") or "")[:100],
        title=(hit.get("title") or "(no title)")[:120],
        snippet=(hit.get("snippet") or "")[:400],
        court=hit.get("court") or "?",
        date_filed=hit.get("date_filed") or "?",
        nature_of_suit=hit.get("nature_of_suit") or "?",
        url=hit.get("url") or "",
    )

_PROVIDERS = None
def _get_providers():
    global _PROVIDERS
    if _PROVIDERS is None:
        # Load .env from llm-fleet directory
        env_path = FLEET / ".env"
        if env_path.exists():
            import os
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        _PROVIDERS = build_providers()
    return _PROVIDERS

async def fleet_batch_async(prompts: list[str], role: str = "uncensored", max_tokens: int = 280) -> list[str]:
    """Direct in-process fleet call. Retries on API errors (not on parse fails).
    Returns "" for terminal failures so the caller distinguishes them from real text."""
    providers = _get_providers()
    sem = asyncio.Semaphore(6)
    async def one(p):
        async with sem:
            for attempt in range(3):
                r = await dispatch_role(role, p, max_tokens, providers)
                if r.ok and r.text:
                    return r.text
                # API error or empty — back off and retry
                await asyncio.sleep(2 * (attempt + 1))
            return ""  # terminal failure
    return await asyncio.gather(*[one(p) for p in prompts])

def fleet_batch_sync(prompts: list[str], role: str = "uncensored") -> list[str]:
    return asyncio.run(fleet_batch_async(prompts, role=role))

def parse_response(text: str) -> dict | None:
    """Extract JSON from one fleet response."""
    if not text: return None
    # Strip code fences if any
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    # Find first { and last }
    try:
        i = text.index("{")
        j = text.rindex("}") + 1
        return json.loads(text[i:j])
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    hits = load_hits(args.limit)
    print(f"[ingest-h] loaded {len(hits)} CL hits")

    known_urls = already_in_db()
    print(f"[ingest-h] DB already has {len(known_urls)} source URLs")

    fresh = [h for h in hits if h.get("url") and h["url"] not in known_urls]
    print(f"[ingest-h] {len(fresh)} fresh hits to process (skipped {len(hits)-len(fresh)} dupes)")

    if not fresh:
        print("[ingest-h] nothing to do")
        return

    # Open output append-mode so resume works on partial runs
    extracts = []
    skips = 0
    parse_fails = 0
    t0 = time.time()
    for i in range(0, len(fresh), args.batch_size):
        chunk = fresh[i:i+args.batch_size]
        prompts = [build_prompt(h) for h in chunk]
        print(f"[ingest-h] batch {i//args.batch_size+1}/{(len(fresh)+args.batch_size-1)//args.batch_size}  "
              f"({i+1}-{i+len(chunk)} of {len(fresh)})", flush=True)
        responses = fleet_batch_sync(prompts, role="uncensored")
        for hit, resp in zip(chunk, responses):
            parsed = parse_response(resp)
            if not parsed:
                parse_fails += 1
                continue
            if parsed.get("skip"):
                skips += 1
                continue
            # Ensure source_url/title round-trip even if model dropped them
            parsed.setdefault("source_url", hit.get("url"))
            parsed.setdefault("source_title", hit.get("title"))
            extracts.append(parsed)
        elapsed = int(time.time() - t0)
        print(f"  cumulative: {len(extracts)} extracts, {skips} skipped, {parse_fails} parse_fail, {elapsed}s", flush=True)

    print(f"[ingest-h] total: {len(extracts)} extracts, {skips} skipped, {parse_fails} parse_failures")

    if args.dry_run:
        print("[ingest-h] --dry-run: not writing")
        print("Sample extracts (first 3):")
        for e in extracts[:3]:
            print(" ", json.dumps(e)[:250])
        return

    # Append to snippet_extracts.jsonl
    with open(OUT, "a") as f:
        for e in extracts:
            f.write(json.dumps(e) + "\n")
    print(f"[ingest-h] appended {len(extracts)} extracts to {OUT}")

    # Hand off to existing loader
    print(f"[ingest-h] running load_snippet_extracts.py...")
    r = subprocess.run(
        [sys.executable, "scrape/load_snippet_extracts.py"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr[:500])

if __name__ == "__main__":
    main()
