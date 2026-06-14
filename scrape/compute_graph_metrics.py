"""
compute_graph_metrics.py
------------------------
Builds a weighted multi-edge graph from chabad.db, computes:
  - Betweenness centrality  (bridge nodes)
  - Eigenvector centrality  (influence / prestige)
  - Weighted degree         (raw connectivity)
  - Louvain community ID    (cluster membership)
  - K-core number           (inner-ring depth)

Writes results back to DB:
  people:  betweenness, eigenvector, degree_w, community_id, kcore
  houses:  betweenness, eigenvector, degree_w, community_id, kcore

Edge weights used for Louvain / betweenness:
  co-defendant  → 3.0  (strongest — shared crime)
  family        → 2.0  (structural alliance)
  house-member  → 1.0  (institutional affiliation)
  geo-proximity → 0.5  (derived — same metro, within 10 km)
  crime-type    → 0.7  (same crime type at same institution)
"""

import sqlite3, math, json, pathlib, collections
import networkx as nx
import community as community_louvain   # python-louvain

ROOT  = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB    = ROOT / "data/chabad.db"

con = sqlite3.connect(DB)
con.execute("PRAGMA journal_mode=WAL")

# ── 0. Schema migration ───────────────────────────────────────────────────────
for col, tbl in [
    ("betweenness REAL", "people"), ("eigenvector REAL",  "people"),
    ("degree_w    REAL", "people"), ("community_id INT",  "people"),
    ("kcore       INT",  "people"),
    ("betweenness REAL", "houses"), ("eigenvector REAL",  "houses"),
    ("degree_w    REAL", "houses"), ("community_id INT",  "houses"),
    ("kcore       INT",  "houses"),
]:
    try:
        con.execute(f"ALTER TABLE {tbl} ADD COLUMN {col}")
    except Exception:
        pass   # column already exists
con.commit()

# ── 1. Build undirected weighted graph ───────────────────────────────────────
G = nx.Graph()

# Node labels:  "p:{id}" for people,  "h:{id}" for houses

print("Loading people nodes…")
for row in con.execute("SELECT id, full_name FROM people"):
    G.add_node(f"p:{row[0]}", label=row[1], type="person", dbid=row[0])

print("Loading house nodes…")
for row in con.execute("SELECT id, name FROM houses"):
    G.add_node(f"h:{row[0]}", label=row[1], type="house", dbid=row[0])

def add_edge(a, b, weight, rel):
    if G.has_edge(a, b):
        # accumulate weight on multi-edges
        G[a][b]["weight"] = G[a][b].get("weight", 0) + weight
        G[a][b]["rels"]   = G[a][b].get("rels", set()) | {rel}
    else:
        G.add_edge(a, b, weight=weight, rels={rel})

# Co-defendant edges (people sharing an incident) — weight 3
print("Building co-defendant edges…")
for row in con.execute("""
    SELECT a.person_id, b.person_id, COUNT(*) AS shared
    FROM incident_people a
    JOIN incident_people b ON a.incident_id = b.incident_id AND a.person_id < b.person_id
    GROUP BY a.person_id, b.person_id
"""):
    add_edge(f"p:{row[0]}", f"p:{row[1]}", weight=3.0 * row[2], rel="codefendant")

# Family edges — weight 2
print("Building family edges…")
for row in con.execute("SELECT person_a, person_b FROM family_relations"):
    add_edge(f"p:{row[0]}", f"p:{row[1]}", weight=2.0, rel="family")

# person_relations edges (codefendant, family, supervisor, attorney, financial, rabbinical)
RELATION_WEIGHTS = {
    "codefendant":   2.5,
    "family":        2.0,
    "supervisor":    1.5,
    "financial":     1.5,
    "rabbinical":    1.2,
    "attorney":      1.0,
}
print("Building person_relations edges…")
for row in con.execute("SELECT person_a, person_b, rel_type FROM person_relations"):
    w = RELATION_WEIGHTS.get(row[2], 1.0)
    add_edge(f"p:{row[0]}", f"p:{row[1]}", weight=w, rel=row[2])

# House-membership edges — weight 1
print("Building house-membership edges…")
for row in con.execute("SELECT person_id, house_id FROM house_roles"):
    add_edge(f"p:{row[0]}", f"h:{row[1]}", weight=1.0, rel="member")

