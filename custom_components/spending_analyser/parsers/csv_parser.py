"""CSV statement parser — midata (UK) + common Australian bank formats."""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any

from .base import ParsedTransaction

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Date format helpers
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%d/%m/%Y",   # 31/01/2024  — AU / UK
    "%d-%m-%Y",   # 31-01-2024
    "%Y-%m-%d",   # 2024-01-31  — ISO
    "%d/%m/%y",   # 31/01/24
    "%m/%d/%Y",   # 01/31/2024  — US
    "%d %b %Y",   # 31 Jan 2024
    "%d %B %Y",   # 31 January 2024
    "%Y%m%d",     # 20240131    — OFX-style sometimes appears in CSV
]


def _parse_date(raw: str) -> str:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date: {raw!r}")


def _parse_amount(raw: str) -> float:
    """Parse a currency string like '$1,234.56' or '(50.00)' to float."""
    raw = raw.strip()
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    value = float(cleaned) if cleaned else 0.0
    return -abs(value) if negative else value


# ---------------------------------------------------------------------------
# Format profiles
# ---------------------------------------------------------------------------

class _Profile:
    name: str

    def match(self, headers: list[str]) -> bool:
        raise NotImplementedError

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        raise NotImplementedError


class _MidataProfile(_Profile):
    """UK midata / Open Banking CSV.

    Headers: Transaction Date, Transaction Type, Sort Code, Account Number,
             Transaction Description, Debit Amount, Credit Amount, Balance
    """
    name = "midata"

    def match(self, headers: list[str]) -> bool:
        h = {h.strip().lower() for h in headers}
        return {"transaction date", "debit amount", "credit amount", "transaction description"} <= h

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        date = _parse_date(row["Transaction Date"])
        description = row.get("Transaction Description", "").strip()
        debit = row.get("Debit Amount", "").strip()
        credit = row.get("Credit Amount", "").strip()
        if debit:
            amount = -abs(_parse_amount(debit))
        elif credit:
            amount = abs(_parse_amount(credit))
        else:
            amount = 0.0
        account = row.get("Account Number", "").strip() or None
        return ParsedTransaction(date=date, description=description, amount=amount,
                                 account=account, raw=dict(row))


class _CommBankProfile(_Profile):
    """Commonwealth Bank of Australia.

    No headers: Date, Amount, Description, Balance  (4 columns)
    """
    name = "commbank"

    def match(self, headers: list[str]) -> bool:
        # CommBank exports have no header row; sniffer will see numeric-like "headers"
        h = [h.strip().lower() for h in headers]
        # Detect if first column looks like a date
        return len(h) >= 3 and re.match(r"\d{2}/\d{2}/\d{4}", headers[0].strip())

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        cols = list(row.values())
        date = _parse_date(cols[0])
        amount = _parse_amount(cols[1])
        description = cols[2].strip() if len(cols) > 2 else ""
        return ParsedTransaction(date=date, description=description, amount=amount, raw=dict(row))


class _ANZProfile(_Profile):
    """ANZ Bank Australia.

    Headers: Date, Amount, Description  (sometimes no header row)
    """
    name = "anz"

    def match(self, headers: list[str]) -> bool:
        h = [h.strip().lower() for h in headers]
        return h[:3] == ["date", "amount", "description"]

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        date = _parse_date(row["Date"])
        amount = _parse_amount(row["Amount"])
        description = row.get("Description", "").strip()
        return ParsedTransaction(date=date, description=description, amount=amount, raw=dict(row))


class _NABProfile(_Profile):
    """National Australia Bank.

    Headers: Date, Amount, Account Number, Description, Merchant Name, ...
    """
    name = "nab"

    def match(self, headers: list[str]) -> bool:
        h = {h.strip().lower() for h in headers}
        return {"date", "amount", "account number", "description"} <= h

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        date = _parse_date(row["Date"])
        amount = _parse_amount(row["Amount"])
        merchant = row.get("Merchant Name", "").strip()
        desc = row.get("Description", "").strip()
        description = merchant if merchant else desc
        account = row.get("Account Number", "").strip() or None
        return ParsedTransaction(date=date, description=description, amount=amount,
                                 account=account, raw=dict(row))


