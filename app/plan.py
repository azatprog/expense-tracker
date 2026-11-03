"""Monthly plan: expected income and expenses for a month, prefilled from recent months."""
import sqlite3
from dataclasses import dataclass

from . import reports

# Bookkeeping lines of the cash view that aren't real recurring spending.
NOT_PLANNABLE = {reports.OPENING, reports.NOT_UPLOADED}


@dataclass
class Line:
    kind: str                 # income | expense
    name: str
    amount_cents: int
    suggested_cents: int | None = None   # average of the history months, for comparison
    actual_cents: int | None = None      # what really happened, once the month has data


@dataclass
class Plan:
    month: str
    saved: bool               # False: showing suggestions that haven't been saved yet
    history: list[str]        # months the suggestions are averaged over
    income: list[Line]
    expenses: list[Line]
    has_actuals: bool

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


def suggestions(conn: sqlite3.Connection, months: list[str]) -> dict[str, dict[str, int]]:
    """Typical monthly cash-flow amount per category over `months`, rounded to whole dollars."""
    per_month: dict[str, dict[str, list[int]]] = {"income": {}, "expense": {}}
    for i, m in enumerate(months):
        s = reports.summary(conn, m, "cash")
        for kind, cats in (("income", s.income), ("expense", s.expenses)):
            for c in cats:
                if c.name not in NOT_PLANNABLE:
                    per_month[kind].setdefault(c.name, [0] * len(months))[i] = c.total_cents
    out: dict[str, dict[str, int]] = {"income": {}, "expense": {}}
    for kind, by_name in per_month.items():
        for name, values in by_name.items():
            cents = round(typical(values) / 100) * 100
            if cents >= 1000:
                out[kind][name] = cents
    return out


def typical(values: list[int]) -> float:
    """The average, leaving out one month that is more than double the others' average (a one-off
    like a car down payment). Occasional spending that is zero in other months is still averaged."""
    if len(values) >= 3:
        biggest = max(values)
        others = list(values)
        others.remove(biggest)
        rest = sum(others) / len(others)
        if rest > 0 and biggest > 2 * rest:
            return rest
    return sum(values) / len(values)


def load(conn: sqlite3.Connection, month: str, history_count: int = 3) -> Plan:
    history = history_months(conn, month, history_count)
    suggested = suggestions(conn, history) if history else {"income": {}, "expense": {}}

    rows = conn.execute(
        "SELECT kind, name, amount_cents FROM budget_lines WHERE month = ? ORDER BY position, id", (month,)
    ).fetchall()
    saved = bool(rows)
    if saved:
        lines = [Line(r["kind"], r["name"], r["amount_cents"]) for r in rows]
    else:
        lines = [Line(kind, name, cents)
                 for kind in ("income", "expense")
                 for name, cents in sorted(suggested[kind].items(), key=lambda kv: -kv[1])]

    actual = reports.summary(conn, month, "cash")
    actual_by = {"income": {c.name: c.total_cents for c in actual.income},
                 "expense": {c.name: c.total_cents for c in actual.expenses}}
    has_actuals = bool(actual.income or actual.expenses)
    for line in lines:
        line.suggested_cents = suggested[line.kind].get(line.name)
        if has_actuals:
            line.actual_cents = actual_by[line.kind].get(line.name, 0)

    return Plan(
        month=month, saved=saved, history=history,
        income=[line for line in lines if line.kind == "income"],
        expenses=[line for line in lines if line.kind == "expense"],
        has_actuals=has_actuals,
    )


def save(conn: sqlite3.Connection, month: str, lines: list[tuple[str, str, int]]) -> None:
    """Replace the month's plan with (kind, name, amount_cents) lines; blank names are dropped."""
    conn.execute("DELETE FROM budget_lines WHERE month = ?", (month,))
    conn.executemany(
        "INSERT INTO budget_lines (month, kind, name, amount_cents, position) VALUES (?, ?, ?, ?, ?)",
        [(month, kind, name.strip(), cents, i) for i, (kind, name, cents) in enumerate(lines) if name.strip()],
    )
    conn.commit()


def reset(conn: sqlite3.Connection, month: str) -> None:
    conn.execute("DELETE FROM budget_lines WHERE month = ?", (month,))
    conn.commit()


def planned_months(conn: sqlite3.Connection) -> list[str]:
    return [r["month"] for r in conn.execute("SELECT DISTINCT month FROM budget_lines ORDER BY month")]
