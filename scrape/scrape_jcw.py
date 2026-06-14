"""
JCW Wall of Justice scraper. Pre-identified Orthodox abusers; many Chabad-affiliated.
Pulls the index, fetches each profile, saves raw HTML + parsed JSON.
Triage step downstream filters to Chabad-affiliated entries only.
"""
import json, hashlib, asyncio, sys
from pathlib import Path
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

ROOT = Path("/Volumes/EOS_DIGITAL/chabad-tracker")
OUT = ROOT / "data/raw/jcw"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "profiles").mkdir(exist_ok=True)

INDEX_URLS = ["https://www.jewishcommunitywatch.org/wall-of-shame-gallery"]


async def fetch(s, url):
    try:
        r = await s.get(url, impersonate="chrome", timeout=30)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def parse_profile_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/wall-of-shame/" in href and "gallery" not in href and "contact" not in href:
            links.add(href.split("?")[0].split("#")[0])
    return links


def parse_profile(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("h1") or soup.find("title"))
    title = title.get_text(strip=True) if title else ""
    body = soup.find("article") or soup.find("main") or soup
    text = body.get_text("\n", strip=True)
    return {"url": url, "title": title, "text": text[:20000]}


async def main():
    async with AsyncSession() as s:
        all_links = set()
        for u in INDEX_URLS:
            code, html = await fetch(s, u)
            print(f"index {u} -> {code} ({len(html)} bytes)")
            if code == 200:
                all_links |= parse_profile_links(html)
        print(f"Found {len(all_links)} profile links")
        (OUT / "index_links.json").write_text(json.dumps(sorted(all_links), indent=2))

        sem = asyncio.Semaphore(4)
        async def one(url):
            async with sem:
                h = hashlib.sha256(url.encode()).hexdigest()[:16]
                p = OUT / "profiles" / f"{h}.json"
                if p.exists():
                    return
                code, html = await fetch(s, url)
                if code == 200:
                    p.write_text(json.dumps(parse_profile(html, url), indent=2))
                return code

        results = await asyncio.gather(*[one(u) for u in all_links])
        ok = sum(1 for r in results if r == 200)
        print(f"Fetched {ok}/{len(all_links)} profiles")


if __name__ == "__main__":
    asyncio.run(main())
