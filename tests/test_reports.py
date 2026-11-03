import hashlib

import pytest

from app import db, importer, reports
from app.parsers import parse_text
from app.reports import split_proportionally

from .fixtures import AMEX, APPLE_CARD, BOA_CHECKING, BOA_CREDIT


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init(c)
    yield c
    c.close()


def load(conn, *texts):
    for text in texts:
        r = importer.save(conn, "x.pdf", hashlib.sha256(text.encode()).hexdigest(), parse_text(text))
        assert r.status == "imported", r.message


def by_name(cats):
    return {c.name: c.total_cents for c in cats}


def test_split_proportionally_sums_exactly():
    shares = dict(split_proportionally(100, {"a": 1, "b": 1, "c": 1}))
    assert sum(shares.values()) == 100
    assert sorted(shares.values()) == [33, 33, 34]


def test_cash_view_replaces_card_payments_with_card_categories(conn):
    load(conn, BOA_CHECKING, AMEX, APPLE_CARD, BOA_CREDIT)
    s = reports.summary(conn, "2026-10", "cash")

    assert by_name(s.income) == {"Salary": 300000}
    payments = {p.card.split(" ··")[0]: p for p in s.card_payments}

    # Amex $150 equals the statement's new balance -> exact match. Net spend on that statement:
    # Amazon 60, Clothing 40 - 10 refund = 30, Groceries 60  -> 150 split 60/30/60.
    amex = payments["American Express"]
    assert amex.method == "exact"
    assert dict(amex.allocations) == {"Amazon": 6000, "Clothing": 3000, "Groceries": 6000}

    # Apple $80 equals the September balance. Net spend: Dining 50, Health 20, Shopping -5 (a
    # return, dropped from the split), Electronics 15 -> 85, of which the payment covers 80.
    apple = payments["Apple Card"]
    assert apple.method == "exact"
    assert sum(c for _, c in apple.allocations) == 8000
    assert set(dict(apple.allocations)) == {"Dining", "Health", "Electronics"}

    # BoA credit card ..9999 ($40 statement closed 10/08, paid 10/14) is found by the CRD last 4.
    boa = payments["Bank of America credit card"]
    assert boa.method == "exact"
    assert dict(boa.allocations) == {"Education": 3000, "Utilities": 1000}

    exp = by_name(s.expenses)
    # Costco on the debit card (20.97) plus the Amex share (60.00)
    assert exp["Groceries"] == 2097 + 6000
    # The Comcast refund deposit reduces Phone & Internet rather than counting as income
    assert exp["Phone & Internet"] == -1211
    assert exp["Rent"] == 200000
    assert "Credit Card Payment" not in exp
    # Every dollar that left the account is accounted for
    assert s.expense_cents == 2097 + 1000 + 15000 + 8000 + 4000 + 200000 - 1211


def test_payment_before_any_statement_closed_is_estimated(conn):
    load(conn, BOA_CHECKING, AMEX)
    conn.execute("UPDATE statements SET period_end = '2026-10-20', balance_cents = 1")
    s = reports.summary(conn, "2026-10", "cash")
    amex = next(p for p in s.card_payments if p.card and p.card.startswith("American Express"))
    assert amex.method == "estimated"
    assert sum(c for _, c in amex.allocations) == 15000


def test_unmatched_card_payment_stays_one_line(conn):
    load(conn, BOA_CHECKING)
    s = reports.summary(conn, "2026-10", "cash")
    assert by_name(s.expenses)[reports.UNMATCHED] == 15000 + 8000 + 4000
    assert all(p.method == "none" for p in s.card_payments)


def test_accrual_view_counts_card_charges_and_ignores_payments(conn):
    load(conn, BOA_CHECKING, AMEX)
    s = reports.summary(conn, None, "accrual")
    exp = by_name(s.expenses)
    assert exp["Amazon"] == 6000
    assert exp["Clothing"] == 3000
    assert "Credit Card Payment" not in exp and "Card Payment Received" not in exp


def test_duplicate_upload_is_ignored(conn):
    load(conn, AMEX)
    again = importer.save(conn, "copy.pdf", "other-sha", parse_text(AMEX))
    assert again.status == "duplicate"
