"""Press administrative bridge to Frappe customer-site restore requests.

Only site-scoped signed messages are accepted by tenant app. This module cannot
restore sites, approve F-node jobs or access Backup01 / Backup02 repositories.
"""
import base64
import json
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import frappe
import requests

from press.restic_restore_admin import _admin
from press.restic_restore_catalog import _result

DOMAIN = b"FRAPPE_RESTIC_SITE_PORTAL_V1\n"
PRESSKEY = Path("/home/frappe/.config/frappe-restic-policy/press-signing.key")
NAME = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")
STATES = {"Acknowledged", "Under Review", "Declined"}


def _sign(payload):
    if PRESSKEY.is_symlink() or not PRESSKEY.is_file():
        frappe.throw("Press signing key unavailable", frappe.ValidationError)
    content = DOMAIN + json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    with tempfile.TemporaryDirectory() as tmp:
        body = Path(tmp) / "body"
        body.write_bytes(content)
        cmd = ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(PRESSKEY), "-in", str(body)]
        signed = subprocess.run(cmd, capture_output=True, check=True, timeout=10)
        if len(signed.stdout) != 64:
            raise ValueError("Unexpected platform signature")
    return {"payload": payload, "signature": base64.b64encode(signed.stdout).decode("ascii")}


def _exchange(site, action, data):
    # This URL is derived only from a validated Site record in Press; never from customer input.
    _admin(site)
    message_id = uuid.uuid4().hex
    payload = {
        "format": "restic-site-portal-v1", "request_id": message_id,
        "action": action, "site": site,
        "created_at": datetime.now(timezone.utc).isoformat(), "data": data,
    }
    url = f"https://{site}/api/method/frappe_restic_portal.api.platform_exchange"
    response = requests.post(url, json={"envelope": json.dumps(_sign(payload))},
                             timeout=(5, 30), allow_redirects=False, verify=True)
    response.raise_for_status()
    decoded = response.json().get("message")
    if not isinstance(decoded, dict) or decoded.get("request_id") != message_id or decoded.get("site") != site:
        raise ValueError("Customer-site response identity mismatch")
    return decoded


@frappe.whitelist(methods=["POST"])
def sync_inventory(site):
    _admin(site)
    catalog = _result(site)
    inventory = catalog.get("inventory")
    if not inventory:
        frappe.throw("No signed Backup01 snapshot inventory; refresh in Press", frappe.ValidationError)
    completed = datetime.fromisoformat(inventory["completed_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) - completed > timedelta(hours=6):
        frappe.throw("Backup01 inventory is too old; refresh first", frappe.ValidationError)
    points = inventory["snapshots"]
    if len(points) > 500:
        frappe.throw("Snapshot inventory exceeds limit", frappe.ValidationError)
    return _exchange(site, "inventory", {"snapshots": points})


@frappe.whitelist(methods=["POST"])
def customer_requests(site):
    _admin(site)
    response = _exchange(site, "list", {})
    rows = response.get("requests")
    if response.get("state") != "RequestsListed" or not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("Invalid site restore request listing")
    # Do not treat customer request status as authorization to restore.
    for row in rows:
        if (not isinstance(row, dict) or not NAME.fullmatch(str(row.get("name", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("recovery_point", "")))):
            raise ValueError("Invalid customer request entry")
    return {"site": site, "requests": rows}


@frappe.whitelist(methods=["POST"])
def set_customer_request_state(site, name, state):
    _, actor = _admin(site)
    if not isinstance(name, str) or not NAME.fullmatch(name) or state not in STATES:
        frappe.throw("Invalid request or review status", frappe.ValidationError)
    result = _exchange(site, "status", {"name": name, "state": state})
    # Execution and snapshot preparation remain separate Press administrator actions.
    frappe.logger("restic_customer_requests").info(
        "Portal request %s on %s marked %s by %s", name, site, state, actor
    )
    return result
