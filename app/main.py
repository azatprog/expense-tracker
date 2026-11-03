from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import categorize, db, importer, plan, reports

HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = db.connect()
    db.init(conn)
    conn.close()
    yield


app = FastAPI(title="Expense Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
# "/static/app.css?v=<mtime>" so browsers pick up a changed file instead of a cached copy.
templates.env.globals["static"] = lambda name: f"/static/{name}?v={int((HERE / 'static' / name).stat().st_mtime)}"
templates.env.filters["money"] = lambda cents: f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# --- dashboard ----------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, month: str | None = None, view: str = "cash", conn=Depends(get_conn)):
    view = "accrual" if view == "accrual" else "cash"
    months = reports.months(conn)
    if month is None and months:
        month = months[0]
    if month == "all":
        month = None
    s = reports.summary(conn, month, view)
    s.expenses = reports.group_categories(conn, s.expenses)
    return templates.TemplateResponse(request, "dashboard.html", {
        "s": s,
        "months": months,
        "month": month,
        "view": view,
        "trend": reports.trend(conn, view),
        "has_income_source": reports.income_account_id(conn) is not None,
        "has_data": bool(months),
    })


# --- monthly plan -------------------------------------------------------------------------------

def _add_months(month: str, n: int) -> str:
    y, m = map(int, month.split("-"))
    y, m = divmod(y * 12 + (m - 1) + n, 12)
    return f"{y:04d}-{m + 1:02d}"


def _cents(text: str) -> int:
    try:
        return round(float(text.replace("$", "").replace(",", "").strip() or 0) * 100)
    except ValueError:
        return 0


@app.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, month: str | None = None, basis: int = 3, conn=Depends(get_conn)):
    this_month = date.today().strftime("%Y-%m")
    month = month or this_month
    basis = basis if basis in (3, 6, 12) else 3
    options = set(reports.months(conn)) | set(plan.planned_months(conn)) | {
        _add_months(this_month, i) for i in range(3)} | {month}
    return templates.TemplateResponse(request, "plan.html", {
        "p": plan.load(conn, month, basis),
        "months": sorted(options, reverse=True),
        "this_month": this_month,
        "basis": basis,
        "categories": conn.execute("SELECT name, kind FROM categories ORDER BY name").fetchall(),
    })


@app.post("/plan")
async def save_plan(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    month, basis = form["month"], form.get("basis", "3")
    lines = zip(form.getlist("kind"), form.getlist("name"), map(_cents, form.getlist("amount")),
                map(plan.split_categories, form.getlist("categories")))
    plan.save(conn, month, [line for line in lines if line[0] in ("income", "expense")])
    return back(f"/plan?month={month}&basis={basis}")


@app.post("/plan/reset")
def reset_plan(month: str = Form(...), basis: int = Form(3), conn=Depends(get_conn)):
    plan.reset(conn, month)
    return back(f"/plan?month={month}&basis={basis}")


# --- upload -------------------------------------------------------------------------------------

@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse(request, "upload.html", {"results": None})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, files: list[UploadFile] = File(...), conn=Depends(get_conn)):
    results = []
    for f in files:
        data = await f.read()
        if not data.startswith(b"%PDF"):
            results.append(importer.ImportResult(f.filename, "error", "Not a PDF file"))
            continue
        results.append(importer.import_pdf(conn, f.filename, data))
    return templates.TemplateResponse(request, "upload.html", {"results": results})


# --- transactions -------------------------------------------------------------------------------

@app.get("/transactions", response_class=HTMLResponse)
def transactions(request: Request, month: str | None = None, account: int | None = None,
                 category: int | None = None, q: str | None = None, conn=Depends(get_conn)):
    where, params = ["1 = 1"], []
    if month:
        where.append("t.date LIKE ?"); params.append(f"{month}-%")
    if account:
        where.append("t.account_id = ?"); params.append(account)
    if category:
        where.append("t.category_id = ?"); params.append(category)
    if q:
        where.append("t.description LIKE ?"); params.append(f"%{q}%")
    rows = conn.execute(
        f"""SELECT t.*, a.name AS account, c.name AS category FROM transactions t
            JOIN accounts a ON a.id = t.account_id LEFT JOIN categories c ON c.id = t.category_id
            WHERE {' AND '.join(where)} ORDER BY t.date DESC, t.id""",
        params,
    ).fetchall()
    return templates.TemplateResponse(request, "transactions.html", {
        "rows": rows,
        "accounts": conn.execute("SELECT * FROM accounts ORDER BY kind, name").fetchall(),
        "categories": conn.execute("SELECT * FROM categories ORDER BY kind, name").fetchall(),
        "months": reports.months(conn),
        "f": {"month": month, "account": account, "category": category, "q": q or ""},
    })


