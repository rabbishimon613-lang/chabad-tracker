#!/usr/bin/env bash
# Vercel prebuild: fetch chabad.db by URL, verify sha256, place in ui/public/.
# Phase 0 hash-pointer pattern. Source of truth = data/chabad.db.url + .sha256.
# (Originally planned to use Cloudflare R2; switched to GitHub Releases to
#  avoid the R2 payment-card requirement. Same pattern, different backend.)

set -euo pipefail

URL_FILE="data/chabad.db.url"
SHA_FILE="data/chabad.db.sha256"
OUT="ui/public/chabad.db"

if [ ! -f "$URL_FILE" ] || [ ! -f "$SHA_FILE" ]; then
  echo "::error::Missing hash-pointer files ($URL_FILE / $SHA_FILE). Cannot fetch DB."
  exit 1
fi

URL="$(tr -d '\n\r ' < "$URL_FILE")"
EXPECTED_SHA="$(tr -d '\n\r ' < "$SHA_FILE")"

mkdir -p "$(dirname "$OUT")"

echo "Fetching DB from $URL"
curl -sSfL --retry 3 --retry-delay 2 "$URL" -o "$OUT"

ACTUAL_SHA="$(shasum -a 256 "$OUT" | awk '{print $1}')"
if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
  echo "::error::sha256 mismatch."
  echo "  expected: $EXPECTED_SHA"
  echo "  actual:   $ACTUAL_SHA"
  rm -f "$OUT"
  exit 1
fi

echo "DB verified: $(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT") bytes, sha256 ok."
