#!/bin/bash
# Registers the daily pipeline with macOS launchd.
#   ./scripts/install-schedule.sh          # install
#   ./scripts/install-schedule.sh remove   # uninstall
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.livecam.pipeline"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "${1:-}" = "remove" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$DEST"
  echo "schedule removed"
  exit 0
fi

PYTHON="$(command -v python3)"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__ROOT__|$ROOT|g" -e "s|__PYTHON__|$PYTHON|g" \
    "$ROOT/scripts/$LABEL.plist" > "$DEST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"

echo "installed - runs daily at 06:00"
echo "  log    : $ROOT/data/pipeline.log"
echo "  status : launchctl list | grep $LABEL"
echo "  run now: launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "  remove : ./scripts/install-schedule.sh remove"
