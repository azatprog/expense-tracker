# Expense Tracker

Local, single-user app that tracks income vs expenses from PDF bank statements. Its main job:
when your income account shows "APPLECARD GSBANK PAYMENT $2,208.92", it replaces that line
with what you actually bought on the card (groceries, dental, education…).

Supported statements (type is auto-detected):

| Source | File you download |
|---|---|
| Bank of America checking / debit | `eStmt_YYYY-MM-DD.pdf` |
| Bank of America credit card | `eStmt_YYYY-MM-DD.pdf` |
| Apple Card | `Apple Card Statement - <Month> <Year>.pdf` |
| American Express | `YYYY-MM-DD.pdf` |

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765, upload statements, then pick your income account on **Accounts**
(the first bank account uploaded is picked automatically).

Data lives in `data/expenses.db` (SQLite, git-ignored). Set `EXPENSE_DB=/path/to.db` to use another file.
Statements are parsed in memory and not stored.

## Checking a statement parsed completely

Every import compares the parsed transactions with the totals printed on the statement
(deposits/withdrawals, payments/charges, fees, interest). A mismatch means some lines were not
read; it is shown on the Upload page and the statement is still imported. From the command line:

```bash
.venv/bin/python -m app.cli check  path/to/statement.pdf   # parse only, list transactions + totals check
.venv/bin/python -m app.cli import path/to/statement.pdf   # add to the database
```

## How the join works

1. Each bank-side transaction categorized **Credit Card Payment** is linked to a card account by
   its description: `APPLECARD GSBANK` → Apple Card, `AMERICAN EXPRESS … ACH PMT` → Amex,
   `payment to CRD 5646` → BoA credit card ending 5646.
2. Each card is run as a tab, first in, first out: every credit to the card pays off the oldest
   unpaid charges made on or before it.
   - Payments printed on the card statement are matched to the bank payment (same amount, within
     7 days); a bank payment whose card statement isn't uploaded yet still pays what's known.
   - A refund first pays off the latest unpaid charge in its own category (the purchase it
     refunds); cashback and other credits pay off the oldest charges like a payment.
   - What was owed before the earliest uploaded statement is one "Card balance before first
     statement" charge at the front of the queue.
3. In the cash-flow view, a bank card payment is replaced by exactly the charges it paid (partly
   paid charges show the paid part), so a charge is never counted twice, whether the card is paid
   in full by autopay or ad hoc mid-cycle. Anything a payment covered beyond the uploaded charges
   shows as "Card charges not uploaded yet".

Payments to cards with no uploaded statements (e.g. Macy's/Citi) stay as one
"Card payments (no statement)" line.

## Views

- **Cash flow**: only the income account. Income = deposits in income categories; expenses =
  direct debits plus card payments split into categories. Answers "where did my paycheck go".
- **By charge date**: every account's transactions on the day they happened, card payments
  ignored as transfers. Answers "what did I spend in October".

## Plan

**Plan** budgets a month up front: expected income and expenses per category, prefilled with the
typical cash-flow amount of the last 3, 6 or 12 months (a single month more than double the
others' average, like a one-off down payment, is left out). Edit amounts, remove lines or add your
own; "Left over" updates as you type, and **Save plan** stores it for that month. Once the
month's statements are uploaded, an "Actual" column shows what really happened.

## Categorizing

Rules (on **Rules**) are case-insensitive substrings of the description; higher priority wins,
then the longer pattern. Changing a category on **Transactions** pins it to that transaction;
tick "apply to all" to also create a rule and re-run it over everything. Categories have a kind:
`income`, `expense`, or `transfer` (excluded from totals).

## Tests

```bash
.venv/bin/python -m pytest
```

Tests use synthetic statement text in `tests/fixtures.py`. Never commit real statements or the database.
