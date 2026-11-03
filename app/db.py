"""SQLite storage. Money is stored as integer cents; sign is from the user's point of view
(negative = money out / a charge, positive = money in / a credit)."""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("EXPENSE_DB", Path(__file__).resolve().parent.parent / "data" / "expenses.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,              -- boa_checking | boa_credit | apple_card | amex
    last4 TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                -- bank | credit
    is_income_source INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source, last4)
);

CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_sha256 TEXT NOT NULL UNIQUE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    balance_cents INTEGER,             -- new/statement balance for cards, ending balance for bank
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL                 -- income | expense | transfer
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,             -- case-insensitive substring of the description
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 0,
    UNIQUE (pattern)
);

CREATE TABLE IF NOT EXISTS budget_lines (
    id INTEGER PRIMARY KEY,
    month TEXT NOT NULL,               -- YYYY-MM
    kind TEXT NOT NULL,                -- income | expense
    name TEXT NOT NULL,                -- usually a category name, can be anything
    amount_cents INTEGER NOT NULL,
    categories TEXT NOT NULL DEFAULT '',  -- linked category names, "|"-separated; empty = same as name
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_budget_month ON budget_lines(month);

CREATE TABLE IF NOT EXISTS seeded_rules (
    pattern TEXT PRIMARY KEY           -- default rules already offered to this database
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    merchant TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    is_card_payment INTEGER NOT NULL DEFAULT 0,  -- card side: payment received from the bank
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    category_locked INTEGER NOT NULL DEFAULT 0   -- set by a manual edit; rules don't overwrite it
);
CREATE INDEX IF NOT EXISTS ix_txn_account_date ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS ix_txn_statement ON transactions(statement_id);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # One connection per request, but FastAPI may open it on a worker thread and use it on the event loop.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn: sqlite3.Connection) -> None:
    from . import categorize

    conn.executescript(SCHEMA)
    migrate(conn)
    categorize.seed(conn)
    conn.commit()


def migrate(conn: sqlite3.Connection) -> None:
    """Add columns that newer versions expect to a database created by an older one."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(budget_lines)")}
    if "categories" not in columns:
        conn.execute("ALTER TABLE budget_lines ADD COLUMN categories TEXT NOT NULL DEFAULT ''")
