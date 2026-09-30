#!/usr/bin/env bash
set -euo pipefail
ADMIN=/var/www/html/admin
INDEX="$ADMIN/index.lp"
BACKUP="$ADMIN/index.lp.rick-hole-backup"
if [[ -f "$BACKUP" ]]; then
  cp -a "$BACKUP" "$INDEX"
  echo "Dashboard restored from $BACKUP"
else
  echo "No dashboard backup found at $BACKUP" >&2
  exit 1
fi
