"""
Fleet-powered Layer 3 enrichment: extract explicit kinship relations
("son of", "brother of", "married to", "father-in-law") from article text.

Input:  data/raw/articles/*.txt (the cleaned article corpus)
Output: data/raw/relations/{hash}.json — list of (person_a, relation, person_b)
Then merges high-confidence relations into the family_relations table.
"""
import asyncio, json, pathlib, sys, sqlite3, re

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
import os
for line in open(FLEET / ".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
ART  = ROOT / "data/raw/articles"
OUT  = ROOT / "data/raw/relations"
OUT.mkdir(parents=True, exist_ok=True)
DB   = ROOT / "data/chabad.db"

PROMPT = """Extract explicit kinship relations between named people from this article. Return ONLY a JSON array. No markdown.

Article:
{text}

Output schema:
[
  {{"person_a": "Full Name", "relation": "father_of|son_of|brother_of|sister_of|spouse_of|father_in_law_of|son_in_law_of|grandfather_of|nephew_of|uncle_of|cousin_of", "person_b": "Full Name", "evidence": "short quote from article"}}
]

Rules:
- Only include relations stated explicitly in the text (e.g. "his father Rabbi X", "Y's brother Z", "married to W").
- Both people must be named (skip "his father" with no name given).
- Skip honorifics in the name: "Rabbi Menachem Schneerson" -> "Menachem Schneerson".
- If no relations found, return [].
- Return ONLY the JSON array."""


async def extract_one(text, providers, sem):
    async with sem:
        snippet = text[:6000]
        r = await dispatch_role("uncensored", PROMPT.format(text=snippet), max_tokens=900, providers=providers)
    if not r.ok or not (r.text or "").strip():
        return None, r.error or "empty"
    t = r.text.strip().strip("`")
    if t.lower().startswith("json"): t = t[4:].strip()
    try:
        return json.loads(t), None
    except Exception:
        try:
            s = t.index("["); e = t.rindex("]")
            return json.loads(t[s:e+1]), None
        except Exception as ex:
            return None, f"parse:{ex}"


async def stage1():
    providers = build_providers()
    sem = asyncio.Semaphore(5)
    files = sorted(ART.glob("*.txt"))
    print(f"articles: {len(files)}")
    counts = {"ok":0, "err":0, "relations":0}

    async def do(f):
        h = f.stem
        out = OUT / f"{h}.json"
        if out.exists(): return
        text = f.read_text(errors="ignore")
        if len(text) < 300: return
        rels, err = await extract_one(text, providers, sem)
        if err:
            counts["err"] += 1; return
        out.write_text(json.dumps(rels, indent=2))
        counts["ok"] += 1
        counts["relations"] += len(rels)

    done = 0
    tasks = [do(f) for f in files]
    for c in asyncio.as_completed(tasks):
        await c
        done += 1
        if done % 25 == 0:
            print(f"  [{done}/{len(files)}] ok={counts['ok']} rels={counts['relations']} err={counts['err']}")
    print(f"done. ok={counts['ok']} relations={counts['relations']} err={counts['err']}")


def norm(name):
    if not name: return ""
    n = re.sub(r"\b(rabbi|rebbe|rabbanit|mrs?\.|mr\.|dr\.)\b", "", name, flags=re.I)
    return re.sub(r"\s+", " ", n).strip().lower()


def stage2_merge():
    """Merge collected relations into family_relations table."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    # Build lookup: norm(full_name) -> shliach_aid
    cur.execute("SELECT id, shliach_aid, full_name, given_name, surname FROM people")
    name_to_aid = {}
    for pid, aid, full, fn, ln in cur.fetchall():
        # use id as fallback if shliach_aid is null
        key_id = aid if aid is not None else pid
        for k in {norm(full), norm(f"{fn or ''} {ln or ''}")}:
            if k: name_to_aid.setdefault(k, key_id)

    inserted = matched_pairs = unmatched = 0
    seen_pair = set()
    for f in OUT.glob("*.json"):
        try:
            rels = json.load(open(f))
        except Exception:
            continue
        if not isinstance(rels, list): continue
        for r in rels:
            a = name_to_aid.get(norm(r.get("person_a","")))
            b = name_to_aid.get(norm(r.get("person_b","")))
            rel = r.get("relation","")
            if not (a and b and rel): unmatched += 1; continue
            key = tuple(sorted([a,b])) + (rel,)
            if key in seen_pair: continue
            seen_pair.add(key)
            matched_pairs += 1
            # collapse fine-grained relations into schema buckets
            bucket = {
                "father_of":"parent_of","mother_of":"parent_of",
                "son_of":"parent_of","daughter_of":"parent_of",
                "brother_of":"sibling_of","sister_of":"sibling_of","cousin_of":"sibling_of",
                "spouse_of":"spouse_of",
                "father_in_law_of":"in_law_of","son_in_law_of":"in_law_of",
                "grandfather_of":"parent_of","nephew_of":"in_law_of","uncle_of":"in_law_of",
            }.get(rel, rel)
            # For son_of/daughter_of, swap so person_a is parent
            if rel in ("son_of","daughter_of"): a, b = b, a
            cur.execute(
              "INSERT OR IGNORE INTO family_relations(person_a, person_b, relation, notes) VALUES(?,?,?,?)",
              (a, b, bucket, "fleet_article_extraction")
            )
            inserted += cur.rowcount
    conn.commit()
    print(f"merge: matched_pairs={matched_pairs} inserted={inserted} unmatched_names={unmatched}")


if __name__ == "__main__":
    asyncio.run(stage1())
    stage2_merge()
