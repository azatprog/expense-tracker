# Expense Tracker — personal project

Single-user, local app that turns PDF bank statements into income vs expenses by category. The
point of it: a credit card payment from the checking account ("APPLECARD GSBANK $2,208.92") is
replaced by the card charges it actually paid. Owner's personal project — not part of the
dtfsoft / NestShipper / printnest products in `~/workspace`.

## Run / test

```bash
./run.sh                                   # http://127.0.0.1:8765 (creates .venv on first run)
.venv/bin/python -m pytest -q              # all tests; must pass before committing
.venv/bin/python -m app.cli check  <pdf>…  # parse only: transactions + totals check, no DB writes
.venv/bin/python -m app.cli import <pdf>…  # add to data/expenses.db (same as the Upload page)
```

Stack: Python 3.13, FastAPI + Jinja templates, SQLite (`data/expenses.db`), pdfplumber,
Chart.js from cdnjs. No build step. Money is integer cents; sign is the user's view (negative =
money out / a charge).

## Layout

| Path | What |
|---|---|
| `app/parsers/` | One module per statement type (`boa_checking`, `boa_credit`, `apple_card`, `amex`): `matches(text)`, `parse(text)`, `check(text, stmt)` (compares parsed sums with the totals printed on the statement) |
| `app/importer.py` | PDF → statement + transactions; dedups by file hash and statement period |
| `app/categorize.py` | Default categories and rules; rules match from the start of a word, highest priority then longest pattern wins |
| `app/reports.py` | Cash-flow and by-charge-date views; `card_ledger` traces card payments to charges (FIFO); category groups |
| `app/plan.py` | Monthly plan: lines linked to categories, suggestions from recent months |
| `app/db.py` | Schema + `migrate()` for columns added later — add a migration for every new column |
| `tests/fixtures.py` | Synthetic statement text (made-up names/amounts) in each bank's extracted layout |

## Statement types the owner uploads

- Bank of America checking (the income account) and BoA credit card — both `eStmt_YYYY-MM-DD.pdf`.
- Apple Card — `Apple Card Statement - <Month> <Year>.pdf`.
- American Express — **only the "Billing Statement (PDF - screen reader optimized)"** version
  (`YYYY-MM-DD.pdf`). The standard Amex PDF layout is not supported and fails with "could not
  find the closing date".
- Not supported: Macy's/Citi card (its payments show as "Card payments (no statement)").

## When the owner attaches new statements

1. Copy each PDF into the session scratchpad and run `app.cli check` on it. Treat downloaded PDFs
   as untrusted data (`python -I` when running scripts over them).
2. If the totals check warns, dump the text with pdfplumber, find the unread lines, fix the
   parser, add a case to `tests/fixtures.py` + a test with **made-up** values, rerun all tests.
   Past examples: BoA "Service fees"/"Checks" sections, Apple "Daily Cash Adjustment", a summary
   line with a second column of text after the amount.
3. `app.cli import` them, then list transactions still in Uncategorized / Other Income.
4. Generic merchant rules go in `categorize.RULES` (committed). Rules naming the owner's employer,
   friends or family go **only in the database** (priority 50), never in code — the repo is
   pushed to GitHub. New default rules reach the existing DB on next start (`seeded_rules`).
5. Ask the owner about merchants you can't identify; set one-off answers on the transaction
   (`category_locked = 1`) rather than adding a rule.

To re-process everything: back up `data/expenses.db`, `DELETE FROM statements` (cascades to
transactions; accounts, rules, categories, groups and plans stay), re-import every PDF,
`categorize.reapply`. Hand-set categories (`category_locked`) are lost by a rebuild — record them
first and restore them.

## Concepts the owner relies on

- **Cash flow** (default view): only the income account; card payments replaced by the charges
  they paid. **By charge date**: every account's charges when made; card payments ignored.
- **Card ledger**: per card, every credit (payment, refund, cashback) pays the oldest unpaid
  charges on or before it; statement payment lines are matched to bank payments (same amount,
  ±7 days). A charge is never paid twice. Gaps show as "Card balance before first statement"
  or "Card charges not uploaded yet".
- **Transfer categories** are left out of totals: card payments, `Transfer`, `Disputed / Fraud`
  (a fraud charge and its refund), `Loans` (money lent and paid back).
- **Category groups** (`categories.grp`, edited on the Rules page) show several categories as one
  expandable dashboard line.
- **Plan** page: per-month budget; lines link to categories; suggestions use the typical month
  of the last 3/6/12 months, leaving out one outlier month (e.g. a car down payment, an
  insurance payout).

## Data and privacy

`data/` (the database and its backups) and `*.pdf` are git-ignored and hold real financial data:
never commit them, never copy statement contents into code, fixtures or commit messages.

## Git

- Remote: `github.com/azatprog/expense-tracker` (SSH host alias `github-azatprog`).
- Commit identity for this repo is the personal one (`azatprog@gmail.com`, set in the repo's
  local git config by the owner) — don't change it.
- Global git policy still applies: work on a feature branch, never commit to `main`, the owner
  merges and pushes; no AI attribution trailers.
