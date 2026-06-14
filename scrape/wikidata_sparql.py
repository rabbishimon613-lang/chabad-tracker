"""
Wikidata SPARQL — pull structured records of Chabad-affiliated people with
criminal convictions or notable controversies. Emits a bucket file the triage
pipeline can pick up via the linked Wikipedia article URLs.
"""
import json, pathlib, httpx
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
OUT = ROOT/"data/raw/searches/bucket_q_wikidata"; OUT.mkdir(parents=True, exist_ok=True)

SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent":"chabad-tracker/0.2 (research)","Accept":"application/sparql-results+json"}

# Query 1: people who are Chabad rabbis OR work for Chabad-affiliated org, AND have any of:
#   - convicted of (P1399)
#   - charged with (also via P1399)
#   - cause of death = murdered / executed (long shot)
#   - manner of death = homicide
# OR have a sub-statement about controversy
Q_CRIMINAL = """
SELECT DISTINCT ?person ?personLabel ?article ?crime ?crimeLabel ?date ?country ?countryLabel WHERE {
  {
    ?person wdt:P140 wd:Q170028 .  # religion = Chabad-Lubavitch
  } UNION {
    ?person wdt:P39 ?pos .
    ?pos rdfs:label ?posLabel filter(contains(lcase(?posLabel),"chabad") || contains(lcase(?posLabel),"lubavitch"))
  } UNION {
    ?person wdt:P108 ?emp .
    ?emp rdfs:label ?empLabel filter(contains(lcase(?empLabel),"chabad") || contains(lcase(?empLabel),"lubavitch"))
  } UNION {
    ?person wdt:P166 wd:Q1462336 .  # award given by Chabad org (proxy)
  }
  ?person wdt:P1399 ?crime .          # convicted of
  OPTIONAL { ?person wdt:P27 ?country }
  OPTIONAL { ?article schema:about ?person ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 200
"""

# Query 2: Wikipedia articles in the Chabad-Lubavitch category that mention "controversy/lawsuit/arrest"
# (We can't do a content search via SPARQL — but we can list members of relevant categories,
# then triage their Wikipedia URLs as candidate sources.)
Q_CATEGORY = """
SELECT DISTINCT ?person ?personLabel ?article WHERE {
  {
    ?person wdt:P140 wd:Q170028 .              # Chabad-Lubavitch religion
  } UNION {
    ?person wdt:P39 wd:Q3251884 .               # position: Chabad shliach
  } UNION {
    ?person wdt:P106 wd:Q44324 .                # occupation: rabbi
    ?person wdt:P140 wd:Q170028 .
  }
  ?article schema:about ?person ;
           schema:isPartOf <https://en.wikipedia.org/> .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 400
"""

def fetch(query, label):
    r = httpx.get(SPARQL, params={"query": query}, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    rows = data.get("results",{}).get("bindings",[])
    print(f"  {label}: {len(rows)} rows")
    return rows

def main():
    results = []
    seen_urls = set()
    try:
        for row in fetch(Q_CRIMINAL, "criminal"):
            person = row.get("personLabel",{}).get("value","")
            crime  = row.get("crimeLabel",{}).get("value","")
            article = row.get("article",{}).get("value")
            if not article or article in seen_urls: continue
            seen_urls.add(article)
            results.append({
                "title": f"Wikidata: {person} — convicted of {crime}",
                "url": article,
                "snippet": f"Wikidata entry: {person}, convicted of {crime}",
            })
    except Exception as e:
        print(f"  criminal query failed: {e}")

    try:
        for row in fetch(Q_CATEGORY, "category"):
            person = row.get("personLabel",{}).get("value","")
            article = row.get("article",{}).get("value")
            if not article or article in seen_urls: continue
            seen_urls.add(article)
            results.append({
                "title": f"Wikipedia article: {person}",
                "url": article,
                "snippet": f"Wikipedia article on Chabad-affiliated person {person} — triage for controversy section",
            })
    except Exception as e:
        print(f"  category query failed: {e}")

    payload = {"query":"wikidata_sparql_sweep","engine":"wikidata","results":results}
    (OUT/"index.json").write_text(json.dumps(payload, indent=2))
    print(f"wrote {len(results)} URLs to {OUT/'index.json'}")

main()
