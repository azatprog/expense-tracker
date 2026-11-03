import hashlib

import pytest
from fastapi.testclient import TestClient

from app import db, importer, plan
from app.parsers import parse_text

from .fixtures import BOA_CHECKING


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init(c)
    yield c
    c.close()


def load_month(conn, text, month):
    """Import a statement fixture with every date moved into `month` (YYYY-MM)."""
    y, m = map(int, month.split("-"))
    parsed = parse_text(text)
    for t in parsed.transactions:
        t.date = t.date.replace(year=y, month=m)
    parsed.period_start = parsed.period_start.replace(year=y, month=m, day=1)
    parsed.period_end = parsed.period_end.replace(year=y, month=m)
    importer.save(conn, f"{month}.pdf", hashlib.sha256(month.encode()).hexdigest(), parsed)


@pytest.mark.parametrize("values,expected", [
    ([10000, 10000, 10000], 10000),
    ([870000, 130275, 248751], 189513),       # car down payment month left out
    ([-1109238, 31179, 28032], 29605.5),      # insurance payout month left out
    ([30000, 0, 0], 10000),                   # occasional spending is still averaged
    ([291, 27934, 0], 9408.333333333334),     # mostly-zero category: plain average
    ([10000, 20000], 15000),                  # too little history to call anything a one-off
])
def test_typical(values, expected):
    assert plan.typical(values) == expected


def test_suggestions_come_from_previous_months(conn):
    for month in ("2026-08", "2026-09", "2026-10"):
        load_month(conn, BOA_CHECKING, month)
    p = plan.load(conn, "2026-11", 3)
    assert p.history == ["2026-08", "2026-09", "2026-10"]
    assert not p.saved and not p.has_actuals
    income = {line.name: line.amount_cents for line in p.income}
    expenses = {line.name: line.amount_cents for line in p.expenses}
    assert income == {"Salary": 300000}
    assert expenses["Rent"] == 200000
    assert p.left_cents == p.income_cents - p.expense_cents


def test_save_reload_and_reset(conn):
    load_month(conn, BOA_CHECKING, "2026-10")
    plan.save(conn, "2026-11", [("income", "Salary", 300000, []), ("expense", "Rent", 200000, []),
                                ("expense", "Thanksgiving trip", 45000, []), ("expense", "  ", 999, [])])
    p = plan.load(conn, "2026-11")
    assert p.saved
    assert [(line.name, line.amount_cents) for line in p.expenses] == [("Rent", 200000), ("Thanksgiving trip", 45000)]
    assert p.left_cents == 300000 - 245000
    # A saved line keeps the history average next to it for comparison.
    assert p.expenses[0].suggested_cents == 200000
    plan.reset(conn, "2026-11")
    assert not plan.load(conn, "2026-11").saved


def test_actuals_show_once_the_month_has_data(conn):
    load_month(conn, BOA_CHECKING, "2026-10")
    plan.save(conn, "2026-10", [("expense", "Rent", 210000, [])])
    p = plan.load(conn, "2026-10")
    assert p.has_actuals
    assert p.expenses[0].actual_cents == 200000


def test_plan_page_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "web.db")
    from app.main import app
    with TestClient(app) as client:
        assert client.get("/plan?month=2026-11").status_code == 200
        r = client.post("/plan", data={
            "month": "2026-11", "basis": "3",
            "kind": ["income", "expense", "expense"],
            "name": ["Salary", "Rent", "Gifts"],
            "amount": ["11,222", "$2,352.50", "abc"],
            "categories": ["Salary", "Rent", ""],
        }, follow_redirects=False)
        assert r.status_code == 303
        page = client.get("/plan?month=2026-11").text
        assert "Your saved plan for 2026-11" in page
        assert "$8,869.50" in page  # 11,222 - 2,352.50 - 0



def test_line_linked_to_several_categories_sums_them(conn):
    load_month(conn, BOA_CHECKING, "2026-10")
    # The fixture month has Groceries $20.97 (Costco) and Tolls $10.00 (HCTRA).
    plan.save(conn, "2026-11", [("expense", "Groceries & road", 5000, ["Groceries", "Tolls"]),
                                ("expense", "Rent", 200000, [])])
    p = plan.load(conn, "2026-11", 1)
    road, rent = p.expenses
    assert road.categories == ["Groceries", "Tolls"]
    assert [part.category for part in road.parts] == ["Groceries", "Tolls"]
    assert road.suggested_cents == 2100 + 1000   # typicals are rounded to whole dollars
    assert rent.categories == [] and rent.suggested_cents == 200000   # unlinked: matches its own name


def test_migration_adds_categories_column_to_old_database(tmp_path):
    c = db.connect(tmp_path / "old.db")
    c.execute("CREATE TABLE budget_lines (id INTEGER PRIMARY KEY, month TEXT NOT NULL, kind TEXT NOT NULL,"
              " name TEXT NOT NULL, amount_cents INTEGER NOT NULL, position INTEGER NOT NULL DEFAULT 0)")
    c.execute("INSERT INTO budget_lines (month, kind, name, amount_cents) VALUES ('2026-11', 'expense', 'Rent', 1)")
    db.init(c)
    assert plan.load(c, "2026-11").expenses[0].categories == []
