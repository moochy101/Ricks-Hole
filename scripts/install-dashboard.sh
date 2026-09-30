#!/usr/bin/env bash
set -euo pipefail
ADMIN=/var/www/html/admin
INDEX="$ADMIN/index.lp"
BACKUP="$ADMIN/index.lp.rick-hole-backup"
JS="$ADMIN/scripts/js/rick-hole.js"
IMG="$ADMIN/img/rick-hole-live.png"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$INDEX" ]] || { echo "Pi-hole Web index.lp not found: $INDEX"; exit 1; }
cp -a "$INDEX" "$BACKUP"
install -d "$ADMIN/img" "$ADMIN/scripts/js"
touch "$IMG"
chown pihole-eink:pihole-eink "$IMG" 2>/dev/null || true
chmod 0644 "$IMG"
install -m 0644 "$HERE/dashboard/rick-hole.js" "$JS"
python3 - "$INDEX" "$HERE/dashboard/card.html" <<'PY_DASH'
from pathlib import Path
import sys
index = Path(sys.argv[1])
card = Path(sys.argv[2]).read_text().rstrip() + "\n"
text = index.read_text()
if 'id="rick-hole-card"' not in text:
    marker = '<!-- Small boxes (Stat box) -->'
    if marker not in text:
        raise SystemExit('Could not find Pi-hole dashboard insertion marker')
    text = text.replace(marker, card + marker, 1)
if 'scripts/js/rick-hole.js' not in text:
    marker = 'scripts/js/index.js'
    pos = text.find(marker)
    if pos < 0:
        raise SystemExit('Could not find Pi-hole index.js script marker')
    end = text.find('</script>', pos)
    if end < 0:
        raise SystemExit('Could not find end of index.js script tag')
    end += len('</script>')
    text = text[:end] + '\n<script src="scripts/js/rick-hole.js"></script>' + text[end:]
index.write_text(text)
PY_DASH
echo "RICK-HOLE dashboard card installed. Backup: $BACKUP"
echo "Pi-hole Web updates may replace index.lp; re-run this script after an update if needed."
