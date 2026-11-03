from datetime import date

import pytest

from app.parsers import merchant_name, parse_text
from app.parsers.common import cents

from .fixtures import AMEX, APPLE_CARD, BOA_CHECKING, BOA_CREDIT


def amounts(stmt):
    return [t.amount_cents for t in stmt.transactions]


def test_boa_checking():
    s = parse_text(BOA_CHECKING)
    assert (s.source, s.kind, s.last4) == ("boa_checking", "bank", "3333")
    assert (s.period_start, s.period_end) == (date(2026, 9, 26), date(2026, 10, 27))
    assert s.balance_cents == 100000
    assert amounts(s) == [300000, 1211, -2097, -1000, -15000, -8000, -4000, -200000]
    # continuation lines are joined, page-break ad text is not
    assert s.transactions[0].description.endswith("ID:1234567890 PPD")
    assert s.transactions[3].description.endswith("RECURRING")
    assert "Cash back" not in s.transactions[2].description


def test_apple_card():
    s = parse_text(APPLE_CARD)
    assert (s.source, s.kind) == ("apple_card", "credit")
    assert (s.period_start, s.period_end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert s.balance_cents == 8000
    assert amounts(s) == [50000, -5000, -2000, 500, -1500]
    assert s.transactions[0].is_card_payment
    assert s.transactions[-1].description == "Installment: Apple Store SUGAR LAND TX"
    assert s.transactions[-1].date == date(2026, 9, 30)


def test_amex():
    s = parse_text(AMEX)
    assert (s.source, s.last4, s.balance_cents) == ("amex", "3456", 15000)
    assert (s.period_start, s.period_end) == (date(2026, 9, 7), date(2026, 10, 7))
    assert amounts(s) == [9000, 1000, -6000, -4000, -6000]
    assert [t.is_card_payment for t in s.transactions] == [True, False, False, False, False]
    assert s.transactions[2].description.endswith("MERCHANDISE")
    assert "8009266299" not in s.transactions[3].description  # phone lines are dropped


def test_boa_credit():
    s = parse_text(BOA_CREDIT)
    assert (s.source, s.last4, s.balance_cents) == ("boa_credit", "9999", 4000)
    assert (s.period_start, s.period_end) == (date(2026, 9, 9), date(2026, 10, 8))
    assert amounts(s) == [10000, -3000, -1000]  # $0.00 interest lines skipped
    assert s.transactions[0].is_card_payment
    assert s.transactions[1].description == "SCHOOLCAFE HOUSTON TX"


def test_unknown_statement():
    with pytest.raises(ValueError):
        parse_text("Some other bank\n01/01/26 THING 1.00")


@pytest.mark.parametrize("text,expected", [
    ("-$1,234.56", -123456), ("$0.07", 7), ("1,197.75", 119775), ("-10.00", -1000),
])
def test_cents(text, expected):
    assert cents(text) == expected


@pytest.mark.parametrize("desc,expected", [
    ("CHECKCARD 1014 COMCAST / XFINITY 8002662278 TX 5543286628720294563", "COMCAST / XFINITY"),
    ("COSTCO WHSE #1 10/01 #000224743 PURCHASE COSTCO WHSE #14 STAFFORD TX", "COSTCO WHSE"),
    ("AMERICAN EXPRESS DES:ACH PMT ID:M5304", "AMERICAN EXPRESS"),
    ("OBC*INDIGO ORTHODONTIC7623 W GRAND PKWY S STE 100 RICHMOND 77407 TX USA", "OBC*INDIGO ORTHODONTIC"),
    ("Zelle payment to Harun Ozay Conf# vm4r2sxg7", "Zelle payment to Harun Ozay"),
])
def test_merchant_name(desc, expected):
    assert merchant_name(desc) == expected
