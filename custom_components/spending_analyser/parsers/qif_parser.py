"""QIF (Quicken Interchange Format) statement parser."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from .base import ParsedTransaction

_LOGGER = logging.getLogger(__name__)

_DATE_FORMATS = [
    "%d/%m/%Y", "%d/%m'%Y", "%d/%m/%y",  # AU / UK
    "%m/%d/%Y", "%m/%d'%Y", "%m/%d/%y",  # US
    "%Y-%m-%d",
    "%-d/ %-m/%Y", "%-d/%-m/%Y",          # single-digit variants
]


def _parse_qif_date(raw: str) -> str:
    raw = raw.strip().replace("-", "/").replace("'", "/")
    # Normalise double-space or space-padded days: " 1/1/2024" → "01/01/2024"
    raw = re.sub(r"\s+", "", raw)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"Unrecognised QIF date: {raw!r}")


class QifParser:
    def parse(self, text: str) -> list[ParsedTransaction]:
        results: list[ParsedTransaction] = []
        current: dict[str, str] = {}

        for line in text.splitlines():
            line = line.rstrip("\r")
            if not line:
                continue
            if line.startswith("!"):
                continue  # account/type header
            if line == "^":
                if current:
                    try:
                        results.append(self._build(current))
                    except Exception as exc:
                        _LOGGER.warning("Skipping QIF record: %s — %s", exc, current)
                    current = {}
                continue

            code, _, value = line[0], line[0], line[1:].strip()
            code = line[0]
            value = line[1:]

            if code == "D":
                current["date"] = value
            elif code == "T":
                current["amount"] = value
            elif code == "P":
                current["payee"] = value
            elif code == "M":
                current["memo"] = value
            elif code == "N":
                current["number"] = value
            elif code == "L":
                current["category"] = value

        # File may not end with ^
        if current:
            try:
                results.append(self._build(current))
            except Exception as exc:
                _LOGGER.warning("Skipping final QIF record: %s", exc)

        return results

    @staticmethod
    def _build(rec: dict[str, str]) -> ParsedTransaction:
        date = _parse_qif_date(rec["date"])
        raw_amt = rec.get("amount", "0").replace(",", "")
        amount = float(raw_amt) if raw_amt else 0.0
        description = rec.get("payee") or rec.get("memo") or ""
        return ParsedTransaction(
            date=date,
            description=description.strip(),
            amount=amount,
            raw=rec,
        )
