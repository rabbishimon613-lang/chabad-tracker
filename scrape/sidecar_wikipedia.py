"""
sidecar_wikipedia.py
---------------------
Traverses Wikipedia articles related to Chabad scandals.
Extracts: external links (→ new sources), cited cases, named people.
Follows links to related articles up to 1 hop deep.

Pure HTTP — no API keys. Uses Wikipedia API.
"""
import urllib.request, urllib.parse, json, pathlib, re, sqlite3, datetime, time

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB   = ROOT / "data/chabad.db"
con  = sqlite3.connect(DB)
now  = datetime.datetime.utcnow().isoformat()

SEED_ARTICLES = [
    "Agriprocessors",
    "Sholom_Rubashkin",
    "Chabad-Lubavitch",
    "Yeshivah_Centre_Melbourne",
    "David_Cyprys",
    "Spinka_rebbe",
    "Milton_Balkany",
    "Mendel_Epstein",
    "770_Eastern_Parkway",
    "Poway_synagogue_shooting",  # will filter out victim angle
    "Operation_Bid_Rig",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (research)"}

def wiki_links(title):
    """Get all external links from a Wikipedia article"""
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={urllib.parse.quote(title)}&prop=extlinks&ellimit=100&format=json"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        pages = data.get("query",{}).get("pages",{})
        links = []
        for page in pages.values():
            for el in page.get("extlinks",[]):
                links.append(el.get("*",""))
        return links
    except: return []

def wiki_text(title):
    """Get plain text extract of article"""
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={urllib.parse.quote(title)}&prop=extracts&exintro=1&explaintext=1&format=json"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        pages = data.get("query",{}).get("pages",{})
        for page in pages.values():
            return page.get("extract","")
    except: return ""

def wiki_related(title):
    """Get linked Wikipedia articles"""
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={urllib.parse.quote(title)}&prop=links&pllimit=50&plnamespace=0&format=json"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        pages = data.get("query",{}).get("pages",{})
        links = []
        for page in pages.values():
            for l in page.get("links",[]):
                links.append(l["title"])
        return links
    except: return []

SKIP_DOMAINS = {"facebook.com","twitter.com","instagram.com","google.com","amazon.com","youtube.com"}
CHABAD_RELEVANCE = ["chabad","lubavitch","rabbi","yeshiva","fraud","convicted","abuse","sentenced"]

existing_urls = {r[0] for r in con.execute("SELECT url FROM sources WHERE url IS NOT NULL")}
new_sources = 0
new_citations = []

for article in SEED_ARTICLES:
    print(f"\nProcessing: {article}")

    # Get external links (these are citations / sources)
    ext_links = wiki_links(article)
    for url in ext_links:
        if not url.startswith("http"): continue
        domain = urllib.parse.urlparse(url).netloc.replace("www.","")
        if any(d in domain for d in SKIP_DOMAINS): continue
        if url in existing_urls: continue
        existing_urls.add(url)

        # Add to sources
        con.execute("INSERT OR IGNORE INTO sources (url,title,accessed_at,type,tags) VALUES (?,?,?,'court','wikipedia-citation')",
            (url, f"[Wikipedia:{article}]", now))
        new_sources += 1

    # Get article text — extract names and amounts
    text = wiki_text(article)
    if text:
        # Extract dollar amounts
        amounts = re.findall(r'\$[\d,]+(?:\.\d+)?\s*(?:million|billion)?', text, re.I)
        # Extract prison terms
        prison = re.findall(r'[\d]+\s+years?\s+(?:in\s+)?(?:prison|jail|custody)', text, re.I)
        # Extract proper names (potential new people)
        names = re.findall(r'\b(?:Rabbi |Mr\. |Mrs\. )?[A-Z][a-z]+ [A-Z][a-z]+\b', text)
        names = [n for n in names if not any(skip in n for skip in ["New York","United States","Supreme Court","Federal Bureau"])]

        if amounts or prison:
            print(f"  Amounts: {amounts[:3]}  Prison: {prison[:3]}")

    # Discover related articles for next hop
    related = wiki_related(article)
    chabad_related = [r for r in related if any(kw in r.lower() for kw in ["chabad","lubavitch","rabbi","yeshiva","agriprocessors"])]
    if chabad_related:
        print(f"  Related Chabad articles: {chabad_related[:5]}")
        # Queue them (save for next run)
        queue_file = ROOT / "data/wikipedia_queue.json"
        existing_queue = json.loads(queue_file.read_text()) if queue_file.exists() else []
        for r in chabad_related:
            if r not in existing_queue and r not in SEED_ARTICLES:
                existing_queue.append(r)
        queue_file.write_text(json.dumps(existing_queue[:100], indent=2))

    time.sleep(0.5)

con.commit()
print(f"\nWikipedia sweep: +{new_sources} sources from {len(SEED_ARTICLES)} articles")

# Check if there's a queue from previous runs to process
queue_file = ROOT / "data/wikipedia_queue.json"
if queue_file.exists():
    q = json.loads(queue_file.read_text())
    print(f"Wikipedia queue for next run: {len(q)} articles")
