frappe.ui.form.on('Restic Recovery Point', {
  refresh(frm) {
    if (frm.is_new() || frm.doc.trigger !== 'manual' || !frm.doc.active ||
        !frappe.user.has_role('System Manager')) return;
    frm.add_custom_button(__('Request Manual Backup Deletion'), () => {
      frappe.prompt([
        {fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason'), reqd: 1},
        {fieldname: 'confirmation', fieldtype: 'Data', label: __('Type DELETE MANUAL BACKUP'), reqd: 1},
      ], (values) => {
        if (values.confirmation !== 'DELETE MANUAL BACKUP') {
          frappe.msgprint(__('The confirmation phrase must match exactly.'));
          return;
        }
        frappe.call({
          method: 'frappe_restic_portal.api.request_manual_deletion',
          args: {snapshot_id: frm.doc.name, reason: values.reason, confirmation: values.confirmation},
          freeze: true,
          callback(r) {
            if (r.message && r.message.name) {
              frappe.show_alert({message: __('Deletion request submitted for platform processing'), indicator: 'blue'});
              frappe.set_route('Form', 'Restic Manual Delete Request', r.message.name);
            }
          }
        });
      }, __('Request deletion of this manual backup'), __('Submit request'));
    });
    frm.set_intro(__('Deletion is a separate audited request. Scheduled recovery points cannot be deleted here.'), 'orange');
  }
});
