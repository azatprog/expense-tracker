import re
from dataclasses import dataclass, field
from datetime import date, datetime

AMOUNT_RE = r"-?\$?-?[\d,]+\.\d{2}"


@dataclass
class ParsedTxn:
    date: date
    description: str
    amount_cents: int          # negative = money out / charge
    is_card_payment: bool = False


@dataclass
class ParsedStatement:
    source: str                # boa_checking | boa_credit | apple_card | amex
    kind: str                  # bank | credit
    account_name: str
    last4: str
    period_start: date
    period_end: date
    balance_cents: int | None
    transactions: list[ParsedTxn] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # parsed totals that disagree with the PDF

    def credits(self) -> int:
        return sum(t.amount_cents for t in self.transactions if t.amount_cents > 0)

    def debits(self) -> int:
        return -sum(t.amount_cents for t in self.transactions if t.amount_cents < 0)


def cents(text: str) -> int:
    """'-$1,234.56' / '$-1,234.56' / '1,234.56' -> signed cents."""
    t = text.replace("$", "").replace(",", "").strip()
    neg = t.startswith("-")
    t = t.lstrip("-")
    whole, frac = t.split(".")
    value = int(whole or 0) * 100 + int(frac)
    return -value if neg else value


def printed_total(text: str, label: str, signed: bool = False) -> int | None:
    """Cents of the first summary line '<label> <amount> [...]' (label is a regex), absolute unless
    signed. Two-column layouts can put unrelated text after the amount on the same line."""
    m = re.search(rf"^{label}\s+({AMOUNT_RE})(?:\s|$)", text, re.M)
    if not m:
        return None
    return cents(m.group(1)) if signed else abs(cents(m.group(1)))


def compare_totals(rows: list[tuple[str, int | None, int]]) -> list[str]:
    """rows of (what, printed on the statement, sum of parsed transactions) -> warnings."""
    out = []
    for what, printed, parsed in rows:
        if printed is None:
            out.append(f"Couldn't find the printed total for {what}")
        elif printed != parsed:
            out.append(f"{what}: statement says ${printed / 100:,.2f}, parsed ${parsed / 100:,.2f} "
                       f"(off by ${(printed - parsed) / 100:,.2f}) — some lines were not read")
    return out


def parse_date(text: str, fmt: str) -> date:
    return datetime.strptime(text, fmt).date()


def merchant_name(description: str) -> str:
    """Short display name: drop trailing store numbers, phones, addresses and processor noise."""
    d = description
    d = re.sub(r"^(CHECKCARD|PURCHASE)\s+\d{4}\s+", "", d)
    d = re.sub(r"^AplPay\s+", "", d)
    d = re.split(r"\s+DES:", d)[0]
    d = re.split(r"\s+Conf#", d)[0]
    # Apple Card glues the street address straight onto the merchant: "ORTHODONTIC7623 W GRAND".
    d = re.split(r"(?<=[A-Za-z*.\-]) ?\d{3,}", d)[0]
    d = re.split(r"\s+#\d", d)[0]
    d = re.split(r"\s+\d{2}/\d{2}\b", d)[0]
    return re.sub(r"\s+", " ", d).strip(" -*") or description.strip()
