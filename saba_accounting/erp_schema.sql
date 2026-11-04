-- Independent prototype extensions: all amounts are integer IRR and quantities whole units.
CREATE TABLE IF NOT EXISTS erp_config (
 company_id INTEGER PRIMARY KEY REFERENCES companies(id),
 cash_account INTEGER, receivable_account INTEGER, payable_account INTEGER,
 inventory_account INTEGER, cogs_account INTEGER, sales_account INTEGER,
 vat_input_account INTEGER, vat_output_account INTEGER,
 payroll_expense_account INTEGER, payroll_payable_account INTEGER, payroll_deduction_account INTEGER,
 depreciation_expense_account INTEGER, accumulated_depreciation_account INTEGER,
 finished_goods_account INTEGER,
 FOREIGN KEY(cash_account) REFERENCES accounts(id)
);
CREATE TABLE IF NOT EXISTS erp_cashboxes (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('cash','bank','pos')),
 gl_account_id INTEGER NOT NULL REFERENCES accounts(id),
 UNIQUE(company_id,name), UNIQUE(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_cash_flows (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 fiscal_year_id INTEGER NOT NULL REFERENCES fiscal_years(id),
 cashbox_id INTEGER NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('receipt','payment')),
 amount_rial INTEGER NOT NULL CHECK(amount_rial>0),
 other_account_id INTEGER NOT NULL REFERENCES accounts(id), party_id INTEGER REFERENCES parties(id),
 movement_date TEXT NOT NULL, reference TEXT NOT NULL, entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id),
 UNIQUE(company_id,reference), FOREIGN KEY(cashbox_id,company_id) REFERENCES erp_cashboxes(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_checks (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 number TEXT NOT NULL, bank_name TEXT NOT NULL, due_date TEXT NOT NULL, amount_rial INTEGER NOT NULL CHECK(amount_rial>0),
 direction TEXT NOT NULL CHECK(direction IN ('received','issued')),
 status TEXT NOT NULL DEFAULT 'registered' CHECK(status IN ('registered','cleared','returned','void')),
 party_id INTEGER REFERENCES parties(id), UNIQUE(company_id,number,direction)
);
CREATE TABLE IF NOT EXISTS erp_items (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 code TEXT NOT NULL, title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('good','service')),
 qty INTEGER NOT NULL DEFAULT 0 CHECK(qty>=0),
 value_rial INTEGER NOT NULL DEFAULT 0 CHECK(value_rial>=0),
 UNIQUE(company_id,code), UNIQUE(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_warehouses (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), name TEXT NOT NULL,
 UNIQUE(company_id,name), UNIQUE(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_stock_movements (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 item_id INTEGER NOT NULL, warehouse_id INTEGER NOT NULL,
 qty_change INTEGER NOT NULL CHECK(qty_change!=0), value_change_rial INTEGER NOT NULL,
 source_kind TEXT NOT NULL, source_id INTEGER NOT NULL,
 FOREIGN KEY(item_id,company_id) REFERENCES erp_items(id,company_id),
 FOREIGN KEY(warehouse_id,company_id) REFERENCES erp_warehouses(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_invoices (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 year_id INTEGER NOT NULL REFERENCES fiscal_years(id),
 direction TEXT NOT NULL CHECK(direction IN ('sale','purchase')),
 external_ref TEXT NOT NULL, invoice_date TEXT NOT NULL,
 party_id INTEGER NOT NULL REFERENCES parties(id), warehouse_id INTEGER REFERENCES erp_warehouses(id),
 subtotal_rial INTEGER NOT NULL, tax_rial INTEGER NOT NULL, total_rial INTEGER NOT NULL,
 entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id),
 UNIQUE(company_id,direction,external_ref)
);
CREATE TABLE IF NOT EXISTS erp_invoice_lines (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES erp_invoices(id),
 item_id INTEGER NOT NULL REFERENCES erp_items(id),qty INTEGER NOT NULL CHECK(qty>0),
 unit_price_rial INTEGER NOT NULL CHECK(unit_price_rial>=0),tax_rate_bps INTEGER NOT NULL CHECK(tax_rate_bps BETWEEN 0 AND 10000),
 tax_rial INTEGER NOT NULL CHECK(tax_rial>=0),cost_rial INTEGER NOT NULL DEFAULT 0 CHECK(cost_rial>=0)
);
CREATE TABLE IF NOT EXISTS erp_employees (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 personnel_code TEXT NOT NULL, name TEXT NOT NULL,
 UNIQUE(company_id,personnel_code), UNIQUE(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_payroll (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 employee_id INTEGER NOT NULL, period TEXT NOT NULL, gross_rial INTEGER NOT NULL CHECK(gross_rial>0),
 deduction_rial INTEGER NOT NULL CHECK(deduction_rial>=0),
 net_rial INTEGER NOT NULL CHECK(net_rial>=0),entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id),
 UNIQUE(company_id,employee_id,period),
 FOREIGN KEY(employee_id,company_id) REFERENCES erp_employees(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_assets (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 code TEXT NOT NULL, title TEXT NOT NULL, cost_rial INTEGER NOT NULL CHECK(cost_rial>0),
 salvage_rial INTEGER NOT NULL CHECK(salvage_rial>=0), life_months INTEGER NOT NULL CHECK(life_months>0),
 months_posted INTEGER NOT NULL DEFAULT 0 CHECK(months_posted>=0),
 depreciated_rial INTEGER NOT NULL DEFAULT 0 CHECK(depreciated_rial>=0),
 UNIQUE(company_id,code), UNIQUE(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_depreciation (
 id INTEGER PRIMARY KEY,asset_id INTEGER NOT NULL REFERENCES erp_assets(id),period TEXT NOT NULL,
 expense_rial INTEGER NOT NULL CHECK(expense_rial>0),entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id),
 UNIQUE(asset_id,period)
);
CREATE TABLE IF NOT EXISTS erp_boms (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 finished_item_id INTEGER NOT NULL, material_item_id INTEGER NOT NULL,
 material_qty INTEGER NOT NULL CHECK(material_qty>0),
 FOREIGN KEY(finished_item_id,company_id) REFERENCES erp_items(id,company_id),
 FOREIGN KEY(material_item_id,company_id) REFERENCES erp_items(id,company_id),
 UNIQUE(company_id,finished_item_id,material_item_id)
);
CREATE TABLE IF NOT EXISTS erp_production (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 finished_item_id INTEGER NOT NULL REFERENCES erp_items(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 cost_rial INTEGER NOT NULL CHECK(cost_rial>0),external_ref TEXT NOT NULL,
 entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id),UNIQUE(company_id,external_ref)
);
CREATE TABLE IF NOT EXISTS erp_projects (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 code TEXT NOT NULL,title TEXT NOT NULL,budget_rial INTEGER NOT NULL CHECK(budget_rial>=0),
 UNIQUE(company_id,code),UNIQUE(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_project_costs (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 project_id INTEGER NOT NULL,amount_rial INTEGER NOT NULL CHECK(amount_rial>0),
 entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id),
 FOREIGN KEY(project_id,company_id) REFERENCES erp_projects(id,company_id)
);
CREATE TABLE IF NOT EXISTS erp_budgets (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),year_id INTEGER NOT NULL REFERENCES fiscal_years(id),
 account_id INTEGER NOT NULL REFERENCES accounts(id), amount_rial INTEGER NOT NULL,
 UNIQUE(company_id,year_id,account_id)
);
CREATE TABLE IF NOT EXISTS erp_tax_outbox (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 invoice_id INTEGER NOT NULL UNIQUE REFERENCES erp_invoices(id),
 state TEXT NOT NULL DEFAULT 'local_draft' CHECK(state IN ('local_draft','exported')),
 payload_json TEXT NOT NULL, external_tracking TEXT
);
CREATE TABLE IF NOT EXISTS erp_audit_log (
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
 action TEXT NOT NULL,entity_kind TEXT NOT NULL,entity_id TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',at_utc TEXT NOT NULL DEFAULT (datetime('now'))
);
