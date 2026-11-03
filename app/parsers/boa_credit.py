"""Bank of America credit card eStatement (eStmt_YYYY-MM-DD.pdf, same name as checking)."""
import re
from datetime import date

from .common import AMOUNT_RE, ParsedStatement, ParsedTxn, cents, compare_totals, parse_date, printed_total

# "09/16 09/18 AMAZON MKTPLACE PMTS AMZN.COM/BILL WA 2469216ABCDEF 5646 43.21"
TXN_RE = re.compile(rf"^(\d{{2}}/\d{{2}})\s+\d{{2}}/\d{{2}}\s+(.+?)\s+({AMOUNT_RE})$")
SECTIONS = {
    "Payments and Other Credits": "payments",
    "Purchases and Adjustments": "charges",
    "Fees Charged": "charges",
    "Interest Charged": "charges",
}


def matches(text: str) -> bool:
    return "Bank of America" in text and ("Purchases and Adjustments" in text or "Payments and Other Credits" in text)


def parse(text: str) -> ParsedStatement:
    period = re.search(r"(\w+ \d{1,2}) - (\w+ \d{1,2}, \d{4})", text)
    acct = re.search(r"Account\s?(?:Number|#)[:\s]+(?:[X\d*]{4}\s){3}(\d{4})", text)
    balance = re.search(r"New Balance Total\s+(-?\$[\d,]+\.\d{2})", text)
    if not period:
        raise ValueError("Bank of America credit statement: could not find the statement period")
    end = parse_date(period.group(2), "%B %d, %Y")
    start = parse_date(f"{period.group(1)}, {end.year}", "%B %d, %Y")
    if start > end:
        start = start.replace(year=end.year - 1)

    stmt = ParsedStatement(
        source="boa_credit",
        kind="credit",
        account_name="Bank of America credit card",
        last4=acct.group(1) if acct else "0000",
        period_start=start,
        period_end=end,
        balance_cents=cents(balance.group(1)) if balance else None,
    )

    section = None
    for raw in text.splitlines():
        line = raw.strip()
        header = line.removesuffix(" continued").removesuffix(" - continued")
        if header in SECTIONS:
            section = SECTIONS[header]
            continue
        if section is None:
            continue
        if line.startswith("TOTAL ") or line.startswith("Total "):
            section = None
            continue
        m = TXN_RE.match(line)
        if not m or cents(m.group(3)) == 0:  # the $0.00 "INTEREST CHARGED ON ..." lines
            continue
        month, day = map(int, m.group(1).split("/"))
        # A January statement can hold December transactions.
        year = end.year - 1 if month > end.month else end.year
        desc = re.sub(r"\s+\w*\d\w*\s+\d{4}$", "", m.group(2))  # drop reference + account number
        stmt.transactions.append(ParsedTxn(
            date=date(year, month, day),
            description=desc,
            # Purchases are printed positive, payments/credits negative.
            amount_cents=-cents(m.group(3)),
            is_card_payment=section == "payments" and "PAYMENT" in desc.upper(),
        ))
    return stmt


def check(text: str, stmt: ParsedStatement) -> list[str]:
    parts = [printed_total(text, label) for label in ("Purchases and Adjustments", "Fees Charged", "Interest Charged")]
    return compare_totals([
        ("Payments and other credits", printed_total(text, "Payments and Other Credits"), stmt.credits()),
        ("Purchases + fees + interest", None if None in parts else sum(parts), stmt.debits()),
    ])
