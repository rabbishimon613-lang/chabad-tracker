"""
One-shot: open chabad.org's center finder for a zip code, log every network
request the page makes, dump them to /tmp/sniff.json. Used to discover the
underlying API endpoint(s) so we can drop Playwright afterward.
"""
import json, asyncio, sys
from playwright.async_api import async_playwright

ZIP = sys.argv[1] if len(sys.argv) > 1 else "10065"
OUT = "/tmp/sniff.json"

async def main():
    requests_log = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ))
        page = await ctx.new_page()

        async def on_response(resp):
            url = resp.url
            ct  = (resp.headers or {}).get("content-type","")
            # Filter out images/css/fonts/static — keep XHR-ish things
            if any(s in url for s in (".png",".jpg",".svg",".css",".woff",".gif",".ico")):
                return
            entry = {"url": url, "status": resp.status, "ct": ct}
            try:
                if "json" in ct or "javascript" in ct or url.endswith(".js") is False:
                    body = await resp.text()
                    entry["body_head"] = body[:400]
                    entry["body_len"]  = len(body)
            except Exception as e:
                entry["err"] = str(e)
            requests_log.append(entry)

        page.on("response", on_response)

        # Hit the results URL directly (type=2 = text/zip search per JS)
        await page.goto(f"https://www.chabad.org/jewish-centers/location/2-{ZIP}",
                        wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)
        await browser.close()

    with open(OUT,"w") as f:
        json.dump(requests_log, f, indent=2)
    print(f"logged {len(requests_log)} responses -> {OUT}")

asyncio.run(main())