class CategoryChange(BaseModel):
    category_id: int
    rule_pattern: str | None = None   # also create a rule so future uploads get this category


@app.post("/api/transactions/{txn_id}/category")
def set_category(txn_id: int, body: CategoryChange, conn=Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM categories WHERE id = ?", (body.category_id,)).fetchone():
        raise HTTPException(404, "Unknown category")
    if conn.execute(
        "UPDATE transactions SET category_id = ?, category_locked = 1 WHERE id = ?", (body.category_id, txn_id)
    ).rowcount == 0:
        raise HTTPException(404, "Unknown transaction")
    updated = 0
    if body.rule_pattern and body.rule_pattern.strip():
        conn.execute(
            "INSERT INTO rules (pattern, category_id, priority) VALUES (?, ?, 50)"
            " ON CONFLICT(pattern) DO UPDATE SET category_id = excluded.category_id, priority = 50",
            (body.rule_pattern.strip(), body.category_id),
        )
        conn.commit()
        updated = categorize.reapply(conn)
    conn.commit()
    return JSONResponse({"ok": True, "reapplied": updated})


# --- accounts -----------------------------------------------------------------------------------

@app.get("/accounts", response_class=HTMLResponse)
def accounts(request: Request, conn=Depends(get_conn)):
    accts = conn.execute("SELECT * FROM accounts ORDER BY kind, name").fetchall()
    stmts = conn.execute(
        """SELECT s.*, (SELECT COUNT(*) FROM transactions t WHERE t.statement_id = s.id) AS n
           FROM statements s ORDER BY s.period_end DESC"""
    ).fetchall()
    return templates.TemplateResponse(request, "accounts.html", {"accounts": accts, "statements": stmts})


@app.post("/accounts/income-source")
def set_income_source(account_id: int = Form(...), conn=Depends(get_conn)):
    conn.execute("UPDATE accounts SET is_income_source = (id = ?)", (account_id,))
    conn.commit()
    return back("/accounts")


@app.post("/statements/{statement_id}/delete")
def delete_statement(statement_id: int, conn=Depends(get_conn)):
    conn.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
    conn.execute("DELETE FROM accounts WHERE id NOT IN (SELECT account_id FROM statements)")
    conn.commit()
    return back("/accounts")


# --- rules & categories -------------------------------------------------------------------------

@app.get("/rules", response_class=HTMLResponse)
def rules(request: Request, conn=Depends(get_conn)):
    return templates.TemplateResponse(request, "rules.html", {
        "rules": conn.execute(
            """SELECT r.*, c.name AS category, c.kind FROM rules r JOIN categories c ON c.id = r.category_id
               ORDER BY r.priority DESC, c.name, r.pattern"""
        ).fetchall(),
        "categories": conn.execute("SELECT * FROM categories ORDER BY kind, name").fetchall(),
    })


@app.post("/rules")
def add_rule(pattern: str = Form(...), category_id: int = Form(...), priority: int = Form(10), conn=Depends(get_conn)):
    conn.execute(
        "INSERT INTO rules (pattern, category_id, priority) VALUES (?, ?, ?)"
        " ON CONFLICT(pattern) DO UPDATE SET category_id = excluded.category_id, priority = excluded.priority",
        (pattern.strip(), category_id, priority),
    )
    categorize.reapply(conn)
    return back("/rules")


@app.post("/rules/{rule_id}/delete")
def delete_rule(rule_id: int, conn=Depends(get_conn)):
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    categorize.reapply(conn)
    return back("/rules")


@app.post("/rules/reapply")
def reapply_rules(conn=Depends(get_conn)):
    categorize.reapply(conn)
    return back("/rules")


@app.post("/groups")
async def save_group(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    name, members = form["name"].strip(), form.getlist("categories")
    if name:
        conn.execute("UPDATE categories SET grp = NULL WHERE grp = ?", (name,))
        conn.executemany("UPDATE categories SET grp = ? WHERE name = ?", [(name, m) for m in members])
        conn.commit()
    return back("/rules#groups")


@app.post("/groups/delete")
def delete_group(name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("UPDATE categories SET grp = NULL WHERE grp = ?", (name,))
    conn.commit()
    return back("/rules#groups")


@app.post("/categories")
def add_category(name: str = Form(...), kind: str = Form("expense"), conn=Depends(get_conn)):
    if kind not in ("income", "expense", "transfer"):
        raise HTTPException(400, "kind must be income, expense or transfer")
    conn.execute("INSERT OR IGNORE INTO categories (name, kind) VALUES (?, ?)", (name.strip(), kind))
    conn.commit()
    return back("/rules")