# Crime-type co-occurrence: two people, same institution, same crime type → weight 0.7
print("Building crime-type co-occurrence edges…")
for row in con.execute("""
    SELECT ip1.person_id, ip2.person_id, COUNT(*) AS shared
    FROM incident_people ip1
    JOIN incident_people ip2
      ON ip1.incident_id != ip2.incident_id AND ip1.person_id < ip2.person_id
    JOIN incidents i1 ON i1.id = ip1.incident_id
    JOIN incidents i2 ON i2.id = ip2.incident_id
    JOIN incident_houses ih1 ON ih1.incident_id = ip1.incident_id
    JOIN incident_houses ih2 ON ih2.incident_id = ip2.incident_id
       AND ih1.house_id = ih2.house_id
    WHERE i1.type = i2.type
    GROUP BY ip1.person_id, ip2.person_id
"""):
    add_edge(f"p:{row[0]}", f"p:{row[1]}", weight=0.7 * row[2], rel="crime_type")

# Geo-proximity edges between houses (≤ 10 km) — weight 0.5
print("Building geo-proximity edges between houses…")
houses_coords = list(con.execute(
    "SELECT id, lat, lng FROM houses WHERE lat IS NOT NULL AND lng IS NOT NULL"
))
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

geo_edges = 0
for i in range(len(houses_coords)):
    for j in range(i+1, len(houses_coords)):
        a, la, lo = houses_coords[i]
        b, lb, lb2 = houses_coords[j]
        try:
            d = haversine(la, lo, lb, lb2)
        except Exception:
            continue
        if d <= 10.0 and d > 0:
            add_edge(f"h:{a}", f"h:{b}", weight=0.5 * max(0.1, 1 - d/10), rel="geo")
            geo_edges += 1

print(f"  → {geo_edges} geo-proximity edges (≤10 km)")
print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

# ── 2. Compute metrics on the FULL graph ────────────────────────────────────
# Use largest connected component for centrality (required for some algorithms)
print("\nComputing largest connected component…")
Gcc = G.subgraph(max(nx.connected_components(G), key=len)).copy()
print(f"  LCC: {Gcc.number_of_nodes()} nodes, {Gcc.number_of_edges()} edges")

print("Computing betweenness centrality (may take ~60s)…")
# Use k-sample approximation for large graphs (k=500 gives good accuracy)
bet = nx.betweenness_centrality(Gcc, weight="weight", normalized=True,
                                k=min(500, Gcc.number_of_nodes()))

print("Computing eigenvector centrality…")
try:
    eig = nx.eigenvector_centrality_numpy(Gcc, weight="weight")
except Exception:
    eig = {}

print("Computing weighted degree…")
wdeg = dict(Gcc.degree(weight="weight"))

print("Computing k-core (unweighted)…")
kcore_map = nx.core_number(G)   # use full graph for k-core

print("Running Louvain community detection…")
# Louvain works on the full graph (including isolated nodes are handled automatically)
partition = community_louvain.best_partition(G, weight="weight", random_state=42)
# Re-number communities by size (community 0 = largest)
comm_sizes = collections.Counter(partition.values())
rank_map   = {c: i for i, (c, _) in enumerate(comm_sizes.most_common())}
partition  = {node: rank_map[cid] for node, cid in partition.items()}

n_communities = len(set(partition.values()))
print(f"  → {n_communities} communities detected")

# Print top 10 communities
comm_members = collections.defaultdict(list)
for node, cid in partition.items():
    comm_members[cid].append(node)
print("\nTop 10 communities (by size):")
for cid in range(min(10, n_communities)):
    members = comm_members[cid]
    # Sample node labels
    sample = [G.nodes[m].get("label","?") for m in members[:3]]
    print(f"  Community {cid}: {len(members)} nodes — {', '.join(sample)}…")

# ── 3. Write metrics back to DB ──────────────────────────────────────────────
print("\nWriting metrics to DB…")

# Normalise betweenness to 0–1 range (already normalised by nx)
# Normalise eigenvector to 0–1 range
max_eig  = max(eig.values()) if eig else 1
max_wdeg = max(wdeg.values()) if wdeg else 1

people_updates = []
house_updates  = []

