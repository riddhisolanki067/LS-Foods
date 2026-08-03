# =========================================================================
# LS Foods — Salary Slip payment Journal Entry + Hours Worked guard.
#
# Wired in hooks.py:
#   doc_events["Salary Slip"]["validate"]  -> set_net_pay_in_words
#   doc_events["Salary Slip"]["before_submit"] -> validate_hours_worked
#   doctype_js["Salary Slip"] -> public/js/payment_entry.js  (calls the
#       whitelisted create_salary_payment_entry / update_payment_date below)
# =========================================================================

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate


@frappe.whitelist()
def create_salary_payment_entry(salary_slip, payment_account, payment_date=None, submit_je=1):
    """
    Create the Journal Entry that pays out a Salary Slip's net pay from the
    selected `payment_account`.

    Debit  -> Payroll Payable Account (clears the liability), party = Employee
    Credit -> payment_account (the bank/cash account selected by the user)

    `payment_date` becomes the JE's posting date — i.e. the date the employee was
    actually paid, which is what lands in the bank reconciliation and the GL.
    It used to be hardcoded to today, so a slip entered late was posted on the
    wrong day. Defaults to today when not supplied.

    `submit_je=0` leaves the Journal Entry as a DRAFT. That is the supported way
    to correct a payment date after the fact: a submitted JE's posting date is
    locked by ERPNext (changing it would silently move a posted GL entry between
    periods), so an already-submitted payment must be cancelled and amended.
    """

    if not payment_account:
        frappe.throw(_("Payment Account is required"))

    ss = frappe.get_doc("Salary Slip", salary_slip)

    if ss.docstatus != 1:
        frappe.throw(_("Salary Slip must be submitted before making a payment entry"))

    # --- Prevent duplicate payment entries for the same slip -------------
    # NOTE: the slip's standard `journal_entry` field holds the ACCRUAL entry
    # posted by ls_foods.payroll, not the payment. The payment JE is tracked
    # separately on custom_payment_journal_entry.
    existing = ss.get("custom_payment_journal_entry")
    if existing and frappe.db.get_value("Journal Entry", existing, "docstatus") != 2:
        frappe.throw(
            _("Payment Journal Entry {0} already exists for Salary Slip {1}. Cancel it first.").format(
                frappe.utils.get_link_to_form("Journal Entry", existing), ss.name
            )
        )

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

    payment_date = getdate(payment_date or nowdate())

    # Paying before the period the slip covers is almost always a typo.
    if ss.end_date and payment_date < getdate(ss.start_date):
        frappe.throw(
            _("Payment Date {0} is before the pay period starts ({1}).").format(
                frappe.format(payment_date, "Date"), frappe.format(ss.start_date, "Date")
            )
        )

    # --- Build the Journal Entry, fully dynamic on company/currency -------
    company_currency = frappe.get_cached_value("Company", ss.company, "default_currency")

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = ss.company
    je.posting_date = payment_date
    je.multi_currency = 0
    # NOTE: deliberately NOT setting cheque_date — ERPNext makes Reference No
    # mandatory the moment a Reference Date is present, which would block the
    # submit for anyone paying by transfer rather than cheque.
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
            # NOTE: Journal Entry Account.reference_type has no "Salary Slip"
            # option, so the link is carried the other way — on the slip's
            # custom_payment_journal_entry field — plus the remark below.
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
            "account_currency": company_currency,
        },
    )

    je.flags.ignore_permissions = True
    je.insert()

    if cint(submit_je):
        je.submit()

    # Track the payment separately from the accrual JE so the "Make Payment
    # Entry" button can tell whether this slip has actually been paid.
    ss.db_set("custom_payment_journal_entry", je.name, update_modified=False)
    ss.db_set("custom_payment_date", payment_date, update_modified=False)

    return je.name


@frappe.whitelist()
def update_payment_date(salary_slip, payment_date):
    """Change the payment date on a slip whose payment JE is still a DRAFT.

    Once the JE is submitted its posting date is locked — that is deliberate:
    moving a posted GL entry to another date (and possibly another period) behind
    the user's back is an accounting-integrity problem. In that case the user is
    told to cancel and amend.
    """
    if not payment_date:
        frappe.throw(_("Payment Date is required"))

    ss = frappe.get_doc("Salary Slip", salary_slip)
    je_name = ss.get("custom_payment_journal_entry")

    if not je_name or not frappe.db.exists("Journal Entry", je_name):
        frappe.throw(_("No payment Journal Entry found for Salary Slip {0}").format(ss.name))

    je = frappe.get_doc("Journal Entry", je_name)

    if je.docstatus == 1:
        frappe.throw(
            _(
                "Journal Entry {0} is already submitted, so its posting date is locked. "
                "Cancel and amend it to change the payment date."
            ).format(frappe.utils.get_link_to_form("Journal Entry", je_name))
        )
    if je.docstatus == 2:
        frappe.throw(_("Journal Entry {0} is cancelled.").format(je_name))

    payment_date = getdate(payment_date)
    je.posting_date = payment_date
    if je.cheque_date:
        je.cheque_date = payment_date
    je.flags.ignore_permissions = True
    je.save()

    ss.db_set("custom_payment_date", payment_date, update_modified=False)

    return je.name


# =========================================================================
#  Hours Worked guard
# =========================================================================


def validate_hours_worked(doc, method=None):
    """Block submitting a Salary Slip with no Hours Worked.

    Why a hard block and not just a warning: the Hourly Wage salary component's
    formula is `custom_hours_worked * custom_rate_per_hour`, so a blank value
    does not merely leave a field empty — it produces a slip with $0 gross pay,
    $0 withholding and a $0 pay stub, and the accrual Journal Entry posts
    nothing. That is far harder to unpick after the fact than being stopped here.

    The form also pops a warning the moment you save a draft (see
    public/js/payment_entry.js), so this only ever fires as a last line of
    defence — or on an API/import path where no form is involved.
    """
    if flt(doc.get("custom_hours_worked")) > 0:
        return

    frappe.throw(
        _(
            "<b>Hours Worked is empty.</b><br><br>"
            "Enter the hours for this pay period on the <b>Payment Days</b> tab "
            "before submitting — pay is calculated as Hours Worked x Rate per Hour, "
            "so submitting now would produce a slip with zero gross pay."
        ),
        title=_("Hours Worked Missing"),
    )


def set_net_pay_in_words(doc, method=None):
    words = frappe.utils.money_in_words(flt(doc.net_pay), doc.currency)
    # Remove only the capitalized "And" used within the number itself,
    # but keep the lowercase "and" that joins whole and decimal parts
    words = re.sub(r'\bAnd\b', '', words)
    # collapse any double spaces left behind
    words = re.sub(r'\s+', ' ', words).strip()
    doc.custom_total_in_words = words
