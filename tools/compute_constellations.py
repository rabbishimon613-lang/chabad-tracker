"""Compute People Web constellations and write to ui/public/constellations.json.

A constellation = a connected subgraph of `people` connected by
family_relations + person_relations + co-defendant edges (incident_people
join on incident_id). Scored per buildroad:

    + N for each named anchored perp
    + 2*N for each severity-weighted incident edge
    + N for each edge between two named people
    + N for % nodes with photos
    - N for % ghost nodes

Returns top-10 by score, with name + one-line + node count + photo count.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


SEVERITY_WEIGHT = {
    "convicted": 4, "indicted": 4,
    "charged":   2, "settled":  2,
    "investigation": 1, "allegation": 1,
}


def _build_graph(conn: sqlite3.Connection):
    """Returns (nodes, edges) where nodes is dict[id]={...} and edges is list of {a, b, reason, kind}."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Nodes — only people who appear in some incident OR are a known anchored perp.
    people_rows = cur.execute("""
        SELECT p.id, p.full_name, p.photo_url,
               (SELECT COUNT(*) FROM incident_people ip
                WHERE ip.person_id = p.id
                  AND LOWER(COALESCE(ip.role,'')) IN ('perpetrator','enabler','covered_up_by')) AS perp_incidents
        FROM people p
        WHERE p.id IN (SELECT person_id FROM incident_people)
           OR p.id IN (SELECT person_a FROM family_relations)
           OR p.id IN (SELECT person_b FROM family_relations)
    """).fetchall()
    nodes = {
        r["id"]: {
            "id":             r["id"],
            "name":           r["full_name"],
            "has_photo":      bool(r["photo_url"]),
            "perp_incidents": r["perp_incidents"] or 0,
            "named":          bool(r["full_name"] and r["full_name"].strip()),
        }
        for r in people_rows
    }

    edges = []

    # Family edges
    for r in cur.execute("SELECT person_a, person_b, relation FROM family_relations").fetchall():
        if r["person_a"] in nodes and r["person_b"] in nodes:
            edges.append({"a": r["person_a"], "b": r["person_b"],
                          "kind": "family", "reason": r["relation"] or "family"})

    # Person relations (co-defendant, etc.) — older schema uses rel_type / rel_detail.
    for r in cur.execute("SELECT person_a, person_b, rel_type, rel_detail FROM person_relations").fetchall():
        if r["person_a"] in nodes and r["person_b"] in nodes:
            edges.append({
                "a": r["person_a"], "b": r["person_b"],
                "kind": (r["rel_type"] or "relation"),
                "reason": r["rel_detail"] or r["rel_type"] or "linked",
            })

    # Co-defendant edges — two people in the same incident.
    inc_to_people = defaultdict(list)
    for r in cur.execute("""
        SELECT ip.incident_id, ip.person_id, COALESCE(i.severity,'') AS sev, i.type
        FROM incident_people ip JOIN incidents i ON i.id = ip.incident_id
        WHERE LOWER(COALESCE(ip.role,'')) IN ('perpetrator','enabler','covered_up_by')
    """).fetchall():
        if r["person_id"] in nodes:
            inc_to_people[r["incident_id"]].append((r["person_id"], r["sev"], r["type"]))
    for inc_id, members in inc_to_people.items():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i][0], members[j][0]
                sev = members[i][1]
                edges.append({
                    "a": a, "b": b, "kind": "codefendant",
                    "reason": f"Co-defendants on incident {inc_id} ({members[i][2] or 'case'}, {sev or 'unknown'})",
                    "severity": sev,
                })

    return nodes, edges


def _connected_components(nodes: dict, edges: list) -> list[list[int]]:
    """Union-find over the graph."""
    parent = {nid: nid for nid in nodes}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry: parent[rx] = ry
    for e in edges:
        if e["a"] in parent and e["b"] in parent:
            union(e["a"], e["b"])
    comps = defaultdict(list)
    for nid in nodes:
        comps[find(nid)].append(nid)
    return [c for c in comps.values() if len(c) >= 2]


def _score(component: list[int], nodes: dict, edges: list) -> dict:
    cnodes = {nid: nodes[nid] for nid in component}
    cset = set(component)
    cedges = [e for e in edges if e["a"] in cset and e["b"] in cset]

    named_perps = [n for n in cnodes.values() if n["named"] and n["perp_incidents"] > 0]
    photoed = sum(1 for n in cnodes.values() if n["has_photo"])
    ghost   = sum(1 for n in cnodes.values() if not n["named"] or n["perp_incidents"] == 0)

    # Severity-weighted incident contribution.
    sev_contrib = 0
    for e in cedges:
        if e["kind"] == "codefendant":
            sev_contrib += SEVERITY_WEIGHT.get((e.get("severity") or "").lower(), 1)
    named_named_edges = sum(
        1 for e in cedges
        if cnodes[e["a"]]["named"] and cnodes[e["b"]]["named"]
    )

    photo_pct = (photoed / len(cnodes)) if cnodes else 0
    ghost_pct = (ghost   / len(cnodes)) if cnodes else 0

    score = (
        len(named_perps) * 3 +
        sev_contrib * 2 +
        named_named_edges * 1 +
        photo_pct * 10 -
        ghost_pct * 4
    )
    title_perp = max(named_perps, key=lambda n: n["perp_incidents"]) if named_perps else None
    return {
        "node_count":      len(cnodes),
        "edge_count":      len(cedges),
        "named_perps":     len(named_perps),
        "photoed":         photoed,
        "ghosts":          ghost,
        "severity_weight": sev_contrib,
        "score":           round(score, 2),
        "node_ids":        component,
        "title_anchor_id": title_perp["id"] if title_perp else None,
        "title_anchor_name": title_perp["name"] if title_perp else None,
    }


def _one_line(con: dict, nodes: dict) -> str:
    n = con["node_count"]
    named = con["named_perps"]
    sev = con["severity_weight"]
    anchor = con["title_anchor_name"] or "—"
    return (
        f"{anchor} at center. {named} named perp{'s' if named != 1 else ''} "
        f"across {n} connected people. severity weight {sev}."
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db",  default="data/chabad.db")
    p.add_argument("--out", default="ui/public/constellations.json")
    p.add_argument("--top", type=int, default=10)
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    nodes, edges = _build_graph(conn)
    print(f"Graph: {len(nodes)} nodes, {len(edges)} edges")

    components = _connected_components(nodes, edges)
    scored = sorted(
        (_score(c, nodes, edges) for c in components),
        key=lambda s: s["score"], reverse=True,
    )[: args.top]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_components": len(components),
        "constellations": [
            {
                "rank":            i + 1,
                "anchor":          s["title_anchor_name"],
                "anchor_id":       s["title_anchor_id"],
                "one_line":        _one_line(s, nodes),
                "node_count":      s["node_count"],
                "edge_count":      s["edge_count"],
                "named_perps":     s["named_perps"],
                "photoed":         s["photoed"],
                "ghosts":          s["ghosts"],
                "score":           s["score"],
                "node_ids":        s["node_ids"][:30],
            }
            for i, s in enumerate(scored)
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"Top {len(scored)} constellations → {args.out}")
    for i, s in enumerate(scored[:5], 1):
        print(f"  {i}. {s['title_anchor_name'] or '(unnamed)'} · {s['node_count']} nodes · score {s['score']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
