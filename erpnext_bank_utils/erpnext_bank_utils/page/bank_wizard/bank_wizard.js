frappe.pages['bank_wizard'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('Bank Wizard'),
        single_column: true
    });

    frappe.bank_wizard.make(page);
    frappe.bank_wizard.run();
    frappe.breadcrumbs.add("ERPNext Bank Utils");
}

frappe.bank_wizard = {
    start: 0,
    make: function (page) {
        var me = frappe.bank_wizard;
        me.page = page;
        me.body = $('<div></div>').appendTo(me.page.main);
        var data = "";
        $(frappe.render_template('bank_wizard', data)).appendTo(me.body);

        // attach button handlers
        this.page.main.find(".btn-parse-file").on('click', function () {
            // get selected account
            var account = document.getElementById("bank_account").value;

            // read the file 
            var file = document.getElementById("input_file").files[0];
            if (file.name.toLowerCase().endsWith(".xml")) {
                // this is an xml file
                var content = "";
                if (file) {
                    // create a new reader instance
                    var reader = new FileReader();
                    // assign load event to process the file
                    reader.onload = function (event) {
                        // enable waiting gif
                        frappe.bank_wizard.start_wait();

                        // read file content
                        content = event.target.result;

                        // parse the xml content
                        frappe.bank_wizard.parse(content, account);
                    }
                    // assign an error handler event
                    reader.onerror = function (event) {
                        frappe.msgprint(__("Error reading file"), __("Error"));
                    }

                    reader.readAsText(file, "ANSI");
                }
                else {
                    frappe.msgprint(__("Please select a file."), __("Information"));
                }
            } else if (file.name.toLowerCase().endsWith(".zip")) {
                // this is a zip file
                console.log("unzipping " + file.name + "...");
                JSZip.loadAsync(file).then(function (zip) {
                    // async: compile a promise to extract all contained files
                    var promises = [];
                    zip.forEach(function (relativePath, zipEntry) {
                        promises.push(zipEntry.async("string").then(
                            function (data) {
                                return data;
                            })
                        );
                    });
                    // on completed promise, combine content and process
                    Promise.all(promises).then(function (list) {
                        console.log("Promise complete!");
                        var content = list.join("");
                        // parse the xml content
                        frappe.bank_wizard.parse(content, account);
                    });
                }, function (e) {
                    frappe.msgprint(__("Unzip error: ") + e.message, __("Error"));
                });
            } else {
                frappe.msgprint(__("Unsupported file format. Please use an xml or zip camt file"), __("Error"));
            }
        });
    },
    parse: function (content, account) {
        // call bankimport method with file content
        frappe.call({
            method: 'erpnext_bank_utils.erpnext_bank_utils.page.bank_wizard.bank_wizard.read_camt053',
            args: {
                content: content
            },
            callback: function (r) {
                if (r.message) {
                    try {
                        frappe.show_alert(r.message.length + __(" transactions found"));
                        frappe.bank_wizard.render_response(r.message);
                    } catch {
                        frappe.msgprint("An error occurred while parsing. Please check the log files.");
                        frappe.bank_wizard.end_wait();
                    }
                }
            }
        });
    },
    run: function () {
        // populate bank accounts
        frappe.call({
            method: 'erpnext_bank_utils.erpnext_bank_utils.page.bank_wizard.bank_wizard.get_bank_accounts',
            callback: function (r) {
                if (r.message) {
                    var select = document.getElementById("bank_account");
                    // add on change event
                    select.onchange = function () {
                        frappe.bank_wizard.set_defaults(select.value);
                    };
                    for (var i = 0; i < r.message.length; i++) {
                        var opt = document.createElement("option");
                        opt.value = r.message[i];
                        opt.innerHTML = r.message[i];
                        select.appendChild(opt);
                    }
                    // call with initial value
                    frappe.bank_wizard.set_defaults(select.value);
                }
            }
        });
    },
    set_defaults: function (bank_account) {
        frappe.call({
            method: 'erpnext_bank_utils.erpnext_bank_utils.page.bank_wizard.bank_wizard.get_defaults',
            args: {
                'bank_account': bank_account
            },
            callback: function (r) {
                if (r.message) {
                    document.getElementById("company").value = r.message.company;
                    document.getElementById("default_supplier").value = r.message.default_supplier;
                    document.getElementById("default_customer").value = r.message.default_customer;
                    document.getElementById("intermediate_account").value = r.message.intermediate_account;
                    document.getElementById("payable_account").value = r.message.default_payable_account;
                    document.getElementById("receivable_account").value = r.message.default_receivable_account;
                } else {
                    frappe.msgprint(__("Please set the <b>default accounts</b> in <a href=\"/desk#Form/Company/{0}\">{0}</a>.").replace("{0}", r.message.company));
                }
            }
        });
    },
    start_wait: function () {
        document.getElementById("waitingScreen").classList.remove("hidden");
        document.getElementById("btn-parse-file").classList.add("disabled");
    },
    end_wait: function () {
        document.getElementById("waitingScreen").classList.add("hidden");
        document.getElementById("btn-parse-file").classList.remove("disabled");
    },
    render_response: function (transactions) {
        // disable waiting gif
        frappe.bank_wizard.end_wait();

        // display the transactions as table
        var container = document.getElementById("table_placeholder");
        var content = frappe.render_template('transaction_table', { "transactions": transactions });
        container.innerHTML = content;

        // attach button handlers
        var bank_account = document.getElementById("bank_account").value;
        var company = document.getElementById("company").value;
        var intermediate_account = document.getElementById("intermediate_account").value;
        var payable_account = document.getElementById("payable_account").value;
        var receivable_account = document.getElementById("receivable_account").value;
        var default_customer = document.getElementById("default_customer").value;
        var default_supplier = document.getElementById("default_supplier").value;

        transactions.forEach(function (transaction) {
            // add generic payables/receivables handler
            const payment = {
                'amount': transaction.amount,
                'date': transaction.date,
                'reference_no': transaction.unique_reference,
                'remarks': (transaction.transaction_reference + ", " + transaction.party_name + ", " + transaction.party_address),
                'company': company
            };

            if (transaction.credit_debit == "DBIT") {
                payment.payment_type = 'Pay';
                payment.paid_from = bank_account;
                payment.paid_to = payable_account;

                // quick match (purchase invoice)
                var button = document.getElementById("btn-quick-pinv-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Supplier';
                        payment.party = transaction.party_match;
                        payment.references = transaction.invoice_matches;
                        payment.auto_submit = 1;

                        frappe.bank_wizard.quick_payment_entry(payment, transaction.txid);
                    });
                }
                // quick match (Expense Claim)
                var button = document.getElementById("btn-quick-exp-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Employee';
                        payment.party = transaction.employee_match;
                        payment.references = transaction.expense_matches;
                        payment.auto_submit = 1;

                        frappe.bank_wizard.quick_payment_entry(payment, transaction.txid);
                    });
                }
                // purchase invoice match
                var button = document.getElementById("btn-close-pinv-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Supplier';
                        payment.party = transaction.party_match;
                        payment.references = transaction.invoice_matches;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
                // expense claim match
                var button = document.getElementById("btn-close-exp-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Employee';
                        payment.party = transaction.employee_match;
                        payment.references = transaction.expense_matches;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
                // supplier match
                var button = document.getElementById("btn-close-supplier-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        debugger;
                        payment.party_type = 'Supplier';
                        payment.party = transaction.party_match;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
                // employee match 
                var button = document.getElementById("btn-close-employee-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Employee';
                        payment.party = transaction.employee_match;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
                // payables
                var button = document.getElementById("btn-close-payable-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Supplier';
                        payment.party = default_supplier;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
            } else {
                payment.payment_type = 'Receive';
                payment.paid_from = receivable_account;
                payment.paid_to = bank_account;

                // quick match (sales invoice)
                var button = document.getElementById("btn-quick-sinv-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Customer';
                        payment.party = transaction.party_match;
                        payment.references = transaction.invoice_matches;
                        payment.auto_submit = 1;

                        frappe.bank_wizard.quick_payment_entry(payment, transaction.txid);
                    });
                }
                // sales invoice match
                var button = document.getElementById("btn-close-sinv-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Customer';
                        payment.party = transaction.party_match;
                        payment.references = transaction.invoice_matches;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
                // customer match
                var button = document.getElementById("btn-close-customer-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Customer';
                        payment.party = transaction.party_match;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
                // receivables
                var button = document.getElementById("btn-close-receivable-" + transaction.txid);
                if (button) {
                    button.addEventListener("click", function () {
                        payment.party_type = 'Customer';
                        payment.party = default_customer;

                        frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                    });
                }
            }
            // add intermediate account handler
            var button = document.getElementById("btn-close-intermediate-" + transaction.txid);
            if (button) {
                button.addEventListener("click", function () {
                    payment.payment_type = 'Internal Transfer';

                    if (transaction.credit_debit == "DBIT") {
                        payment.paid_from = bank_account;
                        payment.paid_to = intermediate_account;
                    } else {
                        payment.paid_from = intermediate_account;
                        payment.paid_to = bank_account;
                    }

                    frappe.bank_wizard.create_payment_entry(payment, transaction.txid);
                });
            }
        });
    },
    create_payment_entry: function (payment, txid) {
        frappe.call({
            method: "erpnext_bank_utils.erpnext_bank_utils.page.bank_wizard.bank_wizard.make_payment_entry",
            args: payment,
            callback: function (r) {
                // open new record in a separate tab
                window.open('/desk#Form/Payment Entry/' + r.message, '_blank');
                frappe.bank_wizard.close_entry(txid);
            }
        });
    },
    close_entry: function (txid) {
        // close the entry in the list
        var table_row = document.getElementById("row-transaction-" + txid);
        table_row.classList.add("hidden");
    },
    quick_payment_entry: function (payment, txid) {
        frappe.call({
            method: "erpnext_bank_utils.erpnext_bank_utils.page.bank_wizard.bank_wizard.make_payment_entry",
            args: payment,
            callback: function (r) {
                // show alert
                frappe.show_alert(__("Transaction matched"));
                frappe.bank_wizard.close_entry(txid);
            }
        });
    }
};
