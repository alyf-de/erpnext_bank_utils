# -*- coding: utf-8 -*-
# Copyright (c) 2017-2020, libracore and contributors
# License: AGPL v3. See LICENCE
import ast
import hashlib
from bs4 import BeautifulSoup

import frappe
from frappe import _


def match_by_amount(amount):
    """Try to match the amount to an open Sales Invoice.

    Return the sales invoice name or None.
    """
    open_invoices = frappe.get_list('Sales Invoice', {'docstatus': 1, 'grand_total': amount, 'status': ('!=', 'Paid')})
    return open_invoices[0].name if len(open_invoices) == 1 else None


def match_by_comment(comment):
    """Try to match the comments to an open Sales Invoice

    Return the Sales Invoice name or None.
    """
    open_invoices = frappe.get_list('Sales Invoice', {'docstatus': 1, 'status': ('!=', 'Paid')})
    names_in_comment = [sinv.name for sinv in open_invoices if sinv.name in comment]
    return names_in_comment[0] if len(names_in_comment) == 1 else None


def get_unpaid_sales_invoices_by_customer(customer):
    """Find unpaid Sales Invoices for a Customer

    Return a dict (name) of sales invoice references or None.
    """
    return frappe.get_list('Sales Invoice', {'docstatus': 1, 'customer': customer, 'status': ('!=', 'Paid')})   


def create_payment_entry(date, to_account, received_amount, transaction_id, remarks, auto_submit=False):
    company = frappe.get_value("Account", to_account, "company")
    default_customer = frappe.get_value("Bank Utils Defaults", {"company": company}, "default_customer")

    if not frappe.db.exists('Payment Entry', {'reference_no': transaction_id}):
        # create new payment entry
        new_payment_entry = frappe.get_doc({'doctype': 'Payment Entry'})
        new_payment_entry.payment_type = "Receive"
        new_payment_entry.party_type = "Customer"
        new_payment_entry.party = default_customer
        # date is in DD.MM.YYYY
        new_payment_entry.posting_date = date
        new_payment_entry.paid_to = to_account
        new_payment_entry.received_amount = received_amount
        new_payment_entry.paid_amount = received_amount
        new_payment_entry.reference_no = transaction_id
        new_payment_entry.reference_date = date
        new_payment_entry.remarks = remarks
        inserted_payment_entry = new_payment_entry.insert()

        if auto_submit:
            new_payment_entry.submit()

        frappe.db.commit()

        return inserted_payment_entry


def create_reference(payment_entry, sales_invoice):
    """Create the reference record in a Payment Entry."""
    reference_entry = frappe.get_doc({"doctype": "Payment Entry Reference"})
    reference_entry.parent = payment_entry
    reference_entry.parentfield = "references"
    reference_entry.parenttype = "Payment Entry"
    reference_entry.reference_doctype = "Sales Invoice"
    reference_entry.reference_name = sales_invoice
    reference_entry.total_amount = frappe.get_value("Sales Invoice", sales_invoice, "base_grand_total")
    reference_entry.outstanding_amount = frappe.get_value("Sales Invoice", sales_invoice, "outstanding_amount")
    paid_amount = frappe.get_value("Payment Entry", payment_entry, "paid_amount")

    reference_entry.allocated_amount = min(
        paid_amount, reference_entry.outstanding_amount
    )
    reference_entry.insert()


def log(comment):
	new_comment = frappe.get_doc({"doctype": "Log"})
	new_comment.comment = comment
	new_comment.insert()
	return new_comment


@frappe.whitelist()
def get_defaults(bank_account):
    company = frappe.get_value("Account", bank_account, "company")
    defaults = frappe.get_doc("Bank Utils Defaults", {"company": company})
    default_payable_account, default_receivable_account = frappe.get_value('Company', company,
        [
            'default_payable_account',
            'default_receivable_account'
        ]
    )

    return {
        "company": company,
        "default_customer": defaults.default_customer,
        "default_supplier": defaults.default_supplier,
        "intermediate_account": defaults.intermediate_account,
        "default_payable_account": default_payable_account,
        "default_receivable_account": default_receivable_account
    }


@frappe.whitelist()
def get_bank_accounts():
    bank_accounts = frappe.get_list('Account', filters={
        'account_type': 'Bank',
        'is_group': 0,
        'disabled': 0
    }, fields=['name'], order_by='account_number')
    return [account.name for account in bank_accounts]


@frappe.whitelist()
def read_camt053(content):
    soup = BeautifulSoup(content, 'lxml')
    entries = soup.find_all('ntry')

    return read_camt_transactions(entries)


