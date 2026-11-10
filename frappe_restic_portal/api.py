"""Customer-site REST endpoints. All platform writes require a signed Press message."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import frappe

from frappe_restic_portal.crypto import verify_envelope

SNAP = re.compile(r"[0-9a-f]{64}\Z")
REQ = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")
STATES = {"Acknowledged", "Under Review", "Declined"}


def _operator():
    user = frappe.session.user
    if user in (None, "Guest") or (user != "Administrator" and "System Manager" not in frappe.get_roles(user)):
        frappe.throw("A site administrator is required", frappe.PermissionError)


def _snapshot(row):
    if not isinstance(row, dict) or set(row) != {"id", "time", "trigger"}:
        raise ValueError("Unexpected recovery point schema")
    if not SNAP.fullmatch(str(row["id"])):
        raise ValueError("Invalid recovery point ID")
    if not isinstance(row["time"], str) or not (10 <= len(row["time"]) <= 100):
        raise ValueError("Invalid recovery point time")
    parsed = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Snapshot timestamps must include time zone")
    if row["trigger"] not in ("manual", "scheduled", "unclassified"):
        raise ValueError("Unsupported recovery point type")
    return row


@frappe.whitelist(methods=["GET"])
def available_recovery_points():
    _operator()
    return frappe.get_all(
        "Restic Recovery Point",
        filters={"active": 1},
        fields=["name", "backup_time", "trigger", "verified_at"],
        order_by="backup_time desc", limit_page_length=500,
    )


@frappe.whitelist(methods=["GET"])
def my_restore_requests():
    _operator()
    return frappe.get_all(
        "Restic Restore Request",
        filters={"owner": frappe.session.user},
        fields=["name", "creation", "recovery_point", "request_state", "platform_job"],
        order_by="creation desc", limit_page_length=100,
    )


@frappe.whitelist(methods=["POST"])
def request_manual_deletion(snapshot_id, reason, confirmation):
    """Create a tenant-local, immutable request. No Restic or Press credentials here."""
    _operator()
    if confirmation != "DELETE MANUAL BACKUP":
        frappe.throw("Explicit deletion confirmation required", frappe.ValidationError)
    if not isinstance(snapshot_id, str) or not SNAP.fullmatch(snapshot_id):
        frappe.throw("Full snapshot identifier required", frappe.ValidationError)
    if not isinstance(reason, str) or not (1 <= len(reason.strip()) <= 500):
        frappe.throw("Reason required (maximum 500 characters)", frappe.ValidationError)
    point = frappe.get_doc("Restic Recovery Point", snapshot_id)
    if point.trigger != "manual" or not point.active:
        frappe.throw("Only available manual backups can be requested for deletion", frappe.PermissionError)
    verified = frappe.utils.get_datetime(point.verified_at)
    if not verified or frappe.utils.now_datetime() - verified > timedelta(hours=8):
        frappe.throw("Refresh the platform recovery-point inventory before requesting deletion", frappe.ValidationError)
    pending = frappe.db.exists("Restic Manual Delete Request", {
        "recovery_point": snapshot_id, "request_state": ["in", ["Requested", "Queued"]]
    })
    if pending:
        frappe.throw("A deletion request for this backup is already pending", frappe.ValidationError)
    try:
        frappe.flags.restic_manual_delete_internal = True
        doc = frappe.get_doc({
            "doctype": "Restic Manual Delete Request", "recovery_point": snapshot_id,
            "reason": reason.strip(), "requester": frappe.session.user,
            "requested_at": frappe.utils.now_datetime(), "request_state": "Requested",
        }).insert(ignore_permissions=True)
    finally:
        frappe.flags.restic_manual_delete_internal = False
    return {"name": doc.name, "request_state": "Requested"}

@frappe.whitelist(allow_guest=True, methods=["POST"])
def platform_exchange(envelope=None):
    """Signature-protected site-scoped API; no shared secret or vault access in tenant."""
    from frappe_restic_portal.crypto import validate_payload
    if frappe.request.method != "POST":
        frappe.throw("POST required", frappe.PermissionError)
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    public = Path(frappe.get_site_path("private", "restic-press-public.pem"))
    payload = validate_payload(verify_envelope(envelope, public), frappe.local.site)
    msg_id = payload["request_id"]
    if frappe.db.exists("Restic Platform Message", msg_id):
        frappe.throw("Replay rejected", frappe.PermissionError)
    data = payload["data"]
    action = payload["action"]
    if action == "inventory":
        snapshots = data.get("snapshots")
        if not isinstance(snapshots, list) or len(snapshots) > 500:
            raise ValueError("Invalid inventory")
        validated = [_snapshot(row) for row in snapshots]
        if len({r["id"] for r in validated}) != len(validated):
            raise ValueError("Duplicate recovery point")
        verified_at = frappe.utils.now_datetime()
        active = {r["id"] for r in validated}
        # Manage only platform-issued point records, never arbitrary DocTypes.
        for row in validated:
            if frappe.db.exists("Restic Recovery Point", row["id"]):
                frappe.db.set_value("Restic Recovery Point", row["id"],
                    {"backup_time": row["time"], "trigger": row["trigger"],
                     "active": 1, "verified_at": verified_at}, update_modified=False)
            else:
                frappe.get_doc({"doctype": "Restic Recovery Point",
                    "snapshot": row["id"], "backup_time": row["time"],
                    "trigger": row["trigger"], "active": 1,
                    "verified_at": verified_at}).insert(ignore_permissions=True)
        for name in frappe.get_all("Restic Recovery Point", fields=["name"], limit_page_length=10000):
            if name.name not in active:
                frappe.db.set_value("Restic Recovery Point", name.name,
                    "active", 0, update_modified=False)
        response = {"state": "InventorySynced", "count": len(validated)}
    elif action == "list":
        docs = frappe.get_all("Restic Restore Request",
            fields=["name", "creation", "owner", "recovery_point", "reason", "request_state", "platform_job"],
            order_by="creation desc", limit_page_length=200)
        response = {"state": "RequestsListed", "requests": docs}
    elif action == "status":
        name = data.get("name")
        state = data.get("state")
        if not isinstance(name, str) or not REQ.fullmatch(name) or state not in STATES:
            raise ValueError("Invalid request status update")
        if not frappe.db.exists("Restic Restore Request", name):
            frappe.throw("Restore request not found", frappe.DoesNotExistError)
        # Site admins have no DocType write rights. Only signed platform messages update status.
        frappe.db.set_value("Restic Restore Request", name, "request_state", state)
        response = {"state": "StatusUpdated", "name": name, "request_state": state}
    elif action == "delete_list":
        docs = frappe.get_all("Restic Manual Delete Request",
            fields=["name", "creation", "requester", "recovery_point", "reason", "request_state", "platform_request_id"],
            filters={"request_state": ["in", ["Requested", "Queued"]]},
            order_by="creation asc", limit_page_length=200)
        response = {"state": "DeletionRequestsListed", "requests": docs}
    elif action == "delete_status":
        name = data.get("name")
        state = data.get("state")
        snap = data.get("snapshot_id")
        request_id = data.get("platform_request_id")
        message = data.get("message") or ""
        if (not isinstance(name, str) or not REQ.fullmatch(name)
                or state not in {"Queued", "Deleted", "Failed", "Declined"}
                or not isinstance(snap, str) or not SNAP.fullmatch(snap)
                or (request_id is not None and (not isinstance(request_id, str)
                    or not re.fullmatch(r"[a-f0-9]{32}", request_id)))
                or not isinstance(message, str) or len(message) > 220):
            raise ValueError("Invalid deletion status message")
        if not frappe.db.exists("Restic Manual Delete Request", name):
            frappe.throw("Deletion request not found", frappe.DoesNotExistError)
        doc = frappe.get_doc("Restic Manual Delete Request", name)
        if doc.recovery_point != snap:
            raise ValueError("Deletion request snapshot mismatch")
        if state == "Queued" and doc.request_state != "Requested":
            raise ValueError("Deletion request already processed")
        if state in {"Deleted", "Failed"} and doc.request_state != "Queued":
            raise ValueError("Deletion receipt without prior queue acknowledgement")
        if state == "Declined" and doc.request_state != "Requested":
            raise ValueError("Cannot decline an already queued deletion")
        if doc.platform_request_id and doc.platform_request_id != request_id:
            raise ValueError("Deletion platform request mismatch")
        if state in {"Queued", "Deleted", "Failed"} and not request_id:
            raise ValueError("Platform request ID required")
        frappe.db.set_value("Restic Manual Delete Request", name, {
            "request_state": state,
            "platform_request_id": request_id or doc.platform_request_id,
            "last_error": message,
        })
        if state == "Deleted":
            frappe.db.set_value("Restic Recovery Point", snap, "active", 0, update_modified=False)
        response = {"state": "DeletionStatusUpdated", "name": name, "request_state": state}
    else:
        raise ValueError("Unknown platform action")
    frappe.get_doc({"doctype": "Restic Platform Message", "message_id": msg_id,
                    "action": action, "site": frappe.local.site}).insert(ignore_permissions=True)
    return {"site": frappe.local.site, "request_id": msg_id, **response}
