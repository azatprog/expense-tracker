import hashlib
import sqlite3
from dataclasses import dataclass

from . import categorize
from .parsers import ParsedStatement, merchant_name, parse_pdf


@dataclass
class ImportResult:
    file_name: str
    status: str            # imported | duplicate | error
    message: str
    statement_id: int | None = None


def import_pdf(conn: sqlite3.Connection, file_name: str, data: bytes) -> ImportResult:
    sha = hashlib.sha256(data).hexdigest()
    if conn.execute("SELECT 1 FROM statements WHERE file_sha256 = ?", (sha,)).fetchone():
        return ImportResult(file_name, "duplicate", "This file was already uploaded")
    try:
        parsed = parse_pdf(data)
    except Exception as e:  # pdfplumber and the parsers raise a variety of errors on bad input
        return ImportResult(file_name, "error", str(e) or e.__class__.__name__)
    return save(conn, file_name, sha, parsed)


def save(conn: sqlite3.Connection, file_name: str, sha: str, parsed: ParsedStatement) -> ImportResult:
    account_id = upsert_account(conn, parsed)
    overlap = conn.execute(
        "SELECT file_name FROM statements WHERE account_id = ? AND period_start = ? AND period_end = ?",
        (account_id, parsed.period_start.isoformat(), parsed.period_end.isoformat()),
    ).fetchone()
    if overlap:
        return ImportResult(file_name, "duplicate", f"Same statement period already imported from {overlap['file_name']}")

    cur = conn.execute(
        "INSERT INTO statements (account_id, file_name, file_sha256, period_start, period_end, balance_cents)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, file_name, sha, parsed.period_start.isoformat(), parsed.period_end.isoformat(), parsed.balance_cents),
    )
    statement_id = cur.lastrowid
    rules, ids = categorize.load_rules(conn), categorize.category_ids(conn)
    conn.executemany(
        "INSERT INTO transactions (statement_id, account_id, date, description, merchant, amount_cents,"
        " is_card_payment, category_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (statement_id, account_id, t.date.isoformat(), t.description, merchant_name(t.description),
             t.amount_cents, int(t.is_card_payment),
             categorize.categorize(t.description, t.amount_cents, t.is_card_payment, rules, ids))
            for t in parsed.transactions
        ],
    )
    conn.commit()
    return ImportResult(
        file_name, "imported",
        f"{parsed.account_name} · {parsed.period_start:%b %d} – {parsed.period_end:%b %d, %Y} · "
        f"{len(parsed.transactions)} transactions",
        statement_id,
    )


def upsert_account(conn: sqlite3.Connection, parsed: ParsedStatement) -> int:
    row = conn.execute(
        "SELECT id FROM accounts WHERE source = ? AND last4 = ?", (parsed.source, parsed.last4)
    ).fetchone()
    if row:
        return row["id"]
    # The first bank account becomes the income source; it can be changed on the Accounts page.
    has_income = conn.execute("SELECT 1 FROM accounts WHERE is_income_source = 1").fetchone()
    name = parsed.account_name if parsed.last4 == "0000" else f"{parsed.account_name} ··{parsed.last4}"
    cur = conn.execute(
        "INSERT INTO accounts (source, last4, name, kind, is_income_source) VALUES (?, ?, ?, ?, ?)",
        (parsed.source, parsed.last4, name, parsed.kind, int(parsed.kind == "bank" and not has_income)),
    )
    return cur.lastrowid
