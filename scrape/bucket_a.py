"""
Bucket A: 50 pattern-based Exa neural-search queries.
Imports searchers from the llm-fleet repo directly (no MCP round-trip).
Saves results to data/raw/searches/bucket_a/{idx}_{slug}.json
"""
import asyncio, json, os, pathlib, re, sys
from dotenv import load_dotenv

# Reach into the llm-fleet repo for the searchers module
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
load_dotenv(FLEET / ".env")

from searchers import build_searchers   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "raw" / "searches" / "bucket_a"
OUT.mkdir(parents=True, exist_ok=True)

QUERIES = [
    # Pattern 1: CSA at Chabad schools/camps
    "Chabad rabbi child sexual abuse conviction",
    "Lubavitch yeshiva sexual abuse lawsuit",
    "Gan Israel summer camp abuse Chabad",
    "Chabad cheder molestation case",
    "Chabad Hasidic school teacher arrested child abuse",
    "Oholei Torah abuse allegations Crown Heights",
    "Bnos Menachem Beis Rivkah teacher misconduct",
    "Lubavitch Yeshiva Crown Heights abuse historic",
    # Pattern 2: Rabbi sex-crime arrests
    "Chabad rabbi arrested sexual assault",
    "Lubavitch shaliach charged sex crime",
    "Chabad rabbi convicted child pornography",
    "Lubavitch director arrested sexual misconduct",
    # Pattern 3: Federal / state financial fraud
    "Chabad nonprofit tax fraud DOJ indictment",
    "Lubavitch organization federal grant fraud",
    "Chabad rabbi indicted tax evasion",
    "Chabad charity money laundering",
    "Friends of Lubavitch IRS investigation",
    "Colel Chabad fraud allegations",
    "Merkos L'Inyonei Chinuch lawsuit",
    # Pattern 4: Elder financial abuse / coerced bequests
    "elderly donor Chabad lawsuit real estate transfer",
    "Chabad rabbi sued widow property coerced",
    "Lubavitch elder financial exploitation lawsuit",
    "Chabad coerced bequest civil suit",
    # Pattern 5: Institutional cover-up
    "Chabad Royal Commission child abuse Australia findings",
    "Lubavitch rabbi cover up sexual abuse allegations",
    "Chabad institution failed to report abuse",
    "Chabad rabbi shielded accused abuser community",
    "Chabad rabbi fled to Israel evade prosecution",
    # Pattern 6: Shlichus territorial
    "Chabad shlichus territorial dispute lawsuit",
    "Lubavitch shaliach contract dispute court",
    "Chabad house ownership lawsuit dispute",
    "Chabad rabbi sued for control synagogue assets",
    # Regional sweeps
    "Chabad Russia Berel Lazar criminal investigation oligarch",
    "Chabad Ukraine Dnipro corruption rabbi",
    "Chabad Argentina criminal case Buenos Aires rabbi",
    "Chabad Brazil rabbi indicted fraud",
    "Chabad Mexico money laundering rabbi",
    "Chabad Bangkok Thailand scandal rabbi",
    "Chabad Israel Kfar Chabad criminal investigation",
    "Chabad Hebron Kiryat Arba settler violence",
    "Chabad West Bank land seizure Palestinian rabbi",
    "Lubavitch UK Stamford Hill lawsuit rabbi",
    "Chabad France Paris rabbi criminal",
    "Chabad Canada Montreal Quebec lawsuit",
    "Chabad Miami Florida rabbi fraud indictment",
    "Chabad Postville Iowa successor Agriprocessors",
    # Categorical
    "Aleph Institute prison chaplain abuse Chabad",
    "Chabad mikvah hidden camera voyeurism",
    "Chabad R-1 religious worker visa fraud",
    "Chabad-Lubavitch deed theft Brooklyn elderly",
]

assert len(QUERIES) == 50, f"want 50 queries, got {len(QUERIES)}"

def slugify(q: str, i: int) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")[:60]
    return f"{i:02d}_{s}"

async def main():
    s = build_searchers().get("exa")
    if not s:
        print("ERROR: no Exa keys configured", file=sys.stderr)
        sys.exit(1)

    sem = asyncio.Semaphore(8)
    counts = {"ok": 0, "err": 0, "total_results": 0}

    async def one(i: int, q: str):
        async with sem:
            r = await s.search(q, num_results=10, search_type="neural")
        out_file = OUT / f"{slugify(q,i)}.json"
        out_file.write_text(json.dumps(r.as_dict(), indent=2))
        if r.ok:
            counts["ok"] += 1
            counts["total_results"] += len(r.results)
            print(f"  [{i+1:02d}] {len(r.results):2d} hits | {q[:60]}")
        else:
            counts["err"] += 1
            print(f"  [{i+1:02d}] ERR ({r.error}) | {q[:60]}")

    await asyncio.gather(*[one(i,q) for i,q in enumerate(QUERIES)])
    print(f"\ndone. ok={counts['ok']} err={counts['err']} total_hits={counts['total_results']}")
    print(f"-> {OUT}")

asyncio.run(main())
