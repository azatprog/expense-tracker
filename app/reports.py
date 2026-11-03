"""Income vs expense reports.

Two views:
- cash:    what left the income account. A card payment is replaced by the categories of the card
           statement it paid, split in proportion to that statement's spending per category.
- accrual: every account's charges on the day they were made; card payments are just transfers.
"""
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .categorize import CARD_PAYMENT

# Bank-side description -> (card source, regex group holding the card's last 4 digits)
CARD_TARGETS = [
    (re.compile(r"APPLECARD", re.I), "apple_card", None),
    (re.compile(r"AMERICAN EXPRESS", re.I), "amex", None),
    (re.compile(r"payment to CRD (\d{4})", re.I), "boa_credit", 1),
]
UNMATCHED = "Card payments (no statement)"
# A payment is matched to the latest statement that closed at most this long before it.
MAX_STATEMENT_AGE = timedelta(days=45)


@dataclass
class Item:
    txn_id: int
    date: str
    merchant: str
    account: str
    amount_cents: int        # positive = spent (expenses) / received (income)
    via: str | None = None   # "Amex payment on 10/13" for charges pulled in through a card payment


@dataclass
class CategoryTotal:
    name: str
    total_cents: int = 0
    items: list[Item] = field(default_factory=list)
    via_cards_cents: int = 0


@dataclass
class CardPayment:
    txn_id: int
    date: str
    description: str
    amount_cents: int
    card: str | None
    statement: str | None    # "Sep 07 – Oct 07, 2026"
    method: str              # exact | previous | estimated | none
    allocations: list[tuple[str, int]] = field(default_factory=list)
    statement_id: int | None = None


@dataclass
class Summary:
    view: str
    month: str | None
    income_cents: int
    expense_cents: int
    income: list[CategoryTotal]
    expenses: list[CategoryTotal]
    card_payments: list[CardPayment]

    @property
    def net_cents(self) -> int:
        return self.income_cents - self.expense_cents


