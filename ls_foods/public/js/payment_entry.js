// =========================================================================
// CLIENT SCRIPT — DocType: Salary Slip
// Where to put this:
//   Option A (no custom app): Setup > Customization > Client Script
//       -> New, DocType = "Salary Slip", Script Type = "Client", paste this.
//   Option B (custom app): <your_app>/public/js/salary_slip.js
//       and add it to hooks.py under doctype_js = {"Salary Slip": "public/js/salary_slip.js"}
// =========================================================================

frappe.ui.form.on('Salary Slip', {
    refresh: function (frm) {
        console.log('Salary Slip refresh triggered for: ' + frm.doc.name);
        // Only show on submitted slips
        if (frm.doc.docstatus !== 1) return;
        console.log('Checking if payment entry exists for Salary Slip: ' + frm.doc.name);
        // Avoid duplicate payments — check if a JE already exists for this slip
        frappe.call({
            method: 'frappe.client.get_count',
            args: {
                doctype: 'Salary Slip',
                filters: {
                    journal_entry: ['is', 'set'],
                    name: frm.doc.name,
                   
                }
            },
            callback: function (r) {
                if (r.message) {
                    console.log('Payment entry can be made');
                    frm.add_custom_button(__('Make Payment Entry'), function () {
                        show_payment_dialog(frm);
                    }, __('Payment'));
                } else {
                    // Already paid - show indicator instead
                    frm.dashboard.add_indicator(__('Payment Entry Already Created'), 'green');
                }
            }
        });
    }
});

function show_payment_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Make Payment Entry'),
        fields: [
            {
                label: __('Payment Account'),
                fieldname: 'payment_account',
                fieldtype: 'Link',
                options: 'Account',
                reqd: 1,
                description: __('Account from which the salary amount will be paid (e.g. Bank or Cash account)'),
                get_query: function () {
                    return {
                        filters: {
                            company: frm.doc.company,
                            is_group: 0
                        }
                    };
                }
            },
            {
                fieldtype: 'Column Break'
            },
            {
                label: __('Net Pay'),
                fieldname: 'net_pay',
                fieldtype: 'Currency',
                default: frm.doc.net_pay,
                read_only: 1,
                options: 'currency'
            }
        ],
        primary_action_label: __('Proceed'),
        primary_action(values) {
            d.disable_primary_action();
            frappe.call({
                method: 'ls_foods.setup.payment_entry.create_salary_payment_entry',
                // ^^ update this dotted path to wherever you put server_create_payment_entry.py
                //    e.g. "<your_app>.api.create_salary_payment_entry"
                args: {
                    salary_slip: frm.doc.name,
                    payment_account: values.payment_account
                },
                freeze: true,
                freeze_message: __('Creating Journal Entry...'),
                callback: function (r) {
                    d.enable_primary_action();
                    if (r.message) {
                        d.hide();
                        frappe.show_alert({
                            message: __('Journal Entry {0} created', [r.message]),
                            indicator: 'green'
                        });
                        frappe.set_route('Form', 'Journal Entry', r.message);
                    }
                },
                error: function () {
                    d.enable_primary_action();
                }
            });
        }
    });
    d.show();
}