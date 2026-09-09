#!/bin/bash
# Clear generated data so the pipeline can be tested from a clean slate.
#
#   ./scripts/reset.sh                 # derived data only        -> then ~6 min
#   ./scripts/reset.sh --cache         # + geocoding cache        -> then ~55 min
#   ./scripts/reset.sh --all           # + channel list           -> then ~1h
#   ./scripts/reset.sh --all --run     # ...and start the pipeline right away
#   ./scripts/reset.sh --cache --yes   # skip the confirmation prompt
#
# Everything removed is copied to .backups/<timestamp>/ first. Nothing under
# src/, web/src/ or config/queries.txt is ever touched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CACHE=0; ALL=0; RUN=0; YES=0
for arg in "$@"; do
  case "$arg" in
    --cache) CACHE=1 ;;
    --all)   ALL=1; CACHE=1 ;;
    --run)   RUN=1 ;;
    --yes|-y) YES=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# ---- what goes ----
TARGETS=(
  streams.json
  data/inventory.json
  data/index.json
  data/unresolved.json
  data/streams.prev.json
  data/dead.json
  web/public/streams.json
  web/dist/streams.json
)
for f in data/*.log; do [ -e "$f" ] && TARGETS+=("$f"); done
[ "$CACHE" = 1 ] && TARGETS+=(data/geo_cache.json)
[ "$ALL" = 1 ]   && TARGETS+=(config/channels.json)

# ---- warn about the expensive ones ----
if [ "$CACHE" = 1 ] && [ "$YES" = 0 ]; then
  echo "This also clears:"
  [ -e data/geo_cache.json ] && echo "  data/geo_cache.json   ($(python3 -c 'import json;print(len(json.load(open("data/geo_cache.json"))))' 2>/dev/null || echo '?') entries) -> build.py will take ~55 min (Nominatim allows 1 req/sec)"
  [ "$ALL" = 1 ] && [ -e config/channels.json ] && echo "  config/channels.json  ($(python3 -c 'import json;print(len(json.load(open("config/channels.json"))))' 2>/dev/null || echo '?') channels) -> discover.py must run first (~4 min)"
  printf 'continue? [y/N] '
  read -r reply
  case "$reply" in [yY]*) ;; *) echo "cancelled"; exit 1 ;; esac
fi

# ---- back up, then delete ----
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$ROOT/.backups/$STAMP"
mkdir -p "$BACKUP"

removed=0
for f in "${TARGETS[@]}"; do
  if [ -e "$f" ]; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp -p "$f" "$BACKUP/$f"
    rm -f "$f"
    echo "  removed  $f"
    removed=$((removed + 1))
  fi
done

if [ "$removed" = 0 ]; then
  rmdir "$BACKUP" 2>/dev/null || true
  echo "nothing to remove - already clean"
else
  echo "$removed file(s) removed, backup in .backups/$STAMP/"
fi

# ---- what survived ----
echo "kept:"
for f in data/geo_cache.json config/channels.json config/queries.txt; do
  [ -e "$f" ] && echo "  $f"
done
echo "  src/  web/src/  scripts/"

# ---- next step ----
if [ ! -e config/channels.json ]; then
  NEXT="python3 src/pipeline.py --discover"
else
  NEXT="python3 src/pipeline.py"
fi

if [ "$RUN" = 1 ]; then
  echo
  echo "running: $NEXT"
  echo
  exec $NEXT
fi
echo
echo "next:  $NEXT"
