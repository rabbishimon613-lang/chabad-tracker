"""
Phase B step 1 — scrape photos from articles already in our sources table.
For each named perp without a photo, find their incident source URLs, refetch,
scan <img> tags. Match by caption/alt-text containing the name → 'probable'.
Match if image domain is authoritative (jewishcommunitywatch, wikipedia, chabad.org) → 'verified'.
"""
import asyncio, json, pathlib, re, sqlite3
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB = ROOT / "data/chabad.db"
AUTH_DOMAINS = ("jewishcommunitywatch.org","wikipedia.org","wikimedia.org","chabad.org","justice.gov")
SKIP_IMG = ("logo","icon","sprite","footer","header","banner","avatar.png","placeholder","blank")

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def extract_candidate(html, person_name, surname, base_url):
    soup = BeautifulSoup(html, "html.parser")
    n_norm = norm(person_name); s_norm = norm(surname)
    best = None
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src: continue
        if any(x in src.lower() for x in SKIP_IMG): continue
        if src.endswith(".svg"): continue
        if src.startswith("//"): src = "https:" + src
        elif src.startswith("/"):
            from urllib.parse import urljoin
            src = urljoin(base_url, src)
        alt = img.get("alt") or ""
        title = img.get("title") or ""
        # surrounding text from figcaption / parent
        cap = ""
        fig = img.find_parent("figure")
        if fig:
            fc = fig.find("figcaption")
            if fc: cap = fc.get_text(" ", strip=True)
        if not cap:
            # nearby text within ~200 chars
            par = img.find_parent()
            if par: cap = par.get_text(" ", strip=True)[:200]
        haystack = norm(alt + " " + title + " " + cap)
        score = 0
        confidence = None
        if n_norm and n_norm in haystack: score += 10; confidence = "verified"
        elif s_norm and s_norm in haystack: score += 5; confidence = "probable"
        if any(d in src for d in AUTH_DOMAINS): score += 5; confidence = "verified"
        # dimension hint
        w = img.get("width")
        if w and w.isdigit() and int(w) > 200: score += 2
        if score >= 5 and (not best or score > best["score"]):
            best = {"url": src, "caption": (cap or alt or title)[:200], "score": score, "confidence": confidence}
    return best

async def main():
    con = sqlite3.connect(DB)
    rows = con.execute("""
      SELECT DISTINCT p.id, p.full_name, COALESCE(p.surname,'') AS surname
      FROM people p
      JOIN incident_people ip ON ip.person_id = p.id
      WHERE p.photo_url IS NULL
        AND p.full_name NOT LIKE 'Unnamed%' AND p.full_name NOT LIKE 'Unknown%'
        AND length(p.full_name) > 6 AND p.full_name NOT LIKE '%,%'
    """).fetchall()
    print(f"{len(rows)} unphotographed named people tied to incidents")

    # For each person, fetch up to 3 incident source URLs
    plans = []  # (person_id, name, surname, [urls])
    for pid, name, surname in rows:
        urls = [r[0] for r in con.execute("""
          SELECT DISTINCT s.url FROM incident_people ip
          JOIN incident_sources isc ON isc.incident_id = ip.incident_id
          JOIN sources s ON s.id = isc.source_id
          WHERE ip.person_id = ? LIMIT 4
        """, (pid,)).fetchall() if r[0] and r[0].startswith("http")]
        if urls:
            plans.append((pid, name, surname, urls))
    print(f"plans: {len(plans)} people × ~3 URLs each")
    con.close()

    # Fetch and parse
    sem = asyncio.Semaphore(6)
    found = []
    async with AsyncSession() as session:
        async def one(pid, name, surname, urls):
            for url in urls:
                async with sem:
                    try:
                        r = await session.get(url, impersonate="chrome", timeout=25)
                        if r.status_code != 200: continue
                        cand = extract_candidate(r.text, name, surname, url)
                        if cand:
                            found.append((pid, name, cand, url))
                            return
                    except Exception:
                        continue
        tasks = [one(*p) for p in plans]
        done = 0
        for c in asyncio.as_completed(tasks):
            await c; done += 1
            if done % 20 == 0: print(f"  {done}/{len(plans)} processed, {len(found)} found")

    print(f"final: {len(found)} candidate photos")

    # Store
    con = sqlite3.connect(DB)
    inserted = 0
    for pid, name, cand, src in found:
        con.execute("""
          UPDATE people SET photo_url=?, photo_source=?, photo_caption=?,
                            photo_confidence=?, photo_verified_at=datetime('now')
          WHERE id=? AND photo_url IS NULL
        """, (cand["url"], src, cand["caption"], cand["confidence"], pid))
        inserted += 1
    con.commit(); con.close()
    print(f"stored {inserted}")

asyncio.run(main())
