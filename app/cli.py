"""Import or dry-run statements from the command line.

    python -m app.cli import  <pdf>...   # add to the database (same as the Upload page)
    python -m app.cli check   <pdf>...   # parse only: print transactions and totals warnings
"""
import sys
from pathlib import Path

from . import db, importer
from .parsers import merchant_name, parse_pdf


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("import", "check"):
        print(__doc__)
        return 2
    command, files = argv[0], argv[1:]
    failed = False
    if command == "check":
        for f in files:
            s = parse_pdf(Path(f).read_bytes())
            print(f"\n## {f}: {s.account_name} {s.last4} {s.period_start} → {s.period_end}, "
                  f"balance {s.balance_cents}, {len(s.transactions)} transactions")
            for t in s.transactions:
                print(f"  {t.date} {t.amount_cents / 100:>10.2f} {'PAY' if t.is_card_payment else '   '} "
                      f"{merchant_name(t.description)[:40]:40} | {t.description[:70]}")
            for w in s.warnings or ["totals match the statement"]:
                print(f"  {'⚠ ' if s.warnings else '✓ '}{w}")
            failed |= bool(s.warnings)
        return 1 if failed else 0

    conn = db.connect()
    db.init(conn)
    for f in files:
        r = importer.import_pdf(conn, Path(f).name, Path(f).read_bytes())
        print(f"{r.status:9} {r.file_name}: {r.message}")
        for w in r.warnings:
            print(f"  ⚠ {w}")
        failed |= r.status == "error" or bool(r.warnings)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
