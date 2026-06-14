#!/usr/bin/env bash
# run_expedition_jh.sh — Charts J + H expedition driver
# Fires the two highest-leverage new charts in order and reports throughput.
#
# Usage:
#   ./scrape/run_expedition_jh.sh                   # full sweep, all domains + all perps
#   ./scrape/run_expedition_jh.sh smoke             # 20 domains + 10 perps (verification)
#   ./scrape/run_expedition_jh.sh j-only            # Wayback only
#   ./scrape/run_expedition_jh.sh h-only            # CourtListener only
#
# All output goes to data/raw/searches/bucket_p_wayback_cdx/ and bucket_o_courtlistener/.
# Downstream: results feed the existing triage → fetch_articles → extract pipeline.

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$ROOT/data/expedition_logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/expedition_jh_${TS}.log"

MODE="${1:-full}"

case "$MODE" in
  smoke)    J_ARGS="--limit 20"; H_ARGS="--limit 10" ;;
  j-only)   J_ARGS="";           H_ARGS="SKIP"       ;;
  h-only)   J_ARGS="SKIP";       H_ARGS=""           ;;
  full|*)   J_ARGS="";           H_ARGS=""           ;;
esac

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "=== Expedition J+H — mode: $MODE ==="
log "log file: $LOG"

# ---------- Preconditions ----------
HOUSES=$(sqlite3 data/chabad.db "SELECT COUNT(*) FROM houses WHERE website IS NOT NULL AND website != ''")
PERPS=$(sqlite3 data/chabad.db "SELECT COUNT(DISTINCT p.full_name) FROM incident_people ip JOIN people p ON p.id=ip.person_id WHERE ip.role='perpetrator' AND p.full_name NOT LIKE 'Unnamed%' AND p.full_name NOT LIKE 'Unknown%' AND length(p.full_name) > 8 AND p.full_name NOT LIKE '%,%'")
J_CACHED=$(find data/raw/searches/bucket_p_wayback_cdx -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
H_CACHED=$(find data/raw/searches/bucket_o_courtlistener -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
log "DB: $HOUSES houses with websites, $PERPS named perps"
log "Cache: $J_CACHED Wayback indexes, $H_CACHED CourtListener responses"

# ---------- Chart J ----------
if [ "$J_ARGS" != "SKIP" ]; then
  log ""
  log "--- CHART J: Wayback CDX walker ---"
  log "Walking houses.website + chabad.org central surfaces"
  log "Output: data/raw/searches/bucket_p_wayback_cdx/"
  python3 scrape/chart_j_wayback_cdx.py $J_ARGS 2>&1 | tee -a "$LOG"
  J_AFTER=$(find data/raw/searches/bucket_p_wayback_cdx -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  J_NEW=$((J_AFTER - J_CACHED))
  J_SNAPS=$(python3 -c "
import json, pathlib
total=0
for fp in pathlib.Path('data/raw/searches/bucket_p_wayback_cdx').glob('*.json'):
    try: total += json.load(open(fp)).get('snapshot_count',0)
    except: pass
print(total)")
  log "Chart J: +$J_NEW new domain indexes, $J_SNAPS total snapshots tracked"
fi

# ---------- Chart H ----------
if [ "$H_ARGS" != "SKIP" ]; then
  log ""
  log "--- CHART H: CourtListener REST v4 sweep ---"
  log "Querying all named perps + 12 institutions for opinions + RECAP dockets"
  log "Output: data/raw/searches/bucket_o_courtlistener/"
  python3 scrape/courtlistener_sweep.py $H_ARGS 2>&1 | tee -a "$LOG"
  H_AFTER=$(find data/raw/searches/bucket_o_courtlistener -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  H_NEW=$((H_AFTER - H_CACHED))
  H_HITS=$(python3 -c "
import json, pathlib
total=0
for fp in pathlib.Path('data/raw/searches/bucket_o_courtlistener').glob('*.json'):
    try: total += len(json.load(open(fp)).get('results',[]))
    except: pass
print(total)")
  log "Chart H: +$H_NEW new query responses, $H_HITS total hits tracked"
fi

# ---------- Summary + next steps ----------
log ""
log "=== Expedition complete ==="
log "Next steps to ingest results:"
log "  1. Triage Chart J snapshots into URLs of interest (which staff-bios survived takedown)"
log "     python3 scrape/triage_v2.py --source bucket_p_wayback_cdx"
log "  2. Fetch high-confidence Wayback snapshots:"
log "     python3 scrape/fetch_wayback_gentle.py"
log "  3. Triage Chart H hits into incident candidates:"
log "     python3 scrape/triage_v2.py --source bucket_o_courtlistener"
log "  4. Extract + load via existing pipeline:"
log "     python3 scrape/extract_from_snippets.py && python3 scrape/load_snippet_extracts.py"
log ""
log "Log saved: $LOG"
