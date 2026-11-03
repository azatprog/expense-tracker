"""Rule-based categorization: a rule is a case-insensitive substring of the transaction
description. The highest priority wins, then the longest pattern."""
import sqlite3

CARD_PAYMENT = "Credit Card Payment"            # bank side: money sent to a card
CARD_PAYMENT_RECEIVED = "Card Payment Received"  # card side: the same money arriving
DISPUTED = "Disputed / Fraud"                    # a charge and its refund, set by hand; nets to zero

CATEGORIES = {
    "income": ["Salary", "Zelle Received", "Rewards & Cashback", "Other Income"],
    # Loans: money lent out and paid back; neither is spending or income.
    "transfer": [CARD_PAYMENT, CARD_PAYMENT_RECEIVED, "Transfer", DISPUTED, "Loans"],
    "expense": [
        "Groceries", "Dining", "Amazon", "Shopping", "Clothing", "Electronics",
        "Rent", "Utilities", "Phone & Internet", "Home Services",
        "Car Payment", "Car Care", "Fuel", "Tolls", "Insurance",
        "Health", "Dental & Orthodontics", "Personal Care", "Education", "Kids Activities", "Fitness",
        "Subscriptions", "Entertainment", "Travel", "Gifts & Donations", "Taxes", "Government & Fees", "Cash Withdrawal", "Zelle Sent", "Uncategorized",
    ],
}

