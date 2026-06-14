"""
Bucket I — structural sweep. No hallucinated names. Year × jurisdiction × crime type × Chabad/Lubavitch.
Targets gaps the existing corpus hasn't covered.
"""
import asyncio, json, hashlib, sys, pathlib, itertools
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet"); sys.path.insert(0, str(FLEET))
import os
for line in open(FLEET / ".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from searchers import build_searchers

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")

YEARS = [str(y) for y in range(1995, 2026)]
JURIS = [
    "New York","Brooklyn","New Jersey","Florida","California","Illinois","Massachusetts",
    "Israel","Australia Melbourne","UK London","France Paris","Russia Moscow","Ukraine",
    "Argentina Buenos Aires","Canada Toronto","South Africa Johannesburg",
]
CRIMES = [
    "child sexual abuse conviction Chabad rabbi",
    "Chabad fraud indictment",
    "Lubavitch embezzlement",
    "Chabad cover-up lawsuit",
    "Lubavitch rabbi arrested",
    "Chabad mosdos financial scandal",
]

def build():
    q=[]
    # year × crime (broad temporal)
    for y,c in itertools.product(YEARS[-12:], CRIMES):
        q.append(f"{c} {y}")
    # juris × crime
    for j,c in itertools.product(JURIS, CRIMES[:3]):
        q.append(f"{c} {j}")
    return list(dict.fromkeys(q))

async def main():
    qs = build()
    out = ROOT/"data/raw/searches/bucket_i"; out.mkdir(parents=True, exist_ok=True)
    s = build_searchers()["tavily"]
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem:
            try:
                res = await s.search(q, max_results=10)
                d = res.as_dict() if hasattr(res,"as_dict") else res
            except Exception as e:
                d = {"results":[], "error":str(e)}
            h = hashlib.sha256(q.encode()).hexdigest()[:16]
            payload={"query":q,"engine":"tavily","results":d.get("results",[]) if isinstance(d,dict) else [],"error":d.get("error") if isinstance(d,dict) else None}
            (out/f"{h}.json").write_text(json.dumps(payload,indent=2))
    print(f"firing {len(qs)} structural queries")
    tasks=[one(q) for q in qs]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%25==0: print(f"  {done}/{len(qs)}")
    print("done")

asyncio.run(main())
