"""Income vs expense reports.

Two views:
- cash:    what left the income account. A card payment is replaced by the card charges it paid off.
- accrual: every account's charges on the day they were made; card payments are just transfers.

Which charges a card payment paid is worked out per card like a running tab (first in, first out):
every credit to the card (a payment, a refund, cashback) pays off the oldest unpaid charges made
before it. Payments printed on the card statement are linked to the bank-side payment, so a charge
can only be paid once, whether the card is paid in full by autopay or ad hoc mid-cycle.
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
OPENING = "Card balance before first statement"   # owed before the earliest uploaded statement
NOT_UPLOADED = "Card charges not uploaded yet"     # payment larger than the charges we know about
# A bank-side payment and the card's "payment received" line are the same money if they are
# for the same amount and this close in date.
MATCH_WINDOW = timedelta(days=7)


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
class _Charge:
    txn: sqlite3.Row | None  # None for the opening balance
    date: str
    category: str
    remaining: int           # cents still unpaid


@dataclass
class CardPayment:
    txn_id: int
    date: str
    description: str
    amount_cents: int
    card: str | None
    paid: list[tuple[_Charge, int]] = field(default_factory=list)  # (charge, cents of it this paid)
    missing_cents: int = 0   # more than the uploaded charges: later card statements not uploaded

    @property
    def allocations(self) -> list[tuple[str, int]]:
        totals: dict[str, int] = defaultdict(int)
        for charge, cents in self.paid:
            totals[charge.category] += cents
        if self.missing_cents:
            totals[NOT_UPLOADED] += self.missing_cents
        return sorted(totals.items(), key=lambda kv: -kv[1])

    @property
    def opening_cents(self) -> int:
        return sum(cents for charge, cents in self.paid if charge.txn is None)

    @property
    def charge_dates(self) -> tuple[str, str] | None:
        dates = [charge.date for charge, _ in self.paid if charge.txn is not None]
        return (min(dates), max(dates)) if dates else None


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
    SELECT t.id, t.date, t.description, t.merchant, t.amount_cents, t.account_id, t.statement_id, t.is_card_payment,
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
        ledger = card_ledger(conn, acct) if acct else {}
        for r in rows:
            if r["category"] == CARD_PAYMENT:
                payment = ledger.get(r["id"]) or CardPayment(r["id"], r["date"], r["merchant"], -r["amount_cents"], None)
                payments.append(payment)
                if payment.card is None:
                    add(expenses, UNMATCHED, -r["amount_cents"], _item(r, -r["amount_cents"]))
                    continue
                via = f"{payment.card} payment on {r['date'][5:].replace('-', '/')}"
                for charge, cents in payment.paid:
                    if charge.txn is None:
                        item = Item(0, charge.date, "Balance owed before the first uploaded statement", payment.card, cents, via)
                    else:
                        full = -charge.txn["amount_cents"]
                        note = via if cents == full else f"{via} · part of ${full / 100:,.2f}"
                        item = _item(charge.txn, cents, note)
                    add(expenses, charge.category, cents, item).via_cards_cents += cents
                if payment.missing_cents:
                    add(expenses, NOT_UPLOADED, payment.missing_cents,
                        _item(r, payment.missing_cents)).via_cards_cents += payment.missing_cents
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


def card_ledger(conn: sqlite3.Connection, income_account: int) -> dict[int, CardPayment]:
    """For every card payment from the income account: which card charges it paid off."""
    bank = conn.execute(
        f"{TXN_SELECT} WHERE t.account_id = ? AND c.name = ? ORDER BY t.date, t.id", (income_account, CARD_PAYMENT)
    ).fetchall()
    by_card: dict[int, list[sqlite3.Row]] = defaultdict(list)
    result: dict[int, CardPayment] = {}
    for b in bank:
        card = find_card_account(conn, b["description"])
        if card:
            by_card[card["id"]].append(b)
            result[b["id"]] = CardPayment(b["id"], b["date"], b["merchant"], -b["amount_cents"], card["name"])
    for card_id, payments in by_card.items():
        _run_card(conn, card_id, payments, result)
    return result


def _run_card(conn: sqlite3.Connection, card_id: int, bank_payments: list[sqlite3.Row],
              result: dict[int, CardPayment]) -> None:
    stmts = conn.execute("SELECT * FROM statements WHERE account_id = ? ORDER BY period_start", (card_id,)).fetchall()
    txns = conn.execute(
        f"{TXN_SELECT} WHERE t.account_id = ? ORDER BY t.date, t.id",
        (card_id,),
    ).fetchall()

    queue: list[_Charge] = []
    first = stmts[0] if stmts else None
    if first is not None and first["balance_cents"] is not None:
        # closing balance = opening balance - sum(signed amounts on that statement)
        opening = first["balance_cents"] + sum(t["amount_cents"] for t in txns if t["statement_id"] == first["id"])
        if opening > 0:
            day_before = (date.fromisoformat(first["period_start"]) - timedelta(days=1)).isoformat()
            queue.append(_Charge(None, day_before, OPENING, opening))

    unmatched = list(bank_payments)
    credits = []  # (date, cents, bank payment or None, refund category or None)
    for t in txns:
        if t["amount_cents"] < 0:
            queue.append(_Charge(t, t["date"], t["category"] or "Uncategorized", -t["amount_cents"]))
        elif t["is_card_payment"]:
            bank = _match_bank_payment(t, unmatched)
            credits.append((t["date"], t["amount_cents"], bank, None))
        else:
            credits.append((t["date"], t["amount_cents"], None, t["category"]))
    # Bank payments whose card statement isn't uploaded yet still pay off what we know about.
    credits += [(b["date"], -b["amount_cents"], b, None) for b in unmatched]
    credits.sort(key=lambda c: c[0])
    queue.sort(key=lambda c: (c.date, c.txn is not None))

    for when, cents, bank, refund_category in credits:
        paid, left = _pay_off(queue, when, cents, refund_category)
        if bank is not None:
            result[bank["id"]].paid = paid
            result[bank["id"]].missing_cents = left


def _match_bank_payment(card_txn: sqlite3.Row, candidates: list[sqlite3.Row]) -> sqlite3.Row | None:
    when = date.fromisoformat(card_txn["date"])
    for b in candidates:
        if -b["amount_cents"] == card_txn["amount_cents"] and abs(date.fromisoformat(b["date"]) - when) <= MATCH_WINDOW:
            candidates.remove(b)
            return b
    return None


def _pay_off(queue: list[_Charge], when: str, cents: int, prefer_category: str | None):
    """Pay `cents` towards unpaid charges dated on or before `when`. A refund first goes to the
    latest unpaid charge in its own category (the purchase it refunds); everything else, oldest
    first. Returns ([(charge, cents paid)], cents left over)."""
    paid: list[tuple[_Charge, int]] = []
    eligible = [c for c in queue if c.remaining > 0 and c.date <= when]
    if prefer_category:
        eligible = [c for c in reversed(eligible) if c.category == prefer_category] + \
                   [c for c in eligible if c.category != prefer_category]
    for charge in eligible:
        if cents == 0:
            break
        take = min(charge.remaining, cents)
        charge.remaining -= take
        cents -= take
        paid.append((charge, take))
    return paid, cents


def _item(r: sqlite3.Row, cents: int, via: str | None = None) -> Item:
    return Item(r["id"], r["date"], r["merchant"], r["account"], cents, via)
