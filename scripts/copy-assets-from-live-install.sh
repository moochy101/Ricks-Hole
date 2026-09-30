#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC=${1:-/opt/pihole-eink/assets/hologram}
DST="$ROOT/assets/hologram"
mkdir -p "$DST"
for f in HAPPY.png LOOK_L.png LOOK_R.png BORED.png SMART.png EXCITED.png INTENSE.png ANGRY.png SLEEP.png BROKEN.png; do
  [[ -f "$SRC/$f" ]] || { echo "Missing $SRC/$f" >&2; exit 1; }
  cp -a "$SRC/$f" "$DST/$f"
done
if [[ -f /opt/pihole-eink/rick_voice.py ]]; then
  cp -a /opt/pihole-eink/rick_voice.py "$ROOT/rick_voice.py"
fi
echo "Copied live face assets into $DST"
echo "Review asset licensing before publishing them publicly."