class _WestpacProfile(_Profile):
    """Westpac Bank Australia.

    Headers: BSB, Account Number, Transaction Date, Narration, Cheque Number,
             Debit, Credit, Balance, Transaction Type
    """
    name = "westpac"

    def match(self, headers: list[str]) -> bool:
        h = {h.strip().lower() for h in headers}
        return {"narration", "transaction date", "debit", "credit"} <= h

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        date = _parse_date(row["Transaction Date"])
        description = row.get("Narration", "").strip()
        debit = row.get("Debit", "").strip()
        credit = row.get("Credit", "").strip()
        if debit:
            amount = -abs(_parse_amount(debit))
        elif credit:
            amount = abs(_parse_amount(credit))
        else:
            amount = 0.0
        account = row.get("Account Number", "").strip() or None
        return ParsedTransaction(date=date, description=description, amount=amount,
                                 account=account, raw=dict(row))


class _STGeorgeBOQProfile(_Profile):
    """St George / Bank of Queensland / BankWest — shared format.

    Headers: Date, Description, Debit, Credit, Balance
    """
    name = "stgeorge_boq"

    def match(self, headers: list[str]) -> bool:
        h = [h.strip().lower() for h in headers]
        return h[:5] == ["date", "description", "debit", "credit", "balance"]

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        date = _parse_date(row["Date"])
        description = row.get("Description", "").strip()
        debit = row.get("Debit", "").strip()
        credit = row.get("Credit", "").strip()
        if debit:
            amount = -abs(_parse_amount(debit))
        elif credit:
            amount = abs(_parse_amount(credit))
        else:
            amount = 0.0
        return ParsedTransaction(date=date, description=description, amount=amount, raw=dict(row))


class _FirstDirectProfile(_Profile):
    """First Direct (HSBC UK).

    Headers: Date, Description, Amount, Balance
    Amounts are already signed: negative = debit, positive = credit.
    """
    name = "first_direct"

    def match(self, headers: list[str]) -> bool:
        h = [h.strip().lower() for h in headers]
        return h[:4] == ["date", "description", "amount", "balance"]

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        date = _parse_date(row["Date"])
        description = row.get("Description", "").strip()
        amount = _parse_amount(row.get("Amount", "0"))
        return ParsedTransaction(date=date, description=description, amount=amount, raw=dict(row))


class _NewdayJLProfile(_Profile):
    """Newday / John Lewis Finance credit card.

    Headers: Date, Description, Note, Amount(GBP)
    Amounts are unsigned positives for purchases and must be negated.
    Refunds/payments appear as negative values and should stay positive.
    Description = clean merchant name; Note = raw acquirer string.
    """
    name = "newday_jl"

    def match(self, headers: list[str]) -> bool:
        h = [h.strip().lower() for h in headers]
        return (
            len(h) >= 4
            and h[0] == "date"
            and h[1] == "description"
            and h[2] == "note"
            and h[3].startswith("amount")
        )

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        date = _parse_date(row["Date"])
        description = row.get("Description", "").strip()
        note = row.get("Note", "").strip()
        # Amount column may be named "Amount(GBP)" or "Amount(EUR)" etc.
        amt_key = next((k for k in row if k.lower().startswith("amount")), "")
        raw_amount = _parse_amount(row.get(amt_key, "0"))
        # Credit card convention: positive = purchase (expense), negative = refund/payment
        amount = -raw_amount if raw_amount > 0 else abs(raw_amount)
        return ParsedTransaction(
            date=date,
            description=description or note,
            amount=amount,
            raw={**dict(row), "_note": note},
        )


