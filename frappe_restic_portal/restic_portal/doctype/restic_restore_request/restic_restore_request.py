import re
from datetime import datetime, timedelta

import frappe
from frappe.model.document import Document


class ResticRestoreRequest(Document):
    def before_insert(self):
        if frappe.session.user in (None, "Guest") or (frappe.session.user != "Administrator"
            and "System Manager" not in frappe.get_roles(frappe.session.user)):
            frappe.throw("Site administrator required", frappe.PermissionError)
        self.requester = frappe.session.user
        self.request_state = "Requested"
        self.requested_at = frappe.utils.now_datetime()
        if len(self.reason or "") > 500 or not (self.reason or "").strip():
            frappe.throw("Reason required (maximum 500 characters)", frappe.ValidationError)
        if not re.fullmatch(r"[0-9a-f]{64}", str(self.recovery_point)):
            frappe.throw("Invalid recovery point", frappe.ValidationError)
        point = frappe.get_doc("Restic Recovery Point", self.recovery_point)
        if not point.active:
            frappe.throw("Recovery point is not currently available", frappe.ValidationError)
        verified = frappe.utils.get_datetime(point.verified_at)
        if frappe.utils.now_datetime() - verified > timedelta(hours=8):
            frappe.throw("Recovery points must be refreshed by the platform", frappe.ValidationError)

    def validate(self):
        if not self.is_new() and frappe.session.user != "Administrator":
            frappe.throw("Restore requests are immutable", frappe.PermissionError)
