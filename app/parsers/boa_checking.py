"""Bank of America checking/debit eStatement (eStmt_YYYY-MM-DD.pdf)."""
import re

from .common import AMOUNT_RE, ParsedStatement, ParsedTxn, cents, compare_totals, parse_date, printed_total

SECTIONS = {
    "Deposits and other additions": +1,
    "ATM and debit card subtractions": -1,
    "Other subtractions": -1,
    "Checks": -1,
    "Service fees": -1,
}
TXN_RE = re.compile(rf"^(\d{{2}}/\d{{2}}/\d{{2}})\s+(.+?)\s+({AMOUNT_RE})$")
# Lines that end a run of description continuation lines.
STOP_RE = re.compile(
    r"^(Total |continued on the next page|Date Description Amount|Page \d+ of|.*! Account #|"
    r"Withdrawals and other subtractions|This page intentionally|Note your Ending Balance)"
)


def matches(text: str) -> bool:
    return "Bank of America" in text and "Deposits and other additions" in text


def parse(text: str) -> ParsedStatement:
    period = re.search(r"for (\w+ \d{1,2}, \d{4}) to (\w+ \d{1,2}, \d{4})", text)
    acct = re.search(r"Account number:\s*([\d ]+\d)", text)
    ending = re.search(r"Ending balance on .+? (-?\$[\d,]+\.\d{2})", text)
    if not (period and acct):
        raise ValueError("Bank of America statement: could not find the period or account number")

    stmt = ParsedStatement(
        source="boa_checking",
        kind="bank",
        account_name="Bank of America checking",
        last4=acct.group(1).replace(" ", "")[-4:],
        period_start=parse_date(period.group(1), "%B %d, %Y"),
        period_end=parse_date(period.group(2), "%B %d, %Y"),
        balance_cents=cents(ending.group(1)) if ending else None,
    )

    sign = None          # +1 / -1 while inside a transaction section
    section = None
    current = None       # transaction still collecting continuation lines
    for raw in text.splitlines():
        line = raw.strip()
        header = line.removesuffix(" - continued")
        if header in SECTIONS:
            section, sign, current = header, SECTIONS[header], None
            continue
        if sign is None:
            continue
        if STOP_RE.match(line):
            current = None
            if line.startswith("Total "):
                sign = None
            continue
        m = TXN_RE.match(line)
        if m:
            current = ParsedTxn(
                date=parse_date(m.group(1), "%m/%d/%y"),
                # The Checks table only has the check number where the description would be.
                description=f"Check {m.group(2)}" if section == "Checks" else m.group(2),
                amount_cents=sign * abs(cents(m.group(3))),
            )
            stmt.transactions.append(current)
        elif current is not None and line:
            current.description += " " + line
    return stmt


def check(text: str, stmt: ParsedStatement) -> list[str]:
    parts = [printed_total(text, label) for label in
             ("ATM and debit card subtractions", "Other subtractions", "Checks", "Service fees")]
    return compare_totals([
        ("Deposits and other additions", printed_total(text, "Deposits and other additions"), stmt.credits()),
        ("Withdrawals (debit card + other + checks + fees)",
         None if None in parts else sum(parts), stmt.debits()),
    ])