def read_camt_transactions(transaction_entries):
    txns = []
    for entry in transaction_entries:
        date = entry.bookgdt.dt.get_text()
        transactions = entry.find_all('txdtls')
        # fetch entry amount as fallback
        entry_amount = float(entry.amt.get_text())
        entry_currency = entry.amt['ccy']
        # fetch global account service reference
        try:
            global_account_service_reference = entry.acctsvcrref.get_text()
        except:
            global_account_service_reference = ""
        transaction_count = 0
        if transactions and len(transactions) > 0:
            for transaction in transactions:
                transaction_count += 1
                # --- find transaction type: paid or received: (DBIT: paid, CRDT: received)
                try:
                    credit_debit = transaction.cdtdbtind.get_text()
                except:
                    # fallback to entry indicator
                    credit_debit = entry.cdtdbtind.get_text()

                # --- find unique reference
                try:
                    # try to use the account service reference 
                    # unique_reference = transaction.refs.acctsvcrref.get_text()
                    unique_reference = transaction.refs.endtoendid.get_text()
                except:
                    # fallback: use tx id
                    try:
                        unique_reference = transaction.txid.get_text()
                    except:
                        # fallback to pmtinfid
                        try:
                            unique_reference = transaction.pmtinfid.get_text()
                        except:
                            # fallback to group account service reference plus transaction_count
                            if global_account_service_reference != "":
                                unique_reference = "{0}-{1}".format(global_account_service_reference, transaction_count)
                            else:
                                # fallback to ustrd (do not use)
                                # unique_reference = transaction.ustrd.get_text()
                                # fallback to hash
                                amount = transaction.amt.get_text()
                                party = transaction.nm.get_text()
                                code = "{0}:{1}:{2}".format(date, amount, party)
                                frappe.log_error("Code: {0}".format(code))
                                unique_reference = hashlib.md5(code.encode("utf-8")).hexdigest()
                # --- find amount and currency
                try:
                    # try to find as <TxAmt>
                    amount = float(transaction.txamt.amt.get_text())
                    currency = transaction.txamt.amt['ccy']
                except:
                    try:
                        # fallback to pure <AMT>
                        amount = float(transaction.amt.get_text())
                        currency = transaction.amt['ccy']
                    except:
                        # fallback to amount from entry level
                        amount = entry_amount
                        currency = entry_currency
                try:
                    # --- find party IBAN
                    if credit_debit == "DBIT":
                        # use RltdPties:Cdtr
                        party_soup = transaction.rltdpties.cdtr
                        try:
                            party_iban = transaction.cdtracct.id.iban.get_text()
                        except:
                            party_iban = ""
                    else:
                        # CRDT: use RltdPties:Dbtr
                        party_soup = transaction.rltdpties.dbtr
                        try:
                            party_iban = transaction.dbtracct.id.iban.get_text()
                        except:
                            party_iban = ""
                    try:
                        party_name = party_soup.nm.get_text()
                        if party_soup.strtnm:
                            # parse by street name, ...
                            try:
                                street = party_soup.strtnm.get_text()
                                try:
                                    street_number = party_soup.bldgnb.get_text()
                                    address_line1 = "{0} {1}".format(street, street_number)
                                except:
                                    address_line1 = street
                                    
                            except:
                                address_line1 = ""
                            try:
                                plz = party_soup.pstcd.get_text()
                            except:
                                plz = ""
                            try:
                                town = party_soup.twnnm.get_text()
                            except:
                                town = ""
                            address_line2 = "{0} {1}".format(plz, town)
                        else:
                            # parse by address lines
                            address_lines = party_soup.find_all("adrline")
                            if len(address_lines) == 2:
                                address_line1 = address_lines[0].get_text()
                                address_line2 = address_lines[1].get_text()
                            else:
                                # in case no address is provided
                                address_line1 = ""
                                address_line2 = ""                      
                    except:
                        # party is not defined (e.g. DBIT from Bank)
                        try:
                            # this is a fallback for ZKB which does not provide nm tag, but address line
                            address_lines = party_soup.find_all("adrline")
                            party_name = address_lines[0].get_text()
                        except:
                            party_name = "not found"
                        address_line1 = ""
                        address_line2 = ""
                    try:
                        country = party_soup.ctry.get_text()
                    except:
                        country = ""
                    if (address_line1 != "") and (address_line2 != ""):
                        party_address = "{0}, {1}, {2}".format(
                            address_line1,
                            address_line2,
                            country)
                    elif (address_line1 != ""):
                        party_address = "{0}, {1}".format(address_line1, country)
                    else:
                        party_address = "{0}".format(country)
                except:
                    # key related parties not found / no customer info
                    party_name = ""
                    party_address = ""
                    party_iban = ""

                try:
                    # try to find ESR reference
                    transaction_reference = transaction.rmtinf.strd.cdtrrefinf.ref.get_text()
                except:
                    try:
                        # try to find a user-defined reference (e.g. SINV.)
                        transaction_reference = transaction.rmtinf.ustrd.get_text()
                    except:
                        try:
                            # try to find an end-to-end ID
                            transaction_reference = transaction.endtoendid.get_text() 
                        except:
                            try:
                                # try to find an AddtlTxInf
                                transaction_reference = transaction.addtltxinf.get_text() 
                            except:
                                transaction_reference = unique_reference

                # check if this transaction is already recorded
                match_payment_entry = frappe.get_all('Payment Entry', filters={'reference_no': unique_reference}, fields=['name'])
                if match_payment_entry:
                    frappe.log_error("Transaction {0} is already imported in {1}.".format(unique_reference, match_payment_entry[0]['name']))
                else:
                    # try to find matching parties & invoices
                    party_match = None
                    employee_match = None
                    invoice_matches = None
                    expense_matches = None
                    matched_amount = 0.0
                    if credit_debit == "DBIT":
                        # suppliers 
                        match_suppliers = frappe.get_all("Supplier", 
                            filters={'supplier_name': party_name, 'disabled': 0}, 
                            fields=['name'])
                        if match_suppliers:
                            party_match = match_suppliers[0]['name']
                            # restrict pins to supplier
                            possible_pinvs = frappe.get_all("Purchase Invoice",
                                filters=[['docstatus', '=', 1], ['outstanding_amount', '>', 0], ['supplier', '=', party_match]],
                                fields=['name', 'supplier', 'outstanding_amount', 'bill_no'])
                        else:
                            # purchase invoices
                            possible_pinvs = frappe.get_all("Purchase Invoice", 
                                filters=[['docstatus', '=', 1], ['outstanding_amount', '>', 0]], 
                                fields=['name', 'supplier', 'outstanding_amount', 'bill_no'])
                        if possible_pinvs:
                            invoice_matches = []
                            for pinv in possible_pinvs:
                                if pinv['name'] in transaction_reference or (pinv['bill_no'] or pinv['name']) in transaction_reference:
                                    invoice_matches.append(pinv['name'])
                                    # override party match in case there is one from the sales invoice
                                    party_match = pinv['supplier']
                                    # add total matched amount
                                    matched_amount += float(pinv['outstanding_amount'])
                        # employees 
                        match_employees = frappe.get_all("Employee", 
                            filters={'employee_name': party_name, 'status': 'active'}, 
                            fields=['name'])
                        if match_employees:
                            employee_match = match_employees[0]['name']
                        # expense claims
                        possible_expenses = frappe.get_all("Expense Claim", 
                            filters=[['docstatus', '=', 1], ['status', '=', 'Unpaid']], 
                            fields=['name', 'employee', 'total_claimed_amount'])
                        if possible_expenses:
                            expense_matches = []
                            for exp in possible_expenses:
                                if exp['name'] in transaction_reference:
                                    expense_matches.append(exp['name'])
                                    # override party match in case there is one from the sales invoice
                                    employee_match = exp['employee']
                                    # add total matched amount
                                    matched_amount += float(exp['total_claimed_amount'])            
                    else:
                        # customers & sales invoices
                        match_customers = frappe.get_all("Customer", filters={'customer_name': party_name, 'disabled': 0}, fields=['name'])
                        if match_customers:
                            party_match = match_customers[0]['name']
                        # sales invoices
                        possible_sinvs = frappe.get_all("Sales Invoice", filters=[['outstanding_amount', '>', 0]], fields=['name', 'customer', 'outstanding_amount'])
                        if possible_sinvs:
                            invoice_matches = []
                            for sinv in possible_sinvs:
                                if sinv['name'] in transaction_reference:
                                    invoice_matches.append(sinv['name'])
                                    # override party match in case there is one from the sales invoice
                                    party_match = sinv['customer']
                                    # add total matched amount
                                    matched_amount += float(sinv['outstanding_amount'])
                                    
                    # reset invoice matches in case there are no matches
                    try:
                        if len(invoice_matches) == 0:
                            invoice_matches = None
                        if len(expense_matches) == 0:
                            expense_matches = None                            
                    except:
                        pass                                                                                                
                    new_txn = {
                        'txid': len(txns),
                        'date': date,
                        'currency': currency,
                        'amount': amount,
                        'party_name': party_name,
                        'party_address': party_address,
                        'credit_debit': credit_debit,
                        'party_iban': party_iban,
                        'unique_reference': unique_reference,
                        'transaction_reference': transaction_reference,
                        'party_match': party_match,
                        'invoice_matches': invoice_matches,
                        'matched_amount': matched_amount,
                        'employee_match': employee_match,
                        'expense_matches': expense_matches
                    }
                    txns.append(new_txn)
        else:
            # transaction without TxDtls: occurs at CS when transaction is from a pain.001 instruction
            # get unique ID
            try:
                unique_reference = entry.acctsvcrref.get_text()
            except:
                # fallback: use tx id
                try:
                    unique_reference = entry.txid.get_text()
                except:
                    # fallback to pmtinfid
                    try:
                        unique_reference = entry.pmtinfid.get_text()
                    except:
                        # fallback to hash
                        code = "{0}:{1}:{2}".format(date, entry_currency, entry_amount)
                        unique_reference = hashlib.md5(code.encode("utf-8")).hexdigest()
            # check if this transaction is already recorded
            match_payment_entry = frappe.get_all('Payment Entry', filters={'reference_no': unique_reference}, fields=['name'])
            if match_payment_entry:
                frappe.log_error("Transaction {0} is already imported in {1}.".format(unique_reference, match_payment_entry[0]['name']))
            else:
                # --- find transaction type: paid or received: (DBIT: paid, CRDT: received)
                credit_debit = entry.cdtdbtind.get_text()
                # find payment instruction ID
                try:
                    payment_instruction_id = entry.pmtinfid.get_text()     # instruction ID, PMTINF-[payment proposal]-row
                    payment_instruction_fields = payment_instruction_id.split("-")
                    payment_instruction_row = int(payment_instruction_fields[-1]) + 1
                    payment_proposal_id = payment_instruction_fields[1]
                    # find original instruction record
                    payment_proposal_payments = frappe.get_all("Payment Proposal Payment", 
                        filters={'parent': payment_proposal_id, 'idx': payment_instruction_row},
                        fields=['receiver', 'receiver_address_line1', 'receiver_address_line2', 'iban', 'reference'])
                    # suppliers 
                    party_match = None
                    if payment_proposal_payments:
                        match_suppliers = frappe.get_all("Supplier", filters={'supplier_name': payment_proposal_payments[0]['receiver']}, 
                            fields=['name'])
                        if match_suppliers:
                            party_match = match_suppliers[0]['name']
                    # purchase invoices 
                    invoice_match = None
                    matched_amount = 0
                    if payment_proposal_payments:
                        match_invoices = frappe.get_all("Purchase Invoice", 
                            filters=[['name', '=', payment_proposal_payments[0]['reference']], ['outstanding_amount', '>', 0]], 
                            fields=['name', 'grand_total'])
                        if match_invoices:
                            invoice_match = [match_invoices[0]['name']]
                            matched_amount = match_invoices[0]['grand_total']
                    if payment_proposal_payments:
                        new_txn = {
                            'txid': len(txns),
                            'date': date,
                            'currency': entry_currency,
                            'amount': entry_amount,
                            'party_name': payment_proposal_payments[0]['receiver'],
                            'party_address': "{0}, {1}".format(
                                payment_proposal_payments[0]['receiver_address_line1'], 
                                payment_proposal_payments[0]['receiver_address_line2']),
                            'credit_debit': credit_debit,
                            'party_iban': payment_proposal_payments[0]['iban'],
                            'unique_reference': unique_reference,
                            'transaction_reference': payment_proposal_payments[0]['reference'],
                            'party_match': party_match,
                            'invoice_matches': invoice_match,
                            'matched_amount': matched_amount
                        }
                        txns.append(new_txn)
                    else:
                        # not matched against payment instruction
                        new_txn = {
                            'txid': len(txns),
                            'date': date,
                            'currency': entry_currency,
                            'amount': entry_amount,
                            'party_name': "???",
                            'party_address': "???",
                            'credit_debit': credit_debit,
                            'party_iban': "???",
                            'unique_reference': unique_reference,
                            'transaction_reference': unique_reference,
                            'party_match': None,
                            'invoice_matches': None,
                            'matched_amount': None
                        }
                        txns.append(new_txn)
                except Exception as err:
                    # no payment instruction
                    new_txn = {
                        'txid': len(txns),
                        'date': date,
                        'currency': entry_currency,
                        'amount': entry_amount,
                        'party_name': "???",
                        'party_address': "???",
                        'credit_debit': credit_debit,
                        'party_iban': "???",
                        'unique_reference': unique_reference,
                        'transaction_reference': unique_reference,
                        'party_match': None,
                        'invoice_matches': None,
                        'matched_amount': None
                    }
                    txns.append(new_txn)
    return txns