for node, data in G.nodes(data=True):
    b   = bet.get(node, 0.0)
    e   = eig.get(node, 0.0) / max_eig if max_eig else 0.0
    d   = wdeg.get(node, 0.0) / max_wdeg if max_wdeg else 0.0
    c   = partition.get(node, -1)
    k   = kcore_map.get(node, 0)
    dbid = data["dbid"]
    if data["type"] == "person":
        people_updates.append((b, e, d, c, k, dbid))
    else:
        house_updates.append((b, e, d, c, k, dbid))

con.executemany(
    "UPDATE people SET betweenness=?, eigenvector=?, degree_w=?, community_id=?, kcore=? WHERE id=?",
    people_updates
)
con.executemany(
    "UPDATE houses SET betweenness=?, eigenvector=?, degree_w=?, community_id=?, kcore=? WHERE id=?",
    house_updates
)
con.commit()

# ── 4. Summary report ────────────────────────────────────────────────────────
print("\n=== GRAPH METRICS SUMMARY ===")
print(f"Nodes in graph:      {G.number_of_nodes():,}")
print(f"Edges in graph:      {G.number_of_edges():,}")
print(f"Communities:         {n_communities}")
print(f"People updated:      {len(people_updates):,}")
print(f"Houses updated:      {len(house_updates):,}")

print("\nTop 15 BRIDGE NODES (betweenness centrality):")
top_bet = sorted(
    [(node, bet[node], G.nodes[node]["label"], G.nodes[node]["type"])
     for node in bet if bet[node] > 0],
    key=lambda x: -x[1]
)[:15]
for node, score, label, ntype in top_bet:
    c = partition.get(node, -1)
    k = kcore_map.get(node, 0)
    print(f"  [{ntype:6}] {label[:40]:40} bet={score:.4f}  k={k}  comm={c}")

print("\nTop 15 INFLUENTIAL NODES (eigenvector centrality):")
top_eig = sorted(
    [(node, eig.get(node,0), G.nodes[node]["label"], G.nodes[node]["type"])
     for node in G.nodes],
    key=lambda x: -x[1]
)[:15]
for node, score, label, ntype in top_eig:
    print(f"  [{ntype:6}] {label[:40]:40} eig={score/max_eig:.4f}")

print("\nTop 10 highest k-core nodes (inner ring):")
top_k = sorted(
    [(node, kcore_map[node], G.nodes[node]["label"], G.nodes[node]["type"])
     for node in G.nodes],
    key=lambda x: -x[1]
)[:10]
for node, score, label, ntype in top_k:
    print(f"  [{ntype:6}] {label[:40]:40} k={score}")

# Export community summary JSON for UI
comm_summary = []
for cid in range(n_communities):
    members = comm_members[cid]
    people_in = [G.nodes[m] for m in members if G.nodes[m]["type"] == "person"]
    houses_in = [G.nodes[m] for m in members if G.nodes[m]["type"] == "house"]
    # Get severity for people in community
    p_ids = [d["dbid"] for d in people_in]
    if p_ids:
        ph = ",".join("?"*len(p_ids))
        sev = con.execute(f"""
            SELECT MAX(CASE i.severity
              WHEN 'convicted' THEN 6 WHEN 'indicted' THEN 5
              WHEN 'charged' THEN 4 WHEN 'settled' THEN 3
              WHEN 'investigation' THEN 2 ELSE 1 END)
            FROM incident_people ip JOIN incidents i ON i.id=ip.incident_id
            WHERE ip.person_id IN ({ph})
        """, p_ids).fetchone()[0] or 0
        sev_label = {6:"convicted",5:"indicted",4:"charged",3:"settled",2:"investigation"}.get(sev,"allegation")
    else:
        sev_label = "none"
    comm_summary.append({
        "id": cid, "size": len(members),
        "n_people": len(people_in), "n_houses": len(houses_in),
        "worst_sev": sev_label,
        "sample": [d["label"] for d in (people_in[:2] + houses_in[:1])]
    })

out_path = ROOT / "data/graph_communities.json"
out_path.write_text(json.dumps(comm_summary, ensure_ascii=False, indent=2))
print(f"\nCommunity summary → {out_path}")
print("\nDone. Run: cp data/chabad.db ui/public/chabad.db && vercel --prod")
