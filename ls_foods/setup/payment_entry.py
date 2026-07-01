# =========================================================================
# SERVER METHOD — creates the Journal Entry for a Salary Slip payment
#
# Where to put this:
#   Option A (no custom app): Setup > Customization > Server Script
#       -> New, Script Type = "API", Method = e.g. "create_salary_payment_entry"
#       -> paste the BODY of the function (Server Script runs as a snippet,
#          not a def, so adapt accordingly — see note at bottom of file).
#   Option B (custom app, recommended): put this whole file at
#       <your_app>/<your_app>/api.py  (or any module you like)
#       and update the client script's `method:` path to match, e.g.
#       "your_app.api.create_salary_payment_entry"
# =========================================================================

import frappe
from frappe import _
from frappe.utils import nowdate, flt


@frappe.whitelist()
def create_salary_payment_entry(salary_slip, payment_account):
    """
    Create a submitted-ready Journal Entry that pays out a Salary Slip's
    net pay from the selected `payment_account`.

    Debit  -> Payroll Payable Account (clears the liability), party = Employee
    Credit -> payment_account (the bank/cash account selected by the user)
    """

    if not payment_account:
        frappe.throw(_("Payment Account is required"))

    ss = frappe.get_doc("Salary Slip", salary_slip)

    if ss.docstatus != 1:
        frappe.throw(_("Salary Slip must be submitted before making a payment entry"))

    # --- Prevent duplicate payment entries for the same slip -------------
    existing = frappe.db.exists(
        "Journal Entry Account",
        {
            "reference_type": "Salary Slip",
            "reference_name": ss.name,
            "docstatus": ["!=", 2],
        },
    )
    if existing:
        frappe.throw(_("A Journal Entry already exists for Salary Slip {0}").format(ss.name))

    # --- Resolve the Payroll Payable account dynamically ------------------
    payroll_payable_account = ss.get("payroll_payable_account") or frappe.get_cached_value(
        "Company", ss.company, "default_payroll_payable_account"
    )

    if not payroll_payable_account:
        frappe.throw(
            _(
                "Payroll Payable Account is not set on the Salary Slip or as the "
                "Default Payroll Payable Account in Company {0}"
            ).format(ss.company)
        )

    if not flt(ss.net_pay):
        frappe.throw(_("Net Pay on Salary Slip {0} is zero").format(ss.name))

    # --- Build the Journal Entry, fully dynamic on company/currency -------
    company_currency = frappe.get_cached_value("Company", ss.company, "default_currency")

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = ss.company
    je.posting_date = nowdate()
    je.multi_currency = 0
    je.user_remark = _("Payment against Salary Slip {0} for Employee {1}").format(
        ss.name, ss.employee_name
    )

    # Debit: clear the payroll payable liability for this employee
    je.append(
        "accounts",
        {
            "account": payroll_payable_account,
            "debit_in_account_currency": flt(ss.net_pay),
            "credit_in_account_currency": 0,
            "party_type": "Employee",
            "party": ss.employee,
            # "reference_type": "Salary Slip",
            # "reference_name": ss.name,
            "account_currency": company_currency,
        },
    )

    # Credit: the account the user selected in the dialog
    je.append(
        "accounts",
        {
            "account": payment_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": flt(ss.net_pay),
            # "reference_type": "Salary Slip",
            # "reference_name": ss.name,
            "account_currency": company_currency,
        },
    )

    je.insert(ignore_permissions=True)

    # Uncomment the next line if you want the JE auto-submitted instead of
    # left as a draft for the accountant to review:
    je.submit()

    return je.name

def set_net_pay_in_words(doc, method):
    words = frappe.utils.money_in_words(doc.net_pay, doc.currency)
    # Remove only the capitalized "And" used within the number itself,
    # but keep the lowercase "and" that joins whole and decimal parts
    words = re.sub(r'\bAnd\b', '', words)
    # collapse any double spaces left behind
    words = re.sub(r'\s+', ' ', words).strip()
    doc.custom_total_in_words = words

# -------------------------------------------------------------------------
# NOTE if using "Server Script" (Option A) instead of a custom app:
# Server Scripts of type "API" don't use @frappe.whitelist() / def — they
# run as a script body with `frappe.flags.args` and you set the result via
# `frappe.response`. Example adaptation:
#
#   salary_slip = frappe.flags.args.salary_slip
#   payment_account = frappe.flags.args.payment_account
#   ... (same logic as above, using frappe.get_doc etc.) ...
#   frappe.response["message"] = je.name
#
# Then in the client script call method: "create_salary_payment_entry"
# (just the API method name, no dotted path).
# -------------------------------------------------------------------------