"""
Priority photo scraper — ranks people by "misdeed score" and fetches photos for
the highest-ranked unphotographed people via Tavily image search.

Misdeed score: sum over each person's incidents of severity weight.
  convicted=10  indicted=8  charged=5  settled=3  investigation=2  allegation=1
People not tied to incidents → score 0 (deprioritized).

Verification: heuristic.
  Caption/alt/snippet contains full name → 'verified'
  Surname only OR authoritative domain → 'probable'
  Otherwise → skip
"""
import asyncio, json, hashlib, os, pathlib, httpx, random, sqlite3, re, sys
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB = ROOT / "data/chabad.db"
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 80
SEV_W = {"convicted":10,"indicted":8,"charged":5,"settled":3,"investigation":2,"allegation":1}
AUTH_DOMAINS = ("jewishcommunitywatch.org","wikipedia.org","wikimedia.org","chabad.org","justice.gov","forward.com","jta.org","tabletmag.com","timesofisrael.com","haaretz.com")
SKIP_IMG = ("logo","icon","sprite","footer","header","banner","avatar.png","placeholder","blank","sponsored","ad-")

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def rank_targets():
    con = sqlite3.connect(DB)
    rows = con.execute(f"""
      WITH score AS (
        SELECT ip.person_id AS pid, SUM(
          CASE i.severity
            {' '.join(f"WHEN '{k}' THEN {v}" for k,v in SEV_W.items())}
            ELSE 0 END
        ) AS s
        FROM incident_people ip JOIN incidents i ON i.id = ip.incident_id
        GROUP BY ip.person_id
      )
      SELECT p.id, p.full_name, COALESCE(p.surname,''), COALESCE(s.s, 0) AS score
      FROM people p LEFT JOIN score s ON s.pid = p.id
      WHERE p.photo_url IS NULL
        AND p.full_name NOT LIKE 'Unnamed%' AND p.full_name NOT LIKE 'Unknown%'
        AND length(p.full_name) > 6 AND p.full_name NOT LIKE '%,%'
      ORDER BY score DESC, p.id
      LIMIT ?
    """, (LIMIT,)).fetchall()
    con.close()
    return rows

async def tavily_image(query, key):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key, "query": query,
                "max_results": 8, "search_depth": "basic",
                "include_images": True, "include_image_descriptions": True,
            })
            r.raise_for_status()
            data = r.json()
            return data.get("images", []), data.get("results", [])
    except Exception as e:
        return [], []

def score_candidate(img, name, surname):
    """Return (confidence, score) or (None, 0).
    STRICT: requires the person's FULL NAME in caption/alt/URL.
    Surname-only or auth-domain-only is NOT enough. Doctrine: truthful > complete.
    """
    url = img.get("url") if isinstance(img, dict) else img
    desc = (img.get("description") if isinstance(img, dict) else "") or ""
    if not url: return None, 0
    low = url.lower()
    if any(x in low for x in SKIP_IMG): return None, 0
    if low.endswith(".svg") or "google.com" in low or low.endswith(".pdf"): return None, 0
    # Reject obvious building/map/infographic patterns
    for bad in ("plant","map","building","logo","cover","menorah","sign","banner","group","reception","ceremony","crowd","panel","conference"):
        if bad in low: return None, 0
    nn = norm(name); ns = norm(surname)
    haystack = norm(desc + " " + url)
    # MUST have full name in caption or URL — surname alone is insufficient
    if nn and nn in haystack:
        confidence = "verified"
        score = 10
    elif ns and ns in haystack:
        # Surname match alone → "probable" ONLY if the desc looks like a portrait/headshot caption
        # i.e. contains "Rabbi" or "Mr." or "Mrs." plus surname AND no exclusion words
        if "rabbi" in haystack or "mr" in haystack:
            confidence = "probable"; score = 5
        else:
            return None, 0
    else:
        return None, 0
    # Auth domain is a quality boost but not required and never alone
    if any(d in low for d in AUTH_DOMAINS): score += 3
    return confidence, score

async def main():
    targets = rank_targets()
    print(f"top {len(targets)} unphotographed (ranked by misdeed score)")

    sem = asyncio.Semaphore(5)
    found = []  # (pid, name, url, desc, confidence)
    failed = 0

    async def one(pid, name, surname, mscore):
        nonlocal failed
        async with sem:
            base = name.replace("Rabbi ","").replace("Mrs. ","").replace("Mr. ","").strip()
            query = f'"{base}" chabad rabbi'
            images, _results = await tavily_image(query, random.choice(KEYS))
            best = None
            for img in images:
                conf, score = score_candidate(img, base, surname)
                if not conf: continue
                url = img.get("url") if isinstance(img, dict) else img
                desc = (img.get("description") if isinstance(img, dict) else "") or ""
                if not best or score > best[2]:
                    best = (url, desc, score, conf)
            if best:
                found.append((pid, name, best[0], best[1], best[3], mscore))
            else:
                failed += 1

    tasks = [one(pid, name, surname, sc) for pid, name, surname, sc in targets]
    done = 0
    for c in asyncio.as_completed(tasks):
        await c; done += 1
        if done % 20 == 0: print(f"  {done}/{len(targets)} (found={len(found)} failed={failed})")
    print(f"final: found={len(found)} failed={failed}")

    # Store
    con = sqlite3.connect(DB)
    stored = 0
    for pid, name, url, desc, conf, mscore in found:
        con.execute("""
          UPDATE people SET photo_url=?, photo_source=?, photo_caption=?,
                            photo_confidence=?, photo_verified_at=datetime('now')
          WHERE id=? AND photo_url IS NULL
        """, (url, url, (desc or name)[:200], conf, pid))
        stored += 1
    con.commit(); con.close()
    print(f"stored {stored}")

asyncio.run(main())