def months(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT substr(date, 1, 7) AS m FROM transactions ORDER BY m DESC")
    return [r["m"] for r in rows]


def income_account_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM accounts WHERE is_income_source = 1").fetchone()
    return row["id"] if row else None


TXN_SELECT = """
    SELECT t.id, t.date, t.description, t.merchant, t.amount_cents, t.account_id, t.statement_id,
           a.name AS account, c.name AS category, c.kind
    FROM transactions t
    JOIN accounts a ON a.id = t.account_id
    LEFT JOIN categories c ON c.id = t.category_id
"""


def _month_clause(month: str | None) -> tuple[str, list]:
    return ("AND t.date LIKE ?", [f"{month}-%"]) if month else ("", [])


def summary(conn: sqlite3.Connection, month: str | None, view: str = "cash") -> Summary:
    clause, params = _month_clause(month)
    income: dict[str, CategoryTotal] = {}
    expenses: dict[str, CategoryTotal] = {}
    payments: list[CardPayment] = []

    def add(bucket: dict, name: str, cents: int, item: Item | None):
        ct = bucket.setdefault(name, CategoryTotal(name))
        ct.total_cents += cents
        if item:
            ct.items.append(item)
        return ct

    def add_direct(r):
        name = r["category"] or "Uncategorized"
        if r["kind"] == "income":
            add(income, name, r["amount_cents"], _item(r, r["amount_cents"]))
        else:
            add(expenses, name, -r["amount_cents"], _item(r, -r["amount_cents"]))

    if view == "cash":
        acct = income_account_id(conn)
        rows = conn.execute(f"{TXN_SELECT} WHERE t.account_id = ? {clause} ORDER BY t.date", [acct, *params]) if acct else []
        for r in rows:
            if r["category"] == CARD_PAYMENT:
                payment = allocate_payment(conn, r)
                payments.append(payment)
                if not payment.allocations:
                    add(expenses, UNMATCHED, -r["amount_cents"], _item(r, -r["amount_cents"]))
                    continue
                via = f"{payment.card} payment on {r['date'][5:].replace('-', '/')}"
                by_cat = dict(payment.allocations)
                for c in by_cat:
                    expenses.setdefault(c, CategoryTotal(c))
                for ch in conn.execute(
                    f"{TXN_SELECT} WHERE t.statement_id = ? AND c.kind = 'expense' ORDER BY t.date",
                    (payment.statement_id,),
                ):
                    if ch["category"] in by_cat:
                        expenses[ch["category"]].items.append(_item(ch, -ch["amount_cents"], via))
                for c, cents in payment.allocations:
                    expenses[c].total_cents += cents
                    expenses[c].via_cards_cents += cents
            elif r["kind"] != "transfer":
                add_direct(r)
    else:
        rows = conn.execute(f"{TXN_SELECT} WHERE 1 = 1 {clause} ORDER BY t.date", params)
        for r in rows:
            if r["kind"] != "transfer":
                add_direct(r)

    inc = sorted(income.values(), key=lambda c: -c.total_cents)
    exp = sorted(expenses.values(), key=lambda c: -c.total_cents)
    return Summary(
        view=view, month=month,
        income_cents=sum(c.total_cents for c in inc),
        expense_cents=sum(c.total_cents for c in exp),
        income=inc, expenses=exp, card_payments=payments,
    )


def trend(conn: sqlite3.Connection, view: str = "cash") -> list[tuple[str, int, int]]:
    return [(m, s.income_cents, s.expense_cents)
            for m in sorted(months(conn))
            for s in [summary(conn, m, view)]]


# --- card payment -> card statement ------------------------------------------------------------

def find_card_account(conn: sqlite3.Connection, description: str) -> sqlite3.Row | None:
    for regex, source, group in CARD_TARGETS:
        m = regex.search(description)
        if not m:
            continue
        if group:
            row = conn.execute("SELECT * FROM accounts WHERE source = ? AND last4 = ?", (source, m.group(group))).fetchone()
            if row:
                return row
        return conn.execute("SELECT * FROM accounts WHERE source = ? ORDER BY id", (source,)).fetchone()
    return None


def pick_statement(conn: sqlite3.Connection, account_id: int, paid_on: date, amount_cents: int):
    """Which card statement did this payment pay off? Returns (statement row, method)."""
    stmts = conn.execute(
        "SELECT * FROM statements WHERE account_id = ? ORDER BY period_end", (account_id,)
    ).fetchall()
    closed_before = [s for s in stmts if date.fromisoformat(s["period_end"]) <= paid_on]
    # 1. A statement whose balance is exactly what was paid (autopay of the statement balance).
    exact = [s for s in closed_before if s["balance_cents"] == amount_cents]
    if exact:
        return exact[-1], "exact"
    # 2. Otherwise the most recent statement that had closed before the payment.
    recent = [s for s in closed_before if paid_on - date.fromisoformat(s["period_end"]) <= MAX_STATEMENT_AGE]
    if recent:
        return recent[-1], "previous"
    # 3. The statement it paid isn't uploaded: estimate with the closest statement we do have.
    if stmts:
        return min(stmts, key=lambda s: abs((date.fromisoformat(s["period_end"]) - paid_on).days)), "estimated"
    return None, "none"


def allocate_payment(conn: sqlite3.Connection, r: sqlite3.Row) -> CardPayment:
    amount = -r["amount_cents"]
    card = find_card_account(conn, r["description"])
    payment = CardPayment(r["id"], r["date"], r["merchant"], amount, card["name"] if card else None, None, "none")
    if not card:
        return payment
    stmt, method = pick_statement(conn, card["id"], date.fromisoformat(r["date"]), amount)
    if not stmt:
        return payment
    basis: dict[str, int] = defaultdict(int)
    for ch in conn.execute(
        f"{TXN_SELECT} WHERE t.statement_id = ? AND c.kind = 'expense'", (stmt["id"],)
    ):
        basis[ch["category"]] += -ch["amount_cents"]
    basis = {c: v for c, v in basis.items() if v > 0}
    if not basis:
        return payment
    start, end = date.fromisoformat(stmt["period_start"]), date.fromisoformat(stmt["period_end"])
    payment.statement = f"{start:%b %d} – {end:%b %d, %Y}"
    payment.method = method
    payment.statement_id = stmt["id"]
    payment.allocations = split_proportionally(amount, basis)
    return payment


def split_proportionally(total: int, weights: dict[str, int]) -> list[tuple[str, int]]:
    """Split total cents across keys by weight; shares sum to exactly total (largest remainder)."""
    wsum = sum(weights.values())
    raw = {k: total * w / wsum for k, w in weights.items()}
    shares = {k: int(v) for k, v in raw.items()}
    leftover = total - sum(shares.values())
    for k in sorted(raw, key=lambda k: raw[k] - shares[k], reverse=True)[:leftover]:
        shares[k] += 1
    return sorted(shares.items(), key=lambda kv: -kv[1])


def _item(r: sqlite3.Row, cents: int, via: str | None = None) -> Item:
    return Item(r["id"], r["date"], r["merchant"], r["account"], cents, via)
