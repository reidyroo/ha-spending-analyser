"""Statement parsers — CSV (midata + AU banks), OFX, QIF."""
from __future__ import annotations

import os
from typing import Any

from .base import ParsedTransaction
from .csv_parser import CsvParser
from .ofx_parser import OfxParser
from .qif_parser import QifParser

__all__ = ["ParsedTransaction", "parse_statement"]


def parse_statement(
    content: str | bytes,
    filename: str = "",
    csv_column_map: dict[str, str] | None = None,
) -> list[ParsedTransaction]:
    """Parse a bank statement and return a list of transactions.

    Format is inferred from the file extension, then from content sniffing.
    csv_column_map lets callers override column detection for exotic CSVs:
        {"date": "Txn Date", "description": "Details", "amount": "Amount"}
    """
    ext = os.path.splitext(filename)[1].lower()

    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content

    if ext in (".ofx", ".qfx"):
        return OfxParser().parse(text)
    if ext == ".qif":
        return QifParser().parse(text)

    # OFX/QIF sniff before assuming CSV
    stripped = text.lstrip()
    if stripped.startswith("OFXHEADER") or stripped.startswith("<OFX"):
        return OfxParser().parse(text)
    if stripped.startswith("!Type:"):
        return QifParser().parse(text)

    return CsvParser(column_map=csv_column_map).parse(text)
