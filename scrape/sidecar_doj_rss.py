"""
sidecar_doj_rss.py
-------------------
Monitors DOJ + FBI press release feeds for Chabad/Lubavitch mentions.
Checks RSS/sitemap feeds. Pure HTTP, no API keys needed.
Adds new cases directly to snippet_extracts.jsonl for loading.

Run every cycle as a sidecar — fast, authoritative, real-time.
"""
import urllib.request, json, pathlib, re, datetime, xml.etree.ElementTree as ET

ROOT     = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
EXTRACTS = ROOT / "data/raw/triage/snippet_extracts.jsonl"
LOG      = ROOT / "data/dragnet_log.jsonl"

FEEDS = [
    ("DOJ", "https://www.justice.gov/feeds/opa/justice-news.xml"),
    ("FBI", "https://www.fbi.gov/feeds/fbi_news.rss"),
    ("USAO-SDNY", "https://www.justice.gov/usao-sdny/rss"),
    ("USAO-NJ",   "https://www.justice.gov/usao-nj/rss"),
    ("USAO-EDNY", "https://www.justice.gov/usao-edny/rss"),
    ("USAO-CDCA", "https://www.justice.gov/usao-cdca/rss"),  # Los Angeles
]

CHABAD_KEYWORDS = [
    "chabad","lubavitch","yeshivah","yeshiva","agriprocessors",
    "oholei torah","770 eastern","crown heights rabbi",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (research bot)"}

def fetch_feed(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None

def parse_feed(xml_str):
    """Returns list of {title, link, description, pubDate}"""
    items = []
    try:
        root = ET.fromstring(xml_str)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # RSS
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            desc  = (item.findtext("description") or "").strip()
            date  = (item.findtext("pubDate") or "").strip()
            items.append({"title":title,"link":link,"desc":desc,"date":date})
        # Atom
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title",namespaces=ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            link = (link_el.get("href","") if link_el is not None else "").strip()
            desc = (entry.findtext("atom:summary",namespaces=ns) or "").strip()
            date = (entry.findtext("atom:updated",namespaces=ns) or "").strip()
            items.append({"title":title,"link":link,"desc":desc,"date":date})
    except: pass
    return items

# Load existing sources to avoid dupes
existing_urls = set()
import sqlite3
con = sqlite3.connect(ROOT / "data/chabad.db")
for r in con.execute("SELECT url FROM sources WHERE url IS NOT NULL"):
    existing_urls.add(r[0])

# Load existing summaries
seen_summaries = set()
if EXTRACTS.exists():
    for line in EXTRACTS.read_text().splitlines():
        try:
            r = json.loads(line)
            seen_summaries.add((r.get("summary","")[:80]).lower().strip())
        except: pass

now = datetime.datetime.utcnow().isoformat()
new_cases = []
new_sources = []

for source_name, feed_url in FEEDS:
    xml_str = fetch_feed(feed_url)
    if not xml_str: continue
    items = parse_feed(xml_str)

    for item in items:
        text = f"{item['title']} {item['desc']}".lower()
        if not any(kw in text for kw in CHABAD_KEYWORDS): continue

        url = item["link"]
        if url in existing_urls: continue
        existing_urls.add(url)

        # Extract year from date
        year = None
        m = re.search(r'20\d\d', item["date"])
        if m: year = int(m.group(0))

        # Infer type + severity from title
        title_lower = item["title"].lower()
        inc_type = "financial_fraud"
        if any(w in title_lower for w in ["sex","abuse","assault","molest"]): inc_type = "sexual_abuse"
        elif any(w in title_lower for w in ["launder","money"]): inc_type = "money_laundering"
        elif any(w in title_lower for w in ["tax","evasion"]): inc_type = "tax_evasion"
        elif any(w in title_lower for w in ["drug","narcotic"]): inc_type = "drug_trafficking"

        severity = "allegation"
        if any(w in title_lower for w in ["convicted","guilty","sentenced","conviction"]): severity = "convicted"
        elif any(w in title_lower for w in ["indicted","indictment","charged","arraigned"]): severity = "charged"
        elif any(w in title_lower for w in ["arrested","arrest"]): severity = "charged"

        summary = f"{item['title']}. {item['desc'][:300]}".strip()
        key = summary[:80].lower().strip()
        if key in seen_summaries: continue
        seen_summaries.add(key)

        case = {
            "name": "",  # will be extracted by load script if possible
            "summary": summary,
            "type": inc_type,
            "severity": severity,
            "year": year,
            "location": "USA",
            "entity": "",
            "source_url": url,
            "source": source_name,
        }
        new_cases.append(case)

        # Also add to sources table
        con.execute("INSERT OR IGNORE INTO sources (url,title,accessed_at,type,outlet) VALUES (?,?,?,'court',?)",
            (url, item["title"][:200], now, source_name))
        new_sources.append(url)
        print(f"  [{source_name}] {item['title'][:80]}")

con.commit()

# Append to snippet_extracts.jsonl
if new_cases:
    with open(EXTRACTS, "a") as f:
        for c in new_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

print(f"\nDOJ/FBI RSS: {len(new_cases)} new cases found, {len(new_sources)} sources added")
