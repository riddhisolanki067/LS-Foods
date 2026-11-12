// LS Foods — Task "Is Recurring": the checkbox starts an Auto Repeat for the task.
// Server side: ls_foods/task_access.py (keeps the box in step with the Auto Repeat).

frappe.ui.form.on("Task", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.custom_is_recurring) return;
		frappe.db
			.count("Auto Repeat", {
				reference_doctype: "Task",
				reference_document: frm.doc.name,
				disabled: 0,
			})
			.then((n) => {
				if (n) return;
				frm.dashboard.set_headline(__("Recurring task: set how often it repeats."));
				frm.add_custom_button(__("Set Up Repeat"), () => ls_new_repeat(frm));
			});
	},
	custom_is_recurring(frm) {
		if (frm.doc.custom_is_recurring && !frm.is_new()) {
			frm.save().then(() => ls_new_repeat(frm));
		}
	},
});

function ls_new_repeat(frm) {
	frappe.new_doc("Auto Repeat", {
		reference_doctype: "Task",
		reference_document: frm.doc.name,
	});
}
