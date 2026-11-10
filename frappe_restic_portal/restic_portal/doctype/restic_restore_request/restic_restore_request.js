frappe.ui.form.on('Restic Restore Request', {
  setup(frm) {
    frm.set_query('recovery_point', () => ({ filters: { active: 1 } }));
  },
  refresh(frm) {
    frm.set_intro(__('This submits a request for platform review. It does not execute a restore.'), 'blue');
    if (!frm.is_new()) frm.disable_save();
  },
});