# (pattern, category, priority)
RULES = [
    ("DES:PAYROLL", "Salary", 10),
    ("Zelle payment from", "Zelle Received", 0),
    ("Zelle payment to", "Zelle Sent", 0),
    ("Garcia Cut Grass", "Home Services", 10),
    ("Redeem Cash Back", "Rewards & Cashback", 10),
    ("CASH REBATE", "Rewards & Cashback", 10),
    ("CASH REWARDS STATEMENT CREDIT", "Rewards & Cashback", 10),
    ("Daily Cash Adjustment", "Rewards & Cashback", 10),
    ("DES:CASHREWARD", "Rewards & Cashback", 10),
    ("APPLE CASH SENT", "Zelle Sent", 10),
    # Card payments, bank side
    ("APPLECARD GSBANK", CARD_PAYMENT, 20),
    ("AMERICAN EXPRESS DES:ACH PMT", CARD_PAYMENT, 20),
    ("payment to CRD", CARD_PAYMENT, 20),
    ("MACYS DES:ONLINE PMT", CARD_PAYMENT, 20),
    ("MACYS DES:AUTO PYMT", CARD_PAYMENT, 20),
    # Groceries
    ("COSTCO", "Groceries", 0), ("H-E-B", "Groceries", 0), ("SAM'S CLUB", "Groceries", 0),
    ("SAMS CLUB", "Groceries", 0), ("SAMSCLUB", "Groceries", 0),
    ("PHOENICIA", "Groceries", 0), ("GLOBUS MARKET", "Groceries", 0), ("KROGER", "Groceries", 0),
    ("WALMART", "Groceries", 0), ("WM SUPERCENTER", "Groceries", 0), ("WAL-MART", "Groceries", 0),
    ("FOOD STORE", "Groceries", 0), ("FOOD MART", "Groceries", 0), ("PECAN CREEK FOOD", "Groceries", 0),
    ("ALDI", "Groceries", 0), ("RUSSIAN GENERAL STORE", "Groceries", 0), ("TRADER JOE", "Groceries", 0), ("WHOLE FOODS", "Groceries", 0),
    # Dining
    ("UBER *EATS", "Dining", 5), ("DOORDASH", "Dining", 0), ("TST*", "Dining", 0),
    ("STARBUCKS", "Dining", 0), ("HIBACHI", "Dining", 0), ("HYDERABADI", "Dining", 0),
    ("WAFFLE HOUSE", "Dining", 0), ("DD/BR", "Dining", 0), ("DUNKIN", "Dining", 0), ("BAKERY", "Dining", 0), ("COFFEE", "Dining", 0),
    ("HAPPY CAKE", "Dining", 0), ("KABAB", "Dining", 0), ("CHURR", "Dining", 0), ("DPMN", "Dining", 0),
    ("TURKISH GRILL", "Dining", 0), ("SUSHI", "Dining", 0), ("NAYAX", "Dining", 0), ("365 MARKET", "Dining", 0), ("MCDONALD", "Dining", 0), ("CHICK-FIL-A", "Dining", 0),
    # Shopping
    ("Amazon Prime", "Subscriptions", 10), ("AMAZON", "Amazon", 0), ("AMZN", "Amazon", 0),
    ("T.J. MAXX", "Clothing", 0), ("MARSHALLS", "Clothing", 0), ("ROSS STORE", "Clothing", 0),
    ("BURLINGTON", "Clothing", 0), ("MACY", "Clothing", 0),
    ("DILLARDS", "Clothing", 0), ("SPORTSWEAR", "Clothing", 0),
    ("OLD NAVY", "Clothing", 0), ("ROSS DRESS", "Clothing", 0), ("SKECHERS", "Clothing", 0),
    ("House of Sport", "Shopping", 0), ("ETSY", "Shopping", 0), ("FEDEX", "Shopping", 0),
    ("HOMEGOODS", "Shopping", 0), ("IKEA", "Shopping", 0), ("FIVE BELOW", "Shopping", 0),
    ("GOODWILL", "Shopping", 0), ("CHRISTMAS VILLAGE", "Shopping", 0), ("TARGET", "Shopping", 0),
    ("Installment: Apple", "Electronics", 10), ("Apple Store", "Electronics", 5), ("AT&T DEVICE", "Electronics", 10),
    # Home & bills
    ("MOVE SALES INC", "Rent", 0), ("Rent-dr", "Rent", 0),
    ("AQUA DES", "Utilities", 0), ("CPENERGY", "Utilities", 0), ("RELIANT", "Utilities", 0),
    ("GEXA ENERGY", "Utilities", 0), ("BEST TRASH", "Utilities", 0),
    ("COMCAST", "Phone & Internet", 0), ("XFINITY", "Phone & Internet", 0), ("ATT DES:PAYMENT", "Phone & Internet", 0),
    ("AT&T BILL", "Phone & Internet", 0), ("AT&T *PAYMENT", "Phone & Internet", 0),
    # Car
    ("AUTONATION FINANC", "Car Payment", 0), ("MBFS", "Car Payment", 0), ("MERCEDES BENZ", "Car Payment", 0),
    ("EXXON", "Fuel", 0), ("SHELL", "Fuel", 0), ("CHEVRON", "Fuel", 0), ("BUC-EE", "Fuel", 0), ("PILOT", "Fuel", 0), ("LOVES #", "Fuel", 0),
    ("SUNOCO", "Fuel", 0), ("TEXACO", "Fuel", 0),
    ("CAR WASH", "Car Care", 0), ("DLR*MERCEDESBENZ", "Car Care", 10),
    ("LUBE", "Car Care", 0), ("AUTOZONE", "Car Care", 0), ("PARKING", "Car Care", 0), ("PMUSA", "Car Care", 0),
    ("HCTRA", "Tolls", 0), ("EZ TAG", "Tolls", 0),
    ("STATE FARM", "Insurance", 0), ("GEICO", "Insurance", 0),
    # Health & family
    ("UNITEDHEALTH", "Health", 0), ("KELSEY-SEYBOLD", "Health", 0), ("CVS", "Health", 0), ("MYUHC", "Health", 0), ("UHC EXCHANGES", "Health", 0),
    ("URGENT CARE", "Health", 0), ("EYE CARE", "Health", 0),
    ("KELSEY - SEYBOLD", "Health", 0), ("PRIMARY MEDI", "Health", 0), ("CLINIC", "Health", -1),
    ("WALGREENS", "Health", 0),
    ("DENTAL", "Dental & Orthodontics", 0), ("ENDODONT", "Dental & Orthodontics", 0), ("ORTHODONT", "Dental & Orthodontics", 0),
    ("UNIVERSITY", "Education", 0), ("SCHOOLCAFE", "Education", 0), ("MYEDUDOCS", "Education", 0), ("CISD", "Education", 0), ("SCHOOL TOOL BOX", "Education", 0),
    ("SCHOOLWEAR", "Education", 0), ("OLYMPIAD", "Education", 0), ("MARTIAL ARTS", "Kids Activities", 0),
    ("DYNAMIC FIT", "Fitness", 0),
    # Subscriptions & cash
    ("OPENAI", "Subscriptions", 0), ("NETFLIX", "Subscriptions", 0), ("APPLE.COM/BILL", "Subscriptions", 0),
    ("SPOTIFY", "Subscriptions", 0), ("DIGITALOCEAN", "Subscriptions", 0),
    ("GODADDY", "Subscriptions", 0), ("TRADINGVIEW", "Subscriptions", 0), ("DELLMONT", "Subscriptions", 0),
    ("BARBER", "Personal Care", 0), ("BABER OF AMERICA", "Personal Care", 0),
    ("PLAYSTATION", "Entertainment", 0), ("TEBEX", "Entertainment", 0), ("ROBLOX", "Entertainment", 0), ("CINEMA", "Entertainment", 0),
    ("TX DPS", "Government & Fees", 0), ("Wire Transfer Fee", "Government & Fees", 10),
    ("Monthly Maintenance Fee", "Government & Fees", 10),
    ("VEHREG", "Government & Fees", 0), ("TXDOT", "Government & Fees", 0), ("TEXAS.GOV", "Government & Fees", 0),
    ("DES:USATAXPYMT", "Taxes", 10), ("TURBOTAX", "Taxes", 0),
    ("SUPER.COM", "Travel", 0), ("IAH ", "Travel", 0), ("MARGARITAVILLE", "Travel", 0),
    ("GOFUNDME", "Gifts & Donations", 0), ("GFM*", "Gifts & Donations", 0), ("GOFNDME", "Gifts & Donations", 0),
    ("RAIN DROP FOUNDATION", "Gifts & Donations", 0), ("CHARITABLE ORG", "Gifts & Donations", 0), ("HOTEL", "Travel", 0), ("AIRBNB", "Travel", 0),
    ("ATM", "Cash Withdrawal", -5),
]


