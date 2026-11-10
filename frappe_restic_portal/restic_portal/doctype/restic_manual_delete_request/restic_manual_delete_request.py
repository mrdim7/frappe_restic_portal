"""Immutable customer manual deletion request. This DocType never deletes snapshots."""
import frappe
from frappe.model.document import Document


class ResticManualDeleteRequest(Document):
    def before_insert(self):
        if not getattr(frappe.flags, "restic_manual_delete_internal", False):
            frappe.throw("Use the confirmed manual deletion request action", frappe.PermissionError)

    def validate(self):
        if not self.is_new() and not getattr(frappe.flags, "restic_manual_delete_internal", False):
            frappe.throw("Deletion requests are immutable", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("Deletion requests are retained for audit", frappe.PermissionError)
