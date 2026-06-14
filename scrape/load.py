"""
Load raw API JSON into SQLite.

Reads:
  data/raw/centers/*.json   — per-center detail (jsonapi format with `included`)
  data/raw/types.json       — service-type lookup (not loaded into DB; kept on disk)

Writes:
  houses, people, house_roles, sources
"""
import sqlite3, json, pathlib, sys, datetime

ROOT  = pathlib.Path(__file__).resolve().parent.parent
DB    = ROOT / "data" / "chabad.db"
CDIR  = ROOT / "data" / "raw" / "centers"

SOURCE_URL = "https://www.chabad.org/api/v2/chabadorg/centers"

def slugify(s: str) -> str:
    return (s or "").lower().replace("/", "-").replace(" ", "-")[:200]

def load_center(con: sqlite3.Connection, source_id: int, doc: dict, scraped_at: str):
    data = doc.get("data")
    if not data or data.get("type") != "center":
        return 0, 0
    a = data.get("attributes", {}) or {}
    rels = (data.get("relationships") or {})
    included = doc.get("included", []) or []

    addr = a.get("address") or {}
    coords = a.get("coordinates") or {}
    phone = (a.get("phone-number") or {}).get("number")

    mosad_aid = a.get("mosad-aid") or int(data.get("id") or 0)
    name      = a.get("name") or ""
    static_url= a.get("static-url") or ""
    slug      = slugify(f"{static_url}-{mosad_aid}")

    cur = con.execute("""
        INSERT INTO houses (mosad_aid, name, slug, country, state, city, address,
                            lat, lng, website, phone, parent_org, source_url, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Chabad-Lubavitch', ?, ?)
        ON CONFLICT(mosad_aid) DO UPDATE SET
          name=excluded.name, slug=excluded.slug, country=excluded.country,
          state=excluded.state, city=excluded.city, address=excluded.address,
          lat=excluded.lat, lng=excluded.lng, website=excluded.website,
          phone=excluded.phone, scraped_at=excluded.scraped_at
        RETURNING id
    """, (
        mosad_aid, name, slug,
        addr.get("country"), addr.get("state"), addr.get("city"),
        ", ".join(filter(None, [addr.get("address-line1"), addr.get("address-line2"),
                                addr.get("zip-code")])),
        coords.get("latitude"), coords.get("longitude"),
        a.get("url"), phone,
        f"{SOURCE_URL}/{mosad_aid}", scraped_at
    ))
    house_id = cur.fetchone()[0]

    # Personnel: pull people out of `included`
    persons = [x for x in included if x.get("type") == "person"]
    n_people = 0
    n_roles  = 0
    for p in persons:
        pa = p.get("attributes", {}) or {}
        shliach_aid = pa.get("shliach-aid") or int(p.get("id") or 0)
        first = pa.get("first-name") or ""
        last  = pa.get("last-name") or ""
        title = pa.get("title") or ""
        full  = " ".join(filter(None, [title, first, last])).strip()
        gender = "f" if title in ("Mrs.","Ms.","Miss","Mrs") else ("m" if title in ("Rabbi","Mr.","Mr") else None)

        cur = con.execute("""
            INSERT INTO people (shliach_aid, full_name, given_name, surname, gender,
                                first_seen_house_id, first_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(shliach_aid) DO UPDATE SET
              full_name=excluded.full_name, given_name=excluded.given_name,
              surname=excluded.surname, gender=COALESCE(people.gender, excluded.gender)
            RETURNING id
        """, (shliach_aid, full, first, last, gender, house_id, scraped_at))
        person_id = cur.fetchone()[0]
        n_people += 1

        role = pa.get("position") or "personnel"
        is_director = 1 if pa.get("is-director") else 0
        is_deceased = 1 if pa.get("is-deceased") else 0
        con.execute("""
            INSERT INTO house_roles (house_id, person_id, role, is_primary, is_deceased)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(house_id, person_id, role) DO UPDATE SET
              is_primary=excluded.is_primary, is_deceased=excluded.is_deceased
        """, (house_id, person_id, role, is_director, is_deceased))
        n_roles += 1

    return n_people, n_roles


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    cur = con.execute("""
        INSERT INTO sources (url, type, title, accessed_at)
        VALUES (?, 'directory', 'chabad.org centers API', ?)
        RETURNING id
    """, (SOURCE_URL, now))
    source_id = cur.fetchone()[0]

    files = sorted(CDIR.glob("*.json"))
    print(f"loading {len(files)} center files...")

    n_houses = n_people = n_roles = n_skip = 0
    for i, fp in enumerate(files, 1):
        try:
            doc = json.loads(fp.read_text())
            if "_error" in doc or "data" not in doc:
                n_skip += 1
                continue
            p, r = load_center(con, source_id, doc, now)
            n_houses += 1
            n_people += p
            n_roles  += r
        except Exception as e:
            print(f"  skip {fp.name}: {e}", file=sys.stderr)
            n_skip += 1
        if i % 500 == 0:
            con.commit()
            print(f"  [{i}] houses={n_houses} people-occurrences={n_people} roles={n_roles} skip={n_skip}")

    con.commit()
    print(f"\ndone. houses={n_houses} role-rows={n_roles} skipped={n_skip}")
    # distinct people (deduped via shliach_aid)
    distinct_people = con.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    print(f"distinct people: {distinct_people}")
    con.close()

if __name__ == "__main__":
    main()
