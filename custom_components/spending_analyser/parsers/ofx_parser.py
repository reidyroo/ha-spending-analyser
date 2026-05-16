"""OFX / QFX statement parser — handles both SGML (v1) and XML (v2) variants."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from .base import ParsedTransaction

_LOGGER = logging.getLogger(__name__)


def _parse_ofx_date(raw: str) -> str:
    """Parse OFX date strings like 20240131120000[+10:00] → 2024-01-31."""
    raw = raw.strip()
    # Strip timezone suffix e.g. [+10:00] or [-5:EST]
    raw = re.split(r"[\[<]", raw)[0]
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:len(fmt.replace("%", "XX").replace("X", ""))], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Fallback: grab first 8 digits
    digits = re.sub(r"\D", "", raw)[:8]
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    raise ValueError(f"Unrecognised OFX date: {raw!r}")


class OfxParser:
    """Parses OFX v1 (SGML) and OFX v2 (XML) files."""

    def parse(self, text: str) -> list[ParsedTransaction]:
        text = text.lstrip("﻿")
        if "<OFX>" in text or "<?OFX" in text:
            return self._parse_xml(text)
        return self._parse_sgml(text)

    # ------------------------------------------------------------------
    # SGML (v1) — tag:value pairs, no closing tags for simple elements
    # ------------------------------------------------------------------

    def _parse_sgml(self, text: str) -> list[ParsedTransaction]:
        results: list[ParsedTransaction] = []
        # Each STMTTRN block is one transaction
        for block in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.DOTALL | re.IGNORECASE):
            try:
                results.append(self._parse_sgml_block(block))
            except Exception as exc:
                _LOGGER.warning("Skipping OFX SGML block: %s", exc)
        return results

    @staticmethod
    def _sgml_val(block: str, tag: str) -> str:
        m = re.search(rf"<{tag}>(.*?)(?:<|\Z)", block, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    def _parse_sgml_block(self, block: str) -> ParsedTransaction:
        date = _parse_ofx_date(self._sgml_val(block, "DTPOSTED"))
        amount = float(self._sgml_val(block, "TRNAMT") or "0")
        description = (
            self._sgml_val(block, "MEMO")
            or self._sgml_val(block, "NAME")
            or self._sgml_val(block, "PAYEE")
        )
        fit_id = self._sgml_val(block, "FITID")
        trntype = self._sgml_val(block, "TRNTYPE")
        return ParsedTransaction(
            date=date,
            description=description,
            amount=amount,
            raw={"fitid": fit_id, "trntype": trntype},
        )

    # ------------------------------------------------------------------
    # XML (v2)
    # ------------------------------------------------------------------

    def _parse_xml(self, text: str) -> list[ParsedTransaction]:
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(re.sub(r"<\?OFX[^?]*\?>", "", text, count=1).strip())
        except Exception as exc:
            _LOGGER.warning("OFX XML parse failed, falling back to SGML mode: %s", exc)
            return self._parse_sgml(text)

        results: list[ParsedTransaction] = []
        for el in root.iter("STMTTRN"):
            try:
                date = _parse_ofx_date(el.findtext("DTPOSTED") or "")
                amount = float(el.findtext("TRNAMT") or "0")
                description = (
                    el.findtext("MEMO") or el.findtext("NAME") or el.findtext("PAYEE") or ""
                )
                fit_id = el.findtext("FITID") or ""
                trntype = el.findtext("TRNTYPE") or ""
                results.append(ParsedTransaction(
                    date=date,
                    description=description.strip(),
                    amount=amount,
                    raw={"fitid": fit_id, "trntype": trntype},
                ))
            except Exception as exc:
                _LOGGER.warning("Skipping OFX XML transaction: %s", exc)
        return results
