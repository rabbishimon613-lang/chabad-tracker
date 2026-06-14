"""
Bucket B — dynasty surname sweep via Tavily (news-indexed).
"""
import json, hashlib, asyncio, sys, dataclasses
from pathlib import Path

sys.path.insert(0, "/Volumes/EOS_DIGITAL/llm-fleet")
import os as _os
for line in open("/Volumes/EOS_DIGITAL/llm-fleet/.env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); _os.environ.setdefault(k,v.strip('"').strip("'"))
from searchers import build_searchers

ROOT = Path("/Volumes/EOS_DIGITAL/chabad-tracker")
OUT = ROOT / "data/raw/searches/bucket_b"
OUT.mkdir(parents=True, exist_ok=True)

DYNASTIES = [
    "Krinsky", "Shemtov", "Cunin", "Lazar", "Gurary", "Hecht", "Raskin",
    "Wilhelm", "Spalter", "Telsner", "Levitin", "Feldman", "Goldstein",
    "Rubashkin", "Kievman", "Sobel", "Charitonov", "Segal", "Engel",
    "Duchman", "Lipskar", "Kotlarsky", "Kantor", "Schochet", "Mintz",
    "Notik", "Bogomilsky", "Schapiro", "Vogel", "Greenberg", "Kalmenson",
    "Lipsker", "Posner", "Heber", "Liberow", "Wineberg", "Plotkin",
    "Holtzberg", "Marlow", "Backman",
]

ANGLES = [
    "arrested OR indicted OR convicted Chabad rabbi",
    "lawsuit OR fraud OR embezzlement Chabad",
    "abuse OR misconduct allegations Chabad",
    "settler violence West Bank Chabad",
]


def build_queries():
    qs = []
    for s in DYNASTIES:
        for a in ANGLES:
            qs.append(f'"{s}" Chabad {a}')
    return qs


async def fire(queries, engine="tavily"):
    s = build_searchers()[engine]
    sem = asyncio.Semaphore(5)

    async def one(q):
        async with sem:
            try:
                res = await s.search(q, max_results=10) if engine == "tavily" else await s.search(q, num_results=10)
                return q, (res.as_dict() if hasattr(res,"as_dict") else res)
            except Exception as e:
                return q, {"error": str(e)}

    done = 0
    tasks = [one(q) for q in queries]
    for coro in asyncio.as_completed(tasks):
        q, res = await coro
        h = hashlib.sha256(q.encode()).hexdigest()[:16]
        out = {"query": q, "engine": engine, "results": res.get("results", []) if isinstance(res,dict) else [], "error": res.get("error") if isinstance(res,dict) else str(res)}
        (OUT / f"{h}.json").write_text(json.dumps(out, indent=2))
        done += 1
        if done % 20 == 0:
            print(f"  [{done}/{len(queries)}]")


def main():
    qs = build_queries()
    print(f"Bucket B: {len(qs)} queries across {len(DYNASTIES)} dynasties × {len(ANGLES)} angles")
    asyncio.run(fire(qs, engine="tavily"))


if __name__ == "__main__":
    main()
