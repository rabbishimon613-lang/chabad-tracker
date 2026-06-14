"""
Download every people.photo_url into ui/public/photos/{person_id}.{ext}
and update people.photo_local_url so the UI serves from our own host.
Keeps photo_source as the original URL for attribution.
"""
import asyncio, pathlib, sqlite3, mimetypes
from curl_cffi.requests import AsyncSession

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB  = ROOT / "data/chabad.db"
OUT = ROOT / "ui/public/photos"; OUT.mkdir(parents=True, exist_ok=True)

def ext_from(url, content_type):
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".jpg"
        if ext == ".jpe": ext = ".jpg"
        return ext
    # fallback from URL
    low = url.lower().split("?")[0]
    for e in (".jpg",".jpeg",".png",".webp",".gif"):
        if low.endswith(e): return e
    return ".jpg"

async def main():
    con = sqlite3.connect(DB)
    # add column if missing
    cols = [r[1] for r in con.execute("PRAGMA table_info(people)").fetchall()]
    if "photo_local_url" not in cols:
        con.execute("ALTER TABLE people ADD COLUMN photo_local_url TEXT")
        con.commit()
    rows = con.execute("""
      SELECT id, photo_url FROM people
      WHERE photo_url IS NOT NULL AND (photo_local_url IS NULL OR photo_local_url='')
    """).fetchall()
    print(f"to download: {len(rows)}")

    sem = asyncio.Semaphore(5)
    updates = []
    failed = 0
    async with AsyncSession() as s:
        async def one(pid, url):
            nonlocal failed
            async with sem:
                try:
                    r = await s.get(url, impersonate="chrome", timeout=30)
                    if r.status_code != 200 or len(r.content) < 500:
                        failed += 1; return
                    ext = ext_from(url, r.headers.get("content-type",""))
                    fp = OUT / f"{pid}{ext}"
                    fp.write_bytes(r.content)
                    updates.append((f"photos/{pid}{ext}", pid))
                except Exception:
                    failed += 1
        tasks = [one(pid, url) for pid, url in rows]
        done = 0
        for c in asyncio.as_completed(tasks):
            await c; done += 1
            if done % 50 == 0: print(f"  {done}/{len(rows)} (failed={failed})")
    print(f"final: ok={len(updates)} failed={failed}")
    for path, pid in updates:
        con.execute("UPDATE people SET photo_local_url=? WHERE id=?", (path, pid))
    con.commit(); con.close()
    print(f"DB updated for {len(updates)} people")

asyncio.run(main())
