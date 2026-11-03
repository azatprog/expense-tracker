import hashlib

import pytest

from app import db, importer, reports
from app.parsers import parse_text

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


def test_cash_view_replaces_card_payments_with_the_charges_they_paid(conn):
    load(conn, BOA_CHECKING, AMEX, APPLE_CARD, BOA_CREDIT)
    s = reports.summary(conn, "2026-10", "cash")

    assert by_name(s.income) == {"Salary": 300000}
    payments = {p.card.split(" ··")[0]: p for p in s.card_payments}

    # Amex: the $90 payment on the statement (bank side not uploaded) paid the $90 opening balance;
    # the $10 T.J. Maxx refund went against the T.J. Maxx charge; the bank's $150 paid the rest.
    amex = payments["American Express"]
    assert dict(amex.allocations) == {"Amazon": 6000, "Clothing": 3000, "Groceries": 6000}
    assert (amex.opening_cents, amex.missing_cents) == (0, 0)

    # Apple: the two returns and the $500 payment on the statement used up the $509.90 opening
    # balance and $5.10 of Uber Eats; the bank's $80 paid the remaining $44.90 of it, Kelsey $20,
    # the $0.10 Daily Cash clawback and the $15 installment.
    apple = payments["Apple Card"]
    assert dict(apple.allocations) == {"Dining": 4490, "Health": 2000, "Electronics": 1500, "Rewards & Cashback": 10}

    # BoA credit card ..9999 is found by the "CRD 9999" in the bank description.
    boa = payments["Bank of America credit card"]
    assert dict(boa.allocations) == {"Education": 3000, "Utilities": 1000}

    exp = by_name(s.expenses)
    # Costco on the debit card (20.97) plus the Amex H-E-B charge (60.00)
    assert exp["Groceries"] == 2097 + 6000
    # The Comcast refund deposit reduces Phone & Internet rather than counting as income
    assert exp["Phone & Internet"] == -1211
    assert exp["Rent"] == 200000
    assert "Credit Card Payment" not in exp
    # Every dollar that left the account is accounted for
    assert s.expense_cents == 2097 + 1000 + 15000 + 8000 + 4000 + 200000 - 1211


AMEX_TWO_PAYMENTS = """\
American Express
Account Ending 1-23456
Closing Date 10/07/26
New Balance $30.00
Less Payments/Credits $0.00
Plus New Charges $100.00
Plus Fees $0.00
Plus I nterest Charged $0.00
New Charges Details
09/06/26 H-E-B #749 RICHMOND TX $40.00
09/20/26 NETFLIX.COM 866-579-7172 CA $60.00
Fees
Days in Billing Period: 31
"""

BANK_TWO_PAYMENTS = """\
Bank of America, N.A.
for September 26, 2026 to October 27, 2026 Account number: 1111 2222 3333
Ending balance on October 27, 2026 $0.00
Deposits and other additions 0.00
ATM and debit card subtractions -0.00
Other subtractions -100.00
Checks -0.00
Service fees -0.00
Other subtractions
Date Description Amount
09/30/26 AMERICAN EXPRESS DES:ACH PMT ID:M1 INDN:JANE DOE CO ID:1 -50.00
10/20/26 AMERICAN EXPRESS DES:ACH PMT ID:M2 INDN:JANE DOE CO ID:1 -50.00
Total other subtractions -$100.00
"""


def test_charges_are_never_paid_twice(conn):
    load(conn, BANK_TWO_PAYMENTS, AMEX_TWO_PAYMENTS)
    payments = reports.card_ledger(conn, reports.income_account_id(conn))
    first, second = sorted(payments.values(), key=lambda p: p.date)
    # $50 on 9/30 pays H-E-B $40 and $10 of Netflix; $50 on 10/20 pays the other $50 of Netflix.
    assert dict(first.allocations) == {"Groceries": 4000, "Subscriptions": 1000}
    assert dict(second.allocations) == {"Subscriptions": 5000}
    total_paid = sum(c for p in payments.values() for _, c in p.allocations)
    assert total_paid == 10000


def test_payment_bigger_than_known_charges_is_flagged(conn):
    load(conn, BANK_TWO_PAYMENTS.replace("-50.00\n10/20", "-500.00\n10/20").replace("-100.00", "-550.00"),
         AMEX_TWO_PAYMENTS)
    first = min(reports.card_ledger(conn, reports.income_account_id(conn)).values(), key=lambda p: p.date)
    assert first.missing_cents == 50000 - 10000


def test_unmatched_card_payment_stays_one_line(conn):
    load(conn, BOA_CHECKING)
    s = reports.summary(conn, "2026-10", "cash")
    assert by_name(s.expenses)[reports.UNMATCHED] == 15000 + 8000 + 4000
    assert all(p.card is None for p in s.card_payments)


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


def test_new_default_rules_reach_an_existing_db_but_deleted_ones_stay_deleted(conn):
    conn.execute("DELETE FROM rules WHERE pattern = 'NETFLIX'")
    conn.execute("DELETE FROM rules WHERE pattern = 'ROBLOX'")
    conn.execute("DELETE FROM seeded_rules WHERE pattern = 'ROBLOX'")  # as if ROBLOX were a new default
    db.init(conn)
    patterns = {r[0] for r in conn.execute("SELECT pattern FROM rules")}
    assert "ROBLOX" in patterns and "NETFLIX" not in patterns
