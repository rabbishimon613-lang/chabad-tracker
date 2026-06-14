"""
Phase A — harvest photos from JCW wall-of-shame profiles.
Each profile page has a primary photo of the named subject.
Match name → people.id and store photo_url.
"""
import asyncio, json, pathlib, re, sqlite3
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB = ROOT / "data/chabad.db"
PROFILES = ROOT / "data/raw/jcw/profiles"

def extract_name_and_image(html):
    soup = BeautifulSoup(html, "html.parser")
    # Look for FULL NAME: line in body text
    text = soup.get_text(" ", strip=True)
    m = re.search(r"FULL NAME:\s*([A-Z][A-Z\s\-']+?)(?:\s+LAST KNOWN|\s+ABOUT|\s+AKA|\s{3,}|$)", text)
    if not m: return None, None, None
    name = m.group(1).strip().title()
    # Find largest image not in nav/icons; JCW puts the perp photo in main content
    imgs = soup.find_all("img")
    best = None
    for img in imgs:
        src = img.get("src") or img.get("data-src") or ""
        if not src: continue
        if any(x in src.lower() for x in ["logo","icon","footer","header","banner","sprite"]): continue
        if src.endswith(".svg"): continue
        # Prefer images in /wp-content/ or /uploads/
        score = 0
        if "wp-content" in src or "upload" in src: score += 5
        if any(name.split()[0].lower() in src.lower() for _ in [1]): score += 3
        w = img.get("width"); h = img.get("height")
        try:
            if w and int(w) > 100: score += 2
        except: pass
        if not best or score > best[1]:
            best = (src, score, img.get("alt",""))
    if not best: return name, None, None
    url = best[0]
    if url.startswith("//"): url = "https:" + url
    elif url.startswith("/"): url = "https://www.jewishcommunitywatch.org" + url
    return name, url, best[2]

async def fetch_and_parse(session, profile_url):
    try:
        r = await session.get(profile_url, impersonate="chrome", timeout=25)
        if r.status_code != 200: return None
        return extract_name_and_image(r.text)
    except Exception as e:
        return None

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

async def main():
    con = sqlite3.connect(DB)
    # Load people for name matching
    people = con.execute("SELECT id, full_name FROM people").fetchall()
    by_norm = {}
    for pid, nm in people:
        n = norm(nm)
        by_norm.setdefault(n, []).append((pid, nm))

    profiles = list(PROFILES.glob("*.json"))
    print(f"processing {len(profiles)} JCW profiles")
    async with AsyncSession() as session:
        sem = asyncio.Semaphore(4)
        results = []
        async def one(p):
            async with sem:
                d = json.loads(p.read_text())
                url = d.get("url")
                if not url: return
                out = await fetch_and_parse(session, url)
                if not out: return
                name, img, alt = out
                if not name or not img: return
                results.append((name, img, alt, url))
        tasks = [one(p) for p in profiles]
        done = 0
        for c in asyncio.as_completed(tasks):
            await c; done += 1
            if done % 25 == 0: print(f"  {done}/{len(profiles)}")
        print(f"fetched, got {len(results)} (name, photo) pairs")

    # Match + store
    matched, inserted, skipped = 0, 0, 0
    for name, img, alt, src in results:
        n = norm(name)
        cands = by_norm.get(n, [])
        if len(cands) == 1:
            pid, full = cands[0]
            con.execute("""
              UPDATE people SET photo_url=?, photo_source=?, photo_caption=?,
                                photo_confidence='verified', photo_verified_at=datetime('now')
              WHERE id=?
            """, (img, src, alt or name, pid))
            matched += 1
        elif len(cands) > 1:
            skipped += 1  # ambiguous
        else:
            # Insert new person — JCW wall-of-shame is authoritative
            parts = name.split()
            surname = parts[-1] if parts else ""
            given = " ".join(parts[:-1]) if len(parts) > 1 else ""
            con.execute("""
              INSERT INTO people (full_name, given_name, surname, photo_url, photo_source, photo_caption, photo_confidence, photo_verified_at, notes)
              VALUES (?, ?, ?, ?, ?, ?, 'verified', datetime('now'), 'inserted from JCW wall-of-shame')
            """, (name, given, surname, img, src, alt or name))
            inserted += 1
    con.commit()
    print(f"matched_existing={matched} new_inserted={inserted} skipped_ambiguous={skipped}")
    con.close()

asyncio.run(main())
