-- Additive safeguards, executed after columns are migrated by finance.py.
CREATE TABLE IF NOT EXISTS floating_details (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 code TEXT NOT NULL, title TEXT NOT NULL,
 detail_type TEXT NOT NULL CHECK(detail_type IN ('person','project','bank','contract','employee','asset','other')),
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
 UNIQUE(company_id,code),UNIQUE(id,company_id)
);
CREATE TABLE IF NOT EXISTS account_detail_rules (
 account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE RESTRICT,
 required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0,1))
);
CREATE TABLE IF NOT EXISTS period_locks (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 fiscal_year_id INTEGER NOT NULL REFERENCES fiscal_years(id),
 start_date TEXT NOT NULL,end_date TEXT NOT NULL,locked INTEGER NOT NULL DEFAULT 1 CHECK(locked IN (0,1)),
 CHECK(start_date<=end_date)
);
CREATE TABLE IF NOT EXISTS fiscal_closures (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id),
 fiscal_year_id INTEGER NOT NULL UNIQUE REFERENCES fiscal_years(id),
 next_year_id INTEGER NOT NULL UNIQUE REFERENCES fiscal_years(id),
 retained_account_id INTEGER NOT NULL REFERENCES accounts(id),
 result_entry_id INTEGER REFERENCES journal_entries(id),
 close_entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
 opening_entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
 profit_rial INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_manual_correction ON journal_entries(correction_of_id) WHERE correction_of_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_floating_line ON journal_lines(detail_id,entry_id);
CREATE TRIGGER IF NOT EXISTS trg_detail_insert BEFORE INSERT ON journal_lines
BEGIN
 SELECT CASE WHEN NEW.detail_id IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM floating_details d JOIN journal_entries j ON j.company_id=d.company_id
  WHERE d.id=NEW.detail_id AND j.id=NEW.entry_id AND d.is_active=1)
 THEN RAISE(ABORT,'Floating detail from different company or inactive') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_detail_update BEFORE UPDATE OF detail_id,entry_id ON journal_lines
BEGIN
 SELECT CASE WHEN NEW.detail_id IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM floating_details d JOIN journal_entries j ON j.company_id=d.company_id
  WHERE d.id=NEW.detail_id AND j.id=NEW.entry_id AND d.is_active=1)
 THEN RAISE(ABORT,'Floating detail from different company or inactive') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_post_required_detail BEFORE UPDATE OF status ON journal_entries
WHEN NEW.status='posted' AND OLD.status!='posted'
BEGIN
 SELECT CASE WHEN EXISTS (
 SELECT 1 FROM journal_lines l JOIN account_detail_rules r ON r.account_id=l.account_id
 WHERE l.entry_id=NEW.id AND r.required=1 AND l.detail_id IS NULL)
 THEN RAISE(ABORT,'Required floating detail is missing') END;
 SELECT CASE WHEN EXISTS (
 SELECT 1 FROM period_locks p WHERE p.fiscal_year_id=NEW.fiscal_year_id AND p.locked=1
 AND NEW.entry_date BETWEEN p.start_date AND p.end_date)
 THEN RAISE(ABORT,'Accounting period is locked') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_no_change_closed_flag BEFORE UPDATE OF is_closed ON fiscal_years
WHEN OLD.is_closed=1 AND NEW.is_closed=0
BEGIN SELECT RAISE(ABORT,'Closed fiscal year cannot be reopened directly'); END;
CREATE TRIGGER IF NOT EXISTS trg_floating_company_lock BEFORE UPDATE OF company_id ON floating_details
BEGIN SELECT RAISE(ABORT,'Floating detail company immutable'); END;
-- Application-level append-only events. This does not protect against a DB owner.
CREATE TRIGGER IF NOT EXISTS trg_audit_append_only_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_append_only_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
