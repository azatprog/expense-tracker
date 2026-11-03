from io import BytesIO

import pdfplumber

from . import amex, apple_card, boa_checking, boa_credit
from .common import ParsedStatement, ParsedTxn, merchant_name

# Order matters: boa_checking before boa_credit (both say "Bank of America").
PARSERS = [apple_card, amex, boa_checking, boa_credit]

__all__ = ["ParsedStatement", "ParsedTxn", "merchant_name", "parse_pdf", "parse_text"]


def pdf_text(data: bytes) -> str:
    with pdfplumber.open(BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_text(text: str) -> ParsedStatement:
    for parser in PARSERS:
        if parser.matches(text):
            stmt = parser.parse(text)
            stmt.warnings = parser.check(text, stmt)
            return stmt
    raise ValueError("Unrecognized statement: expected Bank of America, Apple Card or American Express")


def parse_pdf(data: bytes) -> ParsedStatement:
    return parse_text(pdf_text(data))
