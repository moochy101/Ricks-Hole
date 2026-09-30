#!/usr/bin/env bash
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/config/pihole-eink.example.json"
DST=/etc/pihole-eink.json
read -rsp "Pi-hole application/web password: " PW; echo
read -rp "Physical display rotation [180]: " ROT
ROT=${ROT:-180}
python3 - "$SRC" "$DST" "$PW" "$ROT" <<'PY_CFG'
from pathlib import Path
import json, sys
src, dst, pw, rot = sys.argv[1:]
data = json.loads(Path(src).read_text())
data['password'] = pw
data['rotation'] = int(rot)
Path(dst).write_text(json.dumps(data, indent=2) + '\n')
PY_CFG
chmod 0600 "$DST"
echo "Wrote $DST (mode 0600)."