class _GenericProfile(_Profile):
    """Fallback: looks for common column names and maps them."""
    name = "generic"

    # Candidate column names for each field
    _DATE_COLS = ["date", "transaction date", "txn date", "posted date", "value date"]
    _DESC_COLS = ["description", "details", "narration", "memo", "reference",
                  "transaction description", "merchant"]
    _AMT_COLS  = ["amount", "net amount", "transaction amount"]
    _DEBIT_COLS = ["debit", "debit amount", "withdrawal"]
    _CREDIT_COLS = ["credit", "credit amount", "deposit"]

    def __init__(self, column_map: dict[str, str] | None = None) -> None:
        self._map = {k.lower(): v for k, v in (column_map or {}).items()}

    def match(self, headers: list[str]) -> bool:
        return True  # always matches as last resort

    def _find(self, headers_lower: list[str], candidates: list[str]) -> str | None:
        for c in candidates:
            if c in headers_lower:
                return c
        return None

    def parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        hl = [h.lower() for h in row.keys()]
        hr = {h.lower(): v for h, v in row.items()}

        date_col   = self._map.get("date")   or self._find(hl, self._DATE_COLS)
        desc_col   = self._map.get("description") or self._find(hl, self._DESC_COLS)
        amt_col    = self._map.get("amount")  or self._find(hl, self._AMT_COLS)
        debit_col  = self._map.get("debit")   or self._find(hl, self._DEBIT_COLS)
        credit_col = self._map.get("credit")  or self._find(hl, self._CREDIT_COLS)

        if not date_col:
            raise ValueError(f"Cannot find date column in: {list(row.keys())}")

        # column_map values may be original-case; hr keys are all lowercase
        date = _parse_date(hr[date_col.lower()])
        description = hr.get((desc_col or "").lower(), "").strip()

        amt_key = (amt_col or "").lower()
        if amt_key and hr.get(amt_key, "").strip():
            amount = _parse_amount(hr[amt_key])
        elif debit_col or credit_col:
            debit  = _parse_amount(hr.get((debit_col  or "").lower(), "") or "0")
            credit = _parse_amount(hr.get((credit_col or "").lower(), "") or "0")
            amount = credit - debit if credit >= debit else -debit + credit
        else:
            raise ValueError(f"Cannot find amount column in: {list(row.keys())}")

        return ParsedTransaction(date=date, description=description, amount=amount, raw=dict(row))


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------

_PROFILES: list[_Profile] = [
    _MidataProfile(),
    _NewdayJLProfile(),
    _FirstDirectProfile(),
    _ANZProfile(),
    _NABProfile(),
    _WestpacProfile(),
    _STGeorgeBOQProfile(),
]


class CsvParser:
    def __init__(self, column_map: dict[str, str] | None = None) -> None:
        self._generic = _GenericProfile(column_map)

    def parse(self, text: str) -> list[ParsedTransaction]:
        # Strip BOM and normalise line endings
        text = text.lstrip("﻿")

        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;|")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)

        # CommBank has no headers — detect by first data row
        first_line = text.splitlines()[0]
        headers = [h.strip() for h in first_line.split(dialect.delimiter)]

        # Try headed profiles first; CommBank needs raw first-line check
        commbank = _CommBankProfile()
        if commbank.match(headers):
            return self._parse_with(commbank, text, dialect, has_header=False)

        for profile in _PROFILES:
            if profile.match(headers):
                _LOGGER.debug("CSV format detected: %s", profile.name)
                return self._parse_with(profile, text, dialect, has_header=True)

        _LOGGER.debug("CSV format detected: generic")
        return self._parse_with(self._generic, text, dialect, has_header=True)

    @staticmethod
    def _parse_with(
        profile: _Profile, text: str, dialect: csv.Dialect, has_header: bool
    ) -> list[ParsedTransaction]:
        results: list[ParsedTransaction] = []
        if has_header:
            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
            rows = list(reader)
        else:
            # No header — assign positional keys 0, 1, 2, ...
            lines = [r for r in csv.reader(io.StringIO(text), dialect=dialect)]
            rows = [dict(enumerate(row)) for row in lines if any(c.strip() for c in row)]  # type: ignore[misc]

        for i, row in enumerate(rows):
            try:
                tx = profile.parse_row(row)  # type: ignore[arg-type]
                if tx.description or tx.amount:
                    results.append(tx)
            except Exception as exc:
                _LOGGER.warning("Skipping CSV row %d: %s — %s", i + 1, exc, row)
        return results
