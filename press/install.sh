#!/bin/bash
set -Eeuo pipefail
[[ $EUID == 0 && $(hostname -s) == frappe-press01 ]] || { echo 'Press01 root only' >&2; exit 1; }
ROOT=$(cd "$(dirname "$0")" && pwd)
PRESS=/home/frappe/press-bench/apps/press
UI="$PRESS/dashboard/src/components/site/SiteResticRestore.vue"
[[ -f "$PRESS/press/restic_restore_catalog.py" && -f "$UI" && ! -L "$UI" ]] || { echo 'Prerequisite Phase 2C.7C missing' >&2; exit 1; }
if [ ! -f "$PRESS/press/restic_customer_portal_admin.py" ]; then
  install -m 0644 -o frappe -g frappe "$ROOT/restic_customer_portal_admin.py" "$PRESS/press/restic_customer_portal_admin.py"
else
  cp -a "$PRESS/press/restic_customer_portal_admin.py" "$PRESS/press/restic_customer_portal_admin.py.before-2d1.$(date +%s)"
  install -m 0644 -o frappe -g frappe "$ROOT/restic_customer_portal_admin.py" "$PRESS/press/restic_customer_portal_admin.py"
fi
if ! grep -q 'Phase 2D.1: customer restore requests' "$UI"; then
  BAK="$UI.before-2d1.$(date +%s)"
  cp -a "$UI" "$BAK"
  python3 "$ROOT/patch_restore_ui.py" "$UI" || { cp -a "$BAK" "$UI"; exit 1; }
  chown --reference="$BAK" "$UI"; chmod --reference="$BAK" "$UI"
fi
python3 -m py_compile "$PRESS/press/restic_customer_portal_admin.py"
echo 'PASS: Customer restore request Press bridge installed (read-only/live gate unchanged)'
echo 'NEXT: rebuild dashboard as frappe; restart Press web only'
