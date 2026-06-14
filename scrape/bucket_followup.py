"""
Bucket Followup — self-driving second lap.

Aggregates every `follow_up_searches[]` the fleet generated during Bucket A
extraction, dedupes, fires through search_batch (Exa neural), saves results
to data/raw/searches/bucket_followup/ for triage.py to pick up.
"""
import json, glob, hashlib, re, asyncio, os, sys, dataclasses
from pathlib import Path

sys.path.insert(0, "/Volumes/EOS_DIGITAL/llm-fleet")
for line in open("/Volumes/EOS_DIGITAL/llm-fleet/.env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from searchers import build_searchers  # noqa

ROOT = Path("/Volumes/EOS_DIGITAL/chabad-tracker")
EXTRACTED = ROOT / "data/raw/extracted"
OUT = ROOT / "data/raw/searches/bucket_followup"
OUT.mkdir(parents=True, exist_ok=True)


def norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def collect_queries():
    seen = set()
    queries = []
    for f in sorted(EXTRACTED.glob("*.json")):
        try:
            data = json.load(open(f))
        except Exception:
            continue
        for q in (data.get("follow_up_searches") or []):
            if not isinstance(q, str):
                continue
            n = norm(q)
            if len(n) < 8 or n in seen:
                continue
            # skip overly generic
            if n in {"chabad lubavitch crimes", "chabad abuse"}:
                continue
            seen.add(n)
            queries.append(q.strip())
    return queries


async def fire(queries, engine="exa"):
    s = build_searchers()[engine]
    sem = asyncio.Semaphore(5)

    async def one(q):
        async with sem:
            try:
                res = await s.search(q, num_results=10)
                return q, (res.as_dict() if hasattr(res,"as_dict") else res)
            except Exception as e:
                return q, {"error": str(e)}

    tasks = [one(q) for q in queries]
    done = 0
    for coro in asyncio.as_completed(tasks):
        q, res = await coro
        h = hashlib.sha256(q.encode()).hexdigest()[:16]
        out = {"query": q, "engine": engine, "results": res.get("results", []) if isinstance(res,dict) else [], "error": res.get("error") if isinstance(res,dict) else str(res)}
        (OUT / f"{h}.json").write_text(json.dumps(out, indent=2))
        done += 1
        if done % 20 == 0:
            print(f"  [{done}/{len(queries)}]")


def main():
    queries = collect_queries()
    print(f"Collected {len(queries)} unique follow-up queries.")
    # cap so we don't blow the search budget in one shot
    cap = int(os.environ.get("CAP", "9999"))
    queries = queries[:cap]
    print(f"Firing {len(queries)} via Exa...")
    asyncio.run(fire(queries, engine="exa"))
    print(f"Done. Results in {OUT}")


if __name__ == "__main__":
    main()