@frappe.whitelist()
def make_payment_entry(amount, date, reference_no, paid_from=None, paid_to=None, payment_type=None, 
    party=None, party_type=None, references=None, remarks=None, auto_submit=False, exchange_rate=1,
    company=None):
    # assert list
    if references:
        references = ast.literal_eval(references)

    reference_type = "Sales Invoice"

    # find company
    if not company:
        if paid_from:
            company = frappe.get_value("Account", paid_from, "company")
        elif paid_to:
            company = frappe.get_value("Account", paid_to, "company")

    if payment_type == "Receive":
        # receive
        payment_entry = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Receive',
            'party_type': party_type,
            'party': party,
            'paid_to': paid_to,
            'paid_amount': float(amount),
            'received_amount': float(amount),
            'reference_no': reference_no,
            'reference_date': date,
            'posting_date': date,
            'remarks': remarks,
            'camt_amount': float(amount),
            'company': company,
            'source_exchange_rate': exchange_rate,
            'target_exchange_rate': exchange_rate
        })
    elif payment_type == "Pay":
        # pay
        payment_entry = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Pay',
            'party_type': party_type,
            'party': party,
            'paid_from': paid_from,
            'paid_amount': float(amount),
            'received_amount': float(amount),
            'reference_no': reference_no,
            'reference_date': date,
            'posting_date': date,
            'remarks': remarks,
            'camt_amount': float(amount),
            'company': company,
            'source_exchange_rate': exchange_rate,
            'target_exchange_rate': exchange_rate
        })
        if party_type == "Employee":
            reference_type = "Expense Claim"
        else:
            reference_type = "Purchase Invoice"
    elif payment_type == 'Internal Transfer':
        # internal transfer (against intermediate account)
        payment_entry = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Internal Transfer',
            'paid_from': paid_from,
            'paid_to': paid_to,
            'paid_amount': float(amount),
            'received_amount': float(amount),
            'reference_no': reference_no,
            'reference_date': date,
            'posting_date': date,
            'remarks': remarks,
            'camt_amount': float(amount),
            'company': company,
            'source_exchange_rate': exchange_rate,
            'target_exchange_rate': exchange_rate
        })
    else:
        frappe.throw(_('No Payment Type specified!'))

    if party_type == "Employee":
        payment_entry.paid_to = get_payable_account(company)['account'] or paid_to # note: at creation, this is ignored

    new_entry = payment_entry.insert()

    # add references after insert (otherwise they are overwritten)
    if references:
        for reference in references:
            create_reference(new_entry.name, reference, reference_type)

    if auto_submit:
        matched_entry = frappe.get_doc("Payment Entry", new_entry.name)
        matched_entry.submit()

    return new_entry.name


