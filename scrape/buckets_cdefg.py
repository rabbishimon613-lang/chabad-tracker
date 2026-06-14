"""
Buckets C, D, E, F, G — exhaustive sweep.
C: Regional/geographic
D: Institutional (770, Aguch, Merkos, yeshivas, camps)
E: Primary sources (court, justia, courtlistener)
F: High-severity per-person deep dive
G: Outlet-targeted (VIN, Forward, FailedMessiah, YWN, Times of Israel)
"""
import json, hashlib, asyncio, sys
from pathlib import Path

sys.path.insert(0, "/Volumes/EOS_DIGITAL/llm-fleet")
import os
for line in open("/Volumes/EOS_DIGITAL/llm-fleet/.env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from searchers import build_searchers

ROOT = Path("/Volumes/EOS_DIGITAL/chabad-tracker")

# ------- Bucket C: regional -------
REGIONS = [
    "Crown Heights Brooklyn", "Borough Park Brooklyn", "Pico-Robertson Los Angeles",
    "Postville Iowa", "Kfar Chabad Israel", "West Bank settlement", "Hebron Chabad",
    "Moscow Chabad", "Berlin Chabad", "Paris Chabad", "Buenos Aires Chabad",
    "Sao Paulo Chabad", "Melbourne Chabad", "London Chabad", "Toronto Chabad",
    "Montreal Chabad", "Miami Chabad", "Bangkok Chabad", "Mumbai Chabad",
    "Kathmandu Chabad", "Kiev Chabad", "Tel Aviv Chabad",
]
C_ANGLES = [
    "rabbi arrested OR indicted OR convicted",
    "Chabad lawsuit OR fraud OR embezzlement",
    "Chabad abuse OR misconduct OR cover-up",
    "Chabad settlement OR violence OR assault",
]
def bucket_c():
    return [f"{r} {a}" for r in REGIONS for a in C_ANGLES]

# ------- Bucket D: institutional -------
INSTITUTIONS = [
    "770 Eastern Parkway", "Agudas Chasidei Chabad", "Merkos L'Inyonei Chinuch",
    "Machne Israel", "Oholei Torah yeshiva", "Hadar HaTorah", "Beis Rivkah",
    "Bais Chana", "Chabad on Campus", "Aleph Institute prisons",
    "Friendship Circle", "Chabad House Bangkok", "Mayanot Israel",
    "Tzfat Chabad yeshiva", "Kingston Lubavitcher Yeshiva",
    "Ohel Chabad Lubavitch", "Jewish Children's Museum",
    "Tzivos Hashem", "Chabad Lubavitch Headquarters",
]
D_ANGLES = [
    "lawsuit OR investigation OR indictment",
    "abuse OR scandal OR misconduct",
    "fraud OR embezzlement OR tax evasion",
    "cover-up OR obstruction",
]
def bucket_d():
    return [f'"{i}" {a}' for i in INSTITUTIONS for a in D_ANGLES]

# ------- Bucket E: primary sources via Exa neural with domain hints -------
LEGAL_SEEDS = [
    "Chabad of Poway", "Chabad West Coast Headquarters Cunin",
    "Sholom Rubashkin Agriprocessors", "Yosef Aharonov Israel",
    "Yisroel Goldstein Chabad Poway", "Chabad Hancock Park",
    "Friends of Lubavitch Maryland", "Chabad Lubavitch Russia",
    "Mendy Levy Australia", "Mendel Levertov Chabad",
    "Aron Tendler California", "Yehuda Kolko abuse",
    "Eliyahu Brog Brooklyn", "Avrohom Mondrowitz",
]
E_ANGLES = [
    "court docket OR indictment OR complaint",
    "SEC filing OR DOJ press release",
    "appellate decision OR settlement agreement",
    "criminal information OR plea agreement",
]
def bucket_e():
    return [f"{s} {a}" for s in LEGAL_SEEDS for a in E_ANGLES]

# ------- Bucket F: per-person tier-1 deep dive -------
TIER1_PEOPLE = [
    "Boruch Shlomo Cunin", "Yisroel Goldstein Poway", "Sholom Mordechai Rubashkin",
    "Berel Lazar Russia", "Yossi Engel embezzlement",
    "Tuvia Teldon Long Island", "Mendel Notik",
    "Levi Notik Chabad", "Yossi Naparstek",
    "Aaron Schochet Chabad", "Mendy Kotlarsky",
    "Avraham Berkowitz", "Aron Cohen Chabad",
    "Boruch Wolf settler", "Yitzchak Yehuda Yaroslavsky",
    "Mendel Charitonov", "Joshua Pinson abuse",
    "Yosef Yitzchak Wineberg", "Berel Mochkin",
    "Mendy Vogel Chabad", "Yossi Spritzer",
]
F_ANGLES = [
    "lawsuit indictment conviction",
    "abuse allegation cover-up",
    "fraud embezzlement scheme",
    "court records",
]
def bucket_f():
    return [f'"{p}" {a}' for p in TIER1_PEOPLE for a in F_ANGLES]

# ------- Bucket G: outlet-targeted -------
OUTLETS = ["site:failedmessiah.com", "site:vinnews.com", "site:forward.com",
           "site:theyeshivaworld.com", "site:timesofisrael.com",
           "site:jewishpress.com", "site:jta.org", "site:tabletmag.com"]
G_KEYWORDS = ["Chabad fraud", "Chabad abuse", "Chabad lawsuit",
              "Lubavitcher arrested", "Chabad rabbi convicted",
              "Chabad cover-up", "Lubavitcher indicted"]
def bucket_g():
    return [f"{o} {k}" for o in OUTLETS for k in G_KEYWORDS]


BUCKETS = {"c": (bucket_c, "tavily"), "d": (bucket_d, "tavily"),
           "e": (bucket_e, "exa"),    "f": (bucket_f, "tavily"),
           "g": (bucket_g, "tavily")}


async def fire(name, qbuilder, engine):
    out = ROOT / f"data/raw/searches/bucket_{name}"
    out.mkdir(parents=True, exist_ok=True)
    s = build_searchers()[engine]
    qs = qbuilder()
    print(f"== Bucket {name.upper()} ({engine}): {len(qs)} queries ==")
    sem = asyncio.Semaphore(5)

    async def one(q):
        async with sem:
            try:
                res = (await s.search(q, max_results=10) if engine == "tavily"
                       else await s.search(q, num_results=10))
                d = res.as_dict() if hasattr(res, "as_dict") else res
            except Exception as e:
                d = {"results": [], "error": str(e)}
            h = hashlib.sha256(q.encode()).hexdigest()[:16]
            payload = {"query": q, "engine": engine,
                       "results": d.get("results", []) if isinstance(d, dict) else [],
                       "error": d.get("error") if isinstance(d, dict) else None}
            (out / f"{h}.json").write_text(json.dumps(payload, indent=2))

    done = 0
    tasks = [one(q) for q in qs]
    for c in asyncio.as_completed(tasks):
        await c
        done += 1
        if done % 25 == 0: print(f"  [{name}] {done}/{len(qs)}")


async def main():
    for name, (qb, eng) in BUCKETS.items():
        await fire(name, qb, eng)


if __name__ == "__main__":
    asyncio.run(main())
