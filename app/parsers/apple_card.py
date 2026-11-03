"""Apple Card monthly statement (Apple Card Statement - <Month> <Year>.pdf)."""
import re
from datetime import datetime

from .common import AMOUNT_RE, ParsedStatement, ParsedTxn, cents

PAYMENT_RE = re.compile(rf"^(\d{{2}}/\d{{2}}/\d{{4}})\s+(.+?)\s+({AMOUNT_RE})$")
# "<date> <merchant+address> <n>% $<daily cash> $<amount>"
CHARGE_RE = re.compile(rf"^(\d{{2}}/\d{{2}}/\d{{4}})\s+(.+?)\s+\d+%\s+{AMOUNT_RE}\s+({AMOUNT_RE})$")
INSTALLMENT_RE = re.compile(rf"^(\d{{2}}/\d{{2}}/\d{{4}})\s+(.+?)\s+({AMOUNT_RE})$")
THIS_MONTH_RE = re.compile(rf"^This month.s installment:\s+({AMOUNT_RE})")


def matches(text: str) -> bool:
    return "Apple Card" in text and "Goldman Sachs" in text


def parse(text: str) -> ParsedStatement:
    period = re.search(r"(\w{3}) (\d{1,2}) — (\w{3}) (\d{1,2}), (\d{4})", text)
    if not period:
        raise ValueError("Apple Card statement: could not find the statement period")
    m1, d1, m2, d2, year = period.groups()
    end = datetime.strptime(f"{m2} {d2} {year}", "%b %d %Y").date()
    start = datetime.strptime(f"{m1} {d1} {year}", "%b %d %Y").date()
    if start > end:  # Dec 1 — Dec 31 never crosses a year, but be safe
        start = start.replace(year=start.year - 1)

    # "Your October Balance ..." then the next line starts with "$1,010.74 $85.73 Nov 30, 2026".
    balance = re.search(r"Your \w+ Balance.*?\n.*?\n\s*(\$[\d,]+\.\d{2})", text)

    stmt = ParsedStatement(
        source="apple_card",
        kind="credit",
        account_name="Apple Card",
        last4="0000",  # Apple Card statements don't print a card number
        period_start=start,
        period_end=end,
        balance_cents=cents(balance.group(1)) if balance else None,
    )

    section = None
    pending_installment = None  # (description) waiting for its "This month's installment" line
    for raw in text.splitlines():
        line = raw.strip()
        if line == "Payments":
            section = "payments"
            continue
        if line == "Transactions":
            section = "transactions"
            continue
        if line == "Apple Card Monthly Installments":
            section = "installments"
            continue
        if line.startswith("Total ") and section in ("payments", "transactions"):
            section = None
            continue
        if line.startswith("Total financed") or line == "Daily Cash":
            section = None
            continue

        if section == "payments":
            m = PAYMENT_RE.match(line)
            if m:
                # Shown as -$x on the statement: money in from the card's point of view.
                stmt.transactions.append(ParsedTxn(
                    date=datetime.strptime(m.group(1), "%m/%d/%Y").date(),
                    description=m.group(2),
                    amount_cents=-cents(m.group(3)),
                    is_card_payment=True,
                ))
        elif section == "transactions":
            m = CHARGE_RE.match(line) or PAYMENT_RE.match(line)
            if m:
                # Charges are printed positive; returns/credits are printed -$x.
                stmt.transactions.append(ParsedTxn(
                    date=datetime.strptime(m.group(1), "%m/%d/%Y").date(),
                    description=m.group(2),
                    amount_cents=-cents(m.group(3)),
                ))
        elif section == "installments":
            m = INSTALLMENT_RE.match(line)
            if m:
                pending_installment = m.group(2)
                continue
            m = THIS_MONTH_RE.match(line)
            if m and pending_installment:
                # The installment is billed this month, so it is dated at statement close.
                stmt.transactions.append(ParsedTxn(
                    date=end,
                    description=f"Installment: {pending_installment}",
                    amount_cents=-abs(cents(m.group(1))),
                ))
                pending_installment = None
    return stmt
