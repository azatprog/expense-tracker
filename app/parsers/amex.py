"""American Express monthly statement (YYYY-MM-DD.pdf from americanexpress.com)."""
import re
from datetime import timedelta

from .common import AMOUNT_RE, ParsedStatement, ParsedTxn, cents, compare_totals, parse_date, printed_total

TXN_RE = re.compile(rf"^(\d{{2}}/\d{{2}}/\d{{2}})\*?\s+(.+?)\s+({AMOUNT_RE})$")
SECTIONS = {
    "Payments Details": "payments",
    "Credits Details": "credits",
    "New Charges Details": "charges",
}
END_RE = re.compile(r"^(Fees$|Total Fees|Interest Charged$|New Charges Summary|Payments and Credits Summary)")
PHONE_RE = re.compile(r"^[\d\-() ]{7,}$")


def matches(text: str) -> bool:
    return "American Express" in text and "Closing Date" in text


def parse(text: str) -> ParsedStatement:
    closing = re.search(r"Closing Date\s+(\d{2}/\d{2}/\d{2})", text)
    acct = re.search(r"Account Ending\s+([\d-]+)", text)
    balance = re.search(r"New Balance\s+(\$[\d,]+\.\d{2})", text)
    days = re.search(r"Days in Billing Period:\s*(\d+)", text)
    if not (closing and acct):
        raise ValueError("Amex statement: could not find the closing date or account number")
    end = parse_date(closing.group(1), "%m/%d/%y")
    start = end - timedelta(days=int(days.group(1)) - 1 if days else 30)

    stmt = ParsedStatement(
        source="amex",
        kind="credit",
        account_name="American Express",
        last4=acct.group(1).replace("-", "")[-4:],
        period_start=start,
        period_end=end,
        balance_cents=cents(balance.group(1)) if balance else None,
    )

    section = None
    current = None
    holder = None  # the card member name line repeats above each section
    name = re.search(r"Prepared for\s*\n\s*(.+)", text)
    if name:
        holder = name.group(1).strip()
    for raw in text.splitlines():
        line = raw.strip()
        if line in SECTIONS:
            section, current = SECTIONS[line], None
            continue
        if section is None:
            continue
        if END_RE.match(line):
            section = current = None
            continue
        if not line or line == holder or line.startswith(("*I", "* I")) or line.startswith(
            ("Date Description Amount", "Card Ending")
        ):
            current = None if line.startswith("Card Ending") else current
            continue
        m = TXN_RE.match(line)
        if m:
            amount = cents(m.group(3))
            current = ParsedTxn(
                date=parse_date(m.group(1), "%m/%d/%y"),
                description=m.group(2),
                # Charges are printed positive, payments and credits as -$x.
                amount_cents=-amount,
                is_card_payment=section == "payments",
            )
            stmt.transactions.append(current)
        elif current is not None and not PHONE_RE.match(line):
            current.description += " " + line
    return stmt


def check(text: str, stmt: ParsedStatement) -> list[str]:
    parts = [printed_total(text, label) for label in ("Plus New Charges", "Plus Fees", "Plus I ?nterest Charged")]
    return compare_totals([
        ("Payments and credits", printed_total(text, "Less Payments/Credits"), stmt.credits()),
        ("New charges + fees + interest", None if None in parts else sum(parts), stmt.debits()),
    ])