def create_reference(payment_entry, invoice_reference, invoice_type="Sales Invoice"):
    """Create a reference record in a Payment Entry."""
    reference_entry = frappe.get_doc({"doctype": "Payment Entry Reference"})
    reference_entry.parent = payment_entry
    reference_entry.parentfield = "references"
    reference_entry.parenttype = "Payment Entry"
    reference_entry.reference_doctype = invoice_type
    reference_entry.reference_name = invoice_reference

    if "Invoice" in invoice_type:
        reference_entry.total_amount = frappe.get_value(invoice_type, invoice_reference, "base_grand_total")
        reference_entry.outstanding_amount = frappe.get_value(invoice_type, invoice_reference, "outstanding_amount")
        paid_amount = frappe.get_value("Payment Entry", payment_entry, "paid_amount")
        if paid_amount > reference_entry.outstanding_amount:
            reference_entry.allocated_amount = reference_entry.outstanding_amount
        else:
            reference_entry.allocated_amount = paid_amount
    else:
        # expense claim:
        reference_entry.total_amount = frappe.get_value(invoice_type, invoice_reference, "total_claimed_amount")
        reference_entry.outstanding_amount = reference_entry.total_amount
        paid_amount = frappe.get_value("Payment Entry", payment_entry, "paid_amount")
        if paid_amount > reference_entry.outstanding_amount:
            reference_entry.allocated_amount = reference_entry.outstanding_amount
        else:
            reference_entry.allocated_amount = paid_amount

    reference_entry.insert()
    # update unallocated amount
    payment_record = frappe.get_doc("Payment Entry", payment_entry)
    payment_record.unallocated_amount -= reference_entry.allocated_amount
    payment_record.save()
