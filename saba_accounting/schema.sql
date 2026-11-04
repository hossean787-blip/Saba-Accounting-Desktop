-- ACC-ERP prototype v0.3 / SQLite / schema design only
-- All accounting amounts in integer rials, dates ISO-8601. No proprietary Sepidar schema or code.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS companies (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL CHECK(length(trim(name))>0),
 economic_code TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS fiscal_years (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 code TEXT NOT NULL,
 start_date TEXT NOT NULL,
 end_date TEXT NOT NULL,
 is_closed INTEGER NOT NULL DEFAULT 0 CHECK(is_closed IN (0,1)),
 CHECK(start_date<=end_date),
 UNIQUE(company_id,code), UNIQUE(id,company_id)
);
-- Defense in depth: block overlapping fiscal periods even on direct SQL writes.
CREATE TRIGGER IF NOT EXISTS trg_fiscal_year_no_overlap_insert
BEFORE INSERT ON fiscal_years
WHEN EXISTS (SELECT 1 FROM fiscal_years f WHERE f.company_id=NEW.company_id
 AND f.start_date<=NEW.end_date AND f.end_date>=NEW.start_date)
BEGIN SELECT RAISE(ABORT, 'Overlapping fiscal years'); END;
CREATE TRIGGER IF NOT EXISTS trg_fiscal_year_no_overlap_update
BEFORE UPDATE OF company_id,start_date,end_date ON fiscal_years
WHEN EXISTS (SELECT 1 FROM fiscal_years f WHERE f.company_id=NEW.company_id
 AND f.id!=OLD.id AND f.start_date<=NEW.end_date AND f.end_date>=NEW.start_date)
BEGIN SELECT RAISE(ABORT, 'Overlapping fiscal years'); END;
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 code TEXT NOT NULL,
 title TEXT NOT NULL CHECK(length(trim(title))>0),
 parent_id INTEGER,
 level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 4),
 nature TEXT NOT NULL CHECK(nature IN ('debit','credit','both')),
 account_class TEXT NOT NULL DEFAULT 'unclassified' CHECK(account_class IN ('unclassified','asset','liability','equity','revenue','expense','cost')),
 is_postable INTEGER NOT NULL DEFAULT 0 CHECK(is_postable IN (0,1)),
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
 UNIQUE(company_id,code), UNIQUE(id,company_id),
 FOREIGN KEY(parent_id,company_id) REFERENCES accounts(id,company_id) ON DELETE RESTRICT,
 CHECK(parent_id IS NULL OR parent_id != id)
);
CREATE TABLE IF NOT EXISTS parties (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 code TEXT NOT NULL,
 name TEXT NOT NULL,
 party_kind TEXT NOT NULL CHECK(party_kind IN ('customer','supplier','employee','other','mixed')),
 UNIQUE(company_id,code)
);
CREATE TABLE IF NOT EXISTS cost_centers (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 code TEXT NOT NULL,
 title TEXT NOT NULL,
 UNIQUE(company_id,code)
);
CREATE TABLE IF NOT EXISTS journal_entries (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 fiscal_year_id INTEGER NOT NULL,
 serial_no INTEGER NOT NULL CHECK(serial_no>0),
 entry_date TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','reviewed','posted')),
 source_module TEXT,
 source_type TEXT,
 source_id TEXT,
 reversal_of_id INTEGER REFERENCES journal_entries(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 posted_at TEXT,
 UNIQUE(company_id,fiscal_year_id,serial_no),
 UNIQUE(id,company_id),
 FOREIGN KEY(fiscal_year_id,company_id) REFERENCES fiscal_years(id,company_id) ON DELETE RESTRICT,
 CHECK(source_id IS NULL OR (source_module IS NOT NULL AND source_type IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_posted_auto_document ON journal_entries(company_id,source_module,source_type,source_id)
 WHERE source_id IS NOT NULL AND status='posted';
CREATE UNIQUE INDEX IF NOT EXISTS ux_reversal_once ON journal_entries(reversal_of_id) WHERE reversal_of_id IS NOT NULL AND status='posted';
CREATE INDEX IF NOT EXISTS idx_journal_dates ON journal_entries(company_id,entry_date,status);
CREATE TABLE IF NOT EXISTS journal_lines (
 id INTEGER PRIMARY KEY,
 entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
 account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
 row_no INTEGER NOT NULL CHECK(row_no>0),
 debit_rial INTEGER NOT NULL DEFAULT 0 CHECK(debit_rial>=0),
 credit_rial INTEGER NOT NULL DEFAULT 0 CHECK(credit_rial>=0),
 narration TEXT NOT NULL DEFAULT '',
 cost_center_id INTEGER REFERENCES cost_centers(id) ON DELETE RESTRICT,
 party_id INTEGER REFERENCES parties(id) ON DELETE RESTRICT,
 CHECK((debit_rial>0 AND credit_rial=0) OR (credit_rial>0 AND debit_rial=0)),
 UNIQUE(entry_id,row_no)
);
CREATE INDEX IF NOT EXISTS idx_journal_account ON journal_lines(account_id,entry_id);
CREATE TABLE IF NOT EXISTS audit_events (
 id INTEGER PRIMARY KEY,
 company_id INTEGER REFERENCES companies(id),
 event_type TEXT NOT NULL,
 target_type TEXT NOT NULL,
 target_id TEXT NOT NULL,
 event_time TEXT NOT NULL DEFAULT (datetime('now')),
 actor TEXT NOT NULL DEFAULT 'local-user',
 note TEXT NOT NULL DEFAULT ''
);
-- Inserts must start as draft: prevents a bypass of posting validation.
CREATE TRIGGER IF NOT EXISTS trg_no_direct_post BEFORE INSERT ON journal_entries
WHEN NEW.status != 'draft'
BEGIN SELECT RAISE(ABORT,'New journal must start as draft'); END;
-- Prevent company switches after chart creation.
CREATE TRIGGER IF NOT EXISTS trg_account_scope_lock BEFORE UPDATE OF company_id ON accounts
BEGIN SELECT RAISE(ABORT,'Account company is immutable'); END;
-- Parent-child levels and ownership.
CREATE TRIGGER IF NOT EXISTS trg_account_hierarchy_insert BEFORE INSERT ON accounts
WHEN NEW.parent_id IS NOT NULL
BEGIN
 SELECT CASE WHEN (SELECT level FROM accounts WHERE id=NEW.parent_id AND company_id=NEW.company_id) != NEW.level-1
   THEN RAISE(ABORT,'Invalid account hierarchy') END;
END;
-- Always lock journal's accounting scope, even in draft, to preserve existing lines.
CREATE TRIGGER IF NOT EXISTS trg_journal_scope_lock BEFORE UPDATE OF company_id,fiscal_year_id ON journal_entries
BEGIN SELECT RAISE(ABORT,'Journal company/year immutable'); END;
-- After posting, entry header and lines cannot be edited or removed.
CREATE TRIGGER IF NOT EXISTS trg_posted_header_lock BEFORE UPDATE ON journal_entries
WHEN OLD.status='posted'
BEGIN SELECT RAISE(ABORT,'Posted journal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_posted_header_delete BEFORE DELETE ON journal_entries
WHEN OLD.status='posted'
BEGIN SELECT RAISE(ABORT,'Cannot delete posted journal'); END;
CREATE TRIGGER IF NOT EXISTS trg_lines_insert_scope BEFORE INSERT ON journal_lines
BEGIN
 SELECT CASE WHEN (SELECT status FROM journal_entries WHERE id=NEW.entry_id)='posted'
  THEN RAISE(ABORT,'Cannot insert into posted journal') END;
 SELECT CASE WHEN (SELECT company_id FROM accounts WHERE id=NEW.account_id) != (SELECT company_id FROM journal_entries WHERE id=NEW.entry_id)
  THEN RAISE(ABORT,'Account from different company') END;
 SELECT CASE WHEN (SELECT is_postable FROM accounts WHERE id=NEW.account_id)!=1 OR (SELECT is_active FROM accounts WHERE id=NEW.account_id)!=1
  THEN RAISE(ABORT,'Account not postable or inactive') END;
 SELECT CASE WHEN NEW.party_id IS NOT NULL AND (SELECT company_id FROM parties WHERE id=NEW.party_id) != (SELECT company_id FROM journal_entries WHERE id=NEW.entry_id)
  THEN RAISE(ABORT,'Party from different company') END;
 SELECT CASE WHEN NEW.cost_center_id IS NOT NULL AND (SELECT company_id FROM cost_centers WHERE id=NEW.cost_center_id) != (SELECT company_id FROM journal_entries WHERE id=NEW.entry_id)
  THEN RAISE(ABORT,'Cost center from different company') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_lines_update_guard BEFORE UPDATE ON journal_lines
BEGIN
 SELECT CASE WHEN (SELECT status FROM journal_entries WHERE id=OLD.entry_id)='posted' OR (SELECT status FROM journal_entries WHERE id=NEW.entry_id)='posted'
 THEN RAISE(ABORT,'Cannot edit posted journal lines') END;
 SELECT CASE WHEN (SELECT company_id FROM accounts WHERE id=NEW.account_id) != (SELECT company_id FROM journal_entries WHERE id=NEW.entry_id)
 THEN RAISE(ABORT,'Account from different company') END;
 SELECT CASE WHEN (SELECT is_postable FROM accounts WHERE id=NEW.account_id)!=1 OR (SELECT is_active FROM accounts WHERE id=NEW.account_id)!=1
 THEN RAISE(ABORT,'Account not postable or inactive') END;
 SELECT CASE WHEN NEW.party_id IS NOT NULL AND (SELECT company_id FROM parties WHERE id=NEW.party_id) != (SELECT company_id FROM journal_entries WHERE id=NEW.entry_id)
 THEN RAISE(ABORT,'Party from different company') END;
 SELECT CASE WHEN NEW.cost_center_id IS NOT NULL AND (SELECT company_id FROM cost_centers WHERE id=NEW.cost_center_id) != (SELECT company_id FROM journal_entries WHERE id=NEW.entry_id)
 THEN RAISE(ABORT,'Cost center from different company') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_lines_delete_guard BEFORE DELETE ON journal_lines
WHEN (SELECT status FROM journal_entries WHERE id=OLD.entry_id)='posted'
BEGIN SELECT RAISE(ABORT,'Cannot delete posted journal lines'); END;
-- Posting checks (triggers are a safety net; application services must also validate).
CREATE TRIGGER IF NOT EXISTS trg_posting_checks BEFORE UPDATE OF status ON journal_entries
WHEN NEW.status='posted' AND OLD.status!='posted'
BEGIN
 SELECT CASE WHEN (SELECT is_closed FROM fiscal_years WHERE id=NEW.fiscal_year_id)!=0
 THEN RAISE(ABORT,'Fiscal year closed') END;
 SELECT CASE WHEN NEW.entry_date NOT BETWEEN (SELECT start_date FROM fiscal_years WHERE id=NEW.fiscal_year_id)
  AND (SELECT end_date FROM fiscal_years WHERE id=NEW.fiscal_year_id)
 THEN RAISE(ABORT,'Journal date outside fiscal year') END;
 SELECT CASE WHEN (SELECT count(*) FROM journal_lines WHERE entry_id=NEW.id)<2
 THEN RAISE(ABORT,'Journal requires at least 2 lines') END;
 SELECT CASE WHEN (SELECT coalesce(sum(debit_rial-credit_rial),0) FROM journal_lines WHERE entry_id=NEW.id)!=0
 THEN RAISE(ABORT,'Journal is unbalanced') END;
 SELECT CASE WHEN EXISTS (SELECT 1 FROM journal_lines l JOIN accounts a ON a.id=l.account_id
 WHERE l.entry_id=NEW.id AND (a.is_postable!=1 OR a.is_active!=1))
 THEN RAISE(ABORT,'Journal references a non-postable or inactive account') END;
END;
-- Additional safety barriers used by the application prototype.
CREATE TRIGGER IF NOT EXISTS trg_year_scope_guard BEFORE UPDATE OF company_id,start_date,end_date ON fiscal_years
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE fiscal_year_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Fiscal year has journals and is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_year_delete_guard BEFORE DELETE ON fiscal_years
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE fiscal_year_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Fiscal year has journals'); END;
CREATE TRIGGER IF NOT EXISTS trg_journal_create_date BEFORE INSERT ON journal_entries
WHEN (SELECT is_closed FROM fiscal_years WHERE id=NEW.fiscal_year_id)!=0
  OR NEW.entry_date NOT BETWEEN (SELECT start_date FROM fiscal_years WHERE id=NEW.fiscal_year_id)
    AND (SELECT end_date FROM fiscal_years WHERE id=NEW.fiscal_year_id)
BEGIN SELECT RAISE(ABORT,'Journal date outside open year'); END;
CREATE TRIGGER IF NOT EXISTS trg_journal_date_update BEFORE UPDATE OF entry_date ON journal_entries
WHEN (SELECT is_closed FROM fiscal_years WHERE id=OLD.fiscal_year_id)!=0
  OR NEW.entry_date NOT BETWEEN (SELECT start_date FROM fiscal_years WHERE id=NEW.fiscal_year_id)
    AND (SELECT end_date FROM fiscal_years WHERE id=NEW.fiscal_year_id)
BEGIN SELECT RAISE(ABORT,'Journal date outside open year'); END;
CREATE TRIGGER IF NOT EXISTS trg_account_tree_guard BEFORE UPDATE OF parent_id,level,company_id,is_postable ON accounts
WHEN EXISTS(SELECT 1 FROM journal_lines WHERE account_id=OLD.id)
 OR EXISTS(SELECT 1 FROM accounts WHERE parent_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Account in use cannot change hierarchy'); END;
CREATE TRIGGER IF NOT EXISTS trg_account_delete_guard BEFORE DELETE ON accounts
WHEN EXISTS(SELECT 1 FROM journal_lines WHERE account_id=OLD.id)
 OR EXISTS(SELECT 1 FROM accounts WHERE parent_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Account in use cannot be removed'); END;

-- v0.5.3: enforce the chart-of-accounts hierarchy for direct SQL as well as service calls.
-- Existing migrations keep all historical account IDs and journal references intact.
CREATE TRIGGER IF NOT EXISTS trg_account_structure_insert
BEFORE INSERT ON accounts
BEGIN
 SELECT CASE WHEN NEW.level=1 AND NEW.parent_id IS NOT NULL
    THEN RAISE(ABORT,'Group account cannot have a parent') END;
 SELECT CASE WHEN NEW.level>1 AND NEW.parent_id IS NULL
    THEN RAISE(ABORT,'Non-root account requires a parent') END;
 SELECT CASE WHEN NEW.parent_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM accounts p WHERE p.id=NEW.parent_id AND p.is_postable=1)
    THEN RAISE(ABORT,'Posting account cannot be a parent') END;
 SELECT CASE WHEN NEW.is_postable=1 AND NEW.level!=4
    THEN RAISE(ABORT,'Only level-four accounts can be postable') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_account_structure_update
BEFORE UPDATE OF parent_id,level,is_postable ON accounts
BEGIN
 SELECT CASE WHEN NEW.level=1 AND NEW.parent_id IS NOT NULL
    THEN RAISE(ABORT,'Group account cannot have a parent') END;
 SELECT CASE WHEN NEW.level>1 AND NEW.parent_id IS NULL
    THEN RAISE(ABORT,'Non-root account requires a parent') END;
 SELECT CASE WHEN NEW.parent_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM accounts p WHERE p.id=NEW.parent_id AND p.company_id=NEW.company_id
      AND p.level=NEW.level-1 AND p.is_postable=0)
    THEN RAISE(ABORT,'Invalid account parent') END;
 SELECT CASE WHEN NEW.is_postable=1 AND NEW.level!=4
    THEN RAISE(ABORT,'Only level-four accounts can be postable') END;
 SELECT CASE WHEN NEW.is_postable=1 AND EXISTS (
    SELECT 1 FROM accounts child WHERE child.parent_id=OLD.id)
    THEN RAISE(ABORT,'Parent account cannot be postable') END;
 SELECT CASE WHEN (NEW.parent_id IS NOT OLD.parent_id OR NEW.level!=OLD.level)
    AND (EXISTS(SELECT 1 FROM accounts child WHERE child.parent_id=OLD.id)
      OR EXISTS(SELECT 1 FROM journal_lines l WHERE l.account_id=OLD.id))
    THEN RAISE(ABORT,'Account with children or journal lines cannot be reparented') END;
END;

-- v0.5.4: guard edits to analytic allocations and limit direct SQL amounts.
CREATE TRIGGER IF NOT EXISTS trg_journal_line_amount_insert
BEFORE INSERT ON journal_lines
WHEN NEW.debit_rial>9000000000000000 OR NEW.credit_rial>9000000000000000
BEGIN SELECT RAISE(ABORT,'Journal line exceeds maximum amount'); END;
CREATE TRIGGER IF NOT EXISTS trg_journal_line_amount_update
BEFORE UPDATE OF debit_rial,credit_rial ON journal_lines
WHEN NEW.debit_rial>9000000000000000 OR NEW.credit_rial>9000000000000000
BEGIN SELECT RAISE(ABORT,'Journal line exceeds maximum amount'); END;