def seed(conn: sqlite3.Connection) -> None:
    """Add default categories and rules that this database hasn't had yet. A default rule is added
    once (recorded in seeded_rules), so one the user deleted or changed is left alone."""
    for kind, names in CATEGORIES.items():
        conn.executemany("INSERT OR IGNORE INTO categories (name, kind) VALUES (?, ?)", [(n, kind) for n in names])
    ids = category_ids(conn)
    seeded = {r[0] for r in conn.execute("SELECT pattern FROM seeded_rules")}
    new = [(p, ids[c], prio) for p, c, prio in RULES if p not in seeded]
    conn.executemany("INSERT OR IGNORE INTO rules (pattern, category_id, priority) VALUES (?, ?, ?)", new)
    conn.executemany("INSERT INTO seeded_rules (pattern) VALUES (?)", [(p,) for p, _, _ in new])


def category_ids(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}


def load_rules(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute("SELECT pattern, category_id, priority FROM rules").fetchall()
    rows = sorted(rows, key=lambda r: (-r["priority"], -len(r["pattern"])))
    return [(r["pattern"].upper(), r["category_id"]) for r in rows]


def categorize(description: str, amount_cents: int, is_card_payment: bool,
               rules: list[tuple[str, int]], ids: dict[str, int]) -> int:
    if is_card_payment:
        return ids[CARD_PAYMENT_RECEIVED]
    text = description.upper()
    for pattern, category_id in rules:
        if pattern in text:
            return category_id
    return ids["Other Income"] if amount_cents > 0 else ids["Uncategorized"]


def reapply(conn: sqlite3.Connection) -> int:
    """Re-run the rules over every transaction that wasn't categorized by hand."""
    rules, ids = load_rules(conn), category_ids(conn)
    rows = conn.execute(
        "SELECT id, description, amount_cents, is_card_payment FROM transactions WHERE category_locked = 0"
    ).fetchall()
    for r in rows:
        cat = categorize(r["description"], r["amount_cents"], bool(r["is_card_payment"]), rules, ids)
        conn.execute("UPDATE transactions SET category_id = ? WHERE id = ?", (cat, r["id"]))
    conn.commit()
    return len(rows)
