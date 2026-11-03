"""Monthly plan: expected income and expenses for a month, prefilled from recent months.

A plan line can be linked to one or more categories (e.g. "Groceries & shopping" → Groceries,
Amazon, Clothing, Dining). Its average and actual are the sums over those categories, and the
line can be expanded to see them one by one. A line with no links matches the category of the
same name.
"""
import sqlite3
import statistics
from dataclasses import dataclass, field

from . import reports

# Bookkeeping lines of the cash view that aren't real recurring spending.
NOT_PLANNABLE = {reports.OPENING, reports.NOT_UPLOADED}
# Suggested lines smaller than this are left out of a fresh plan.
MIN_SUGGESTION_CENTS = 1000
# A category whose middle month is below this is occasional spending: no month is a one-off.
OCCASIONAL_CENTS = 2000


@dataclass
class Part:
    category: str
    suggested_cents: int | None   # typical month for this category
    actual_cents: int | None      # this month, once it has data


@dataclass
class Line:
    kind: str                 # income | expense
    name: str
    amount_cents: int
    categories: list[str] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)

    @property
    def suggested_cents(self) -> int | None:
        known = [p.suggested_cents for p in self.parts if p.suggested_cents is not None]
        return sum(known) if known else None

    @property
    def actual_cents(self) -> int | None:
        known = [p.actual_cents for p in self.parts if p.actual_cents is not None]
        return sum(known) if known else None


@dataclass
class Plan:
    month: str
    saved: bool               # False: showing suggestions that haven't been saved yet
    history: list[str]        # months the suggestions are averaged over
    income: list[Line]
    expenses: list[Line]
    has_actuals: bool
    typical_by: dict[str, dict[str, int]] = field(default_factory=dict)   # kind -> category -> cents
    actual_by: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def income_cents(self) -> int:
        return sum(line.amount_cents for line in self.income)

    @property
    def expense_cents(self) -> int:
        return sum(line.amount_cents for line in self.expenses)

    @property
    def left_cents(self) -> int:
        return self.income_cents - self.expense_cents


def history_months(conn: sqlite3.Connection, month: str, count: int) -> list[str]:
    """The last `count` months with data before `month`."""
    return [m for m in sorted(reports.months(conn)) if m < month][-count:]


def typicals(conn: sqlite3.Connection, months: list[str]) -> dict[str, dict[str, int]]:
    """Typical monthly cash-flow amount per category over `months`, rounded to whole dollars."""
    per_month: dict[str, dict[str, list[int]]] = {"income": {}, "expense": {}}
    for i, m in enumerate(months):
        s = reports.summary(conn, m, "cash")
        for kind, cats in (("income", s.income), ("expense", s.expenses)):
            for c in cats:
                if c.name not in NOT_PLANNABLE:
                    per_month[kind].setdefault(c.name, [0] * len(months))[i] = c.total_cents
    return {kind: {name: round(typical(values) / 100) * 100 for name, values in by_name.items()}
            for kind, by_name in per_month.items()}


def typical(values: list[int]) -> float:
    """The average, leaving out the one month furthest from the median when it is more than twice
    the median away: a one-off like a car down payment, or an insurance payout that made a month
    negative. Categories that are usually zero (occasional spending) are plainly averaged."""
    if len(values) >= 3:
        med = statistics.median(values)
        if abs(med) >= OCCASIONAL_CENTS:
            far = max(values, key=lambda v: abs(v - med))
            if abs(far - med) > 2 * abs(med):
                rest = list(values)
                rest.remove(far)
                return sum(rest) / len(rest)
    return sum(values) / len(values)


def load(conn: sqlite3.Connection, month: str, history_count: int = 3) -> Plan:
    history = history_months(conn, month, history_count)
    typical_by = typicals(conn, history) if history else {"income": {}, "expense": {}}

    rows = conn.execute(
        "SELECT kind, name, amount_cents, categories FROM budget_lines WHERE month = ? ORDER BY position, id",
        (month,),
    ).fetchall()
    saved = bool(rows)
    if saved:
        lines = [Line(r["kind"], r["name"], r["amount_cents"], split_categories(r["categories"])) for r in rows]
    else:
        lines = [Line(kind, name, cents, [name])
                 for kind in ("income", "expense")
                 for name, cents in sorted(typical_by[kind].items(), key=lambda kv: -kv[1])
                 if cents >= MIN_SUGGESTION_CENTS]

    actual = reports.summary(conn, month, "cash")
    actual_by = {"income": {c.name: c.total_cents for c in actual.income},
                 "expense": {c.name: c.total_cents for c in actual.expenses}}
    has_actuals = bool(actual.income or actual.expenses)
    for line in lines:
        line.parts = [
            Part(cat, typical_by[line.kind].get(cat) if history else None,
                 actual_by[line.kind].get(cat, 0) if has_actuals else None)
            for cat in (line.categories or [line.name])
        ]

    return Plan(
        month=month, saved=saved, history=history,
        income=[line for line in lines if line.kind == "income"],
        expenses=[line for line in lines if line.kind == "expense"],
        has_actuals=has_actuals,
        typical_by=typical_by if history else {"income": {}, "expense": {}},
        actual_by=actual_by if has_actuals else {"income": {}, "expense": {}},
    )


def split_categories(text: str) -> list[str]:
    return [c.strip() for c in (text or "").split("|") if c.strip()]


def save(conn: sqlite3.Connection, month: str, lines: list[tuple[str, str, int, list[str]]]) -> None:
    """Replace the month's plan with (kind, name, amount_cents, categories) lines; blank names are dropped."""
    conn.execute("DELETE FROM budget_lines WHERE month = ?", (month,))
    conn.executemany(
        "INSERT INTO budget_lines (month, kind, name, amount_cents, categories, position) VALUES (?, ?, ?, ?, ?, ?)",
        [(month, kind, name.strip(), cents, "|".join(c.strip() for c in cats if c.strip()), i)
         for i, (kind, name, cents, cats) in enumerate(lines) if name.strip()],
    )
    conn.commit()


def reset(conn: sqlite3.Connection, month: str) -> None:
    conn.execute("DELETE FROM budget_lines WHERE month = ?", (month,))
    conn.commit()


def planned_months(conn: sqlite3.Connection) -> list[str]:
    return [r["month"] for r in conn.execute("SELECT DISTINCT month FROM budget_lines ORDER BY month")]
