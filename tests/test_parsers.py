"""Tests for CSV, OFX and QIF statement parsers."""
import pytest

from custom_components.spending_analyser.parsers import parse_statement
from custom_components.spending_analyser.parsers.csv_parser import CsvParser
from custom_components.spending_analyser.parsers.ofx_parser import OfxParser
from custom_components.spending_analyser.parsers.qif_parser import QifParser

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from samples import (
    ANZ_CSV, FIRST_DIRECT_CSV, MIDATA_CSV, NAB_CSV,
    NEWDAY_JL_CSV, OFX_SGML, OFX_XML, QIF_CONTENT, WESTPAC_CSV,
)


# ── CSV — format detection ────────────────────────────────────────────────────

class TestMidataCsv:
    def test_detects_format(self):
        txs = CsvParser().parse(MIDATA_CSV)
        assert len(txs) == 3

    def test_debit_is_negative(self):
        txs = CsvParser().parse(MIDATA_CSV)
        debits = [t for t in txs if "COSTA" in t.description]
        assert debits[0].amount == pytest.approx(-13.45)

    def test_credit_is_positive(self):
        txs = CsvParser().parse(MIDATA_CSV)
        salary = [t for t in txs if "SALARY" in t.description][0]
        assert salary.amount == pytest.approx(2000.00)

    def test_date_normalised_to_iso(self):
        txs = CsvParser().parse(MIDATA_CSV)
        assert txs[0].date == "2026-05-15"

    def test_account_number_captured(self):
        txs = CsvParser().parse(MIDATA_CSV)
        assert txs[0].account == "12345678"


class TestFirstDirectCsv:
    def test_detects_format(self):
        txs = CsvParser().parse(FIRST_DIRECT_CSV)
        assert len(txs) == 2

    def test_signed_amount_passthrough(self):
        txs = CsvParser().parse(FIRST_DIRECT_CSV)
        expense = [t for t in txs if "SUPERMARKET" in t.description][0]
        assert expense.amount == pytest.approx(-65.40)

    def test_income_positive(self):
        txs = CsvParser().parse(FIRST_DIRECT_CSV)
        salary = [t for t in txs if "SALARY" in t.description][0]
        assert salary.amount == pytest.approx(2000.00)


class TestNewdayJLCsv:
    def test_detects_format(self):
        txs = CsvParser().parse(NEWDAY_JL_CSV)
        assert len(txs) == 3

    def test_purchase_negated(self):
        txs = CsvParser().parse(NEWDAY_JL_CSV)
        costa = [t for t in txs if "Costa" in t.description][0]
        assert costa.amount == pytest.approx(-13.45)

    def test_refund_stays_positive(self):
        txs = CsvParser().parse(NEWDAY_JL_CSV)
        refund = [t for t in txs if "Refund" in t.description][0]
        assert refund.amount == pytest.approx(5.00)

    def test_description_is_clean_merchant_name(self):
        txs = CsvParser().parse(NEWDAY_JL_CSV)
        assert txs[0].description == "Costa Coffee"


class TestAnzCsv:
    def test_detects_format(self):
        txs = CsvParser().parse(ANZ_CSV)
        assert len(txs) == 2

    def test_amount_sign_preserved(self):
        txs = CsvParser().parse(ANZ_CSV)
        expense = [t for t in txs if "Woolworths" in t.description][0]
        assert expense.amount == pytest.approx(-65.40)


class TestNabCsv:
    def test_detects_format(self):
        txs = CsvParser().parse(NAB_CSV)
        assert len(txs) == 1

    def test_uses_merchant_name(self):
        txs = CsvParser().parse(NAB_CSV)
        assert "Woolworths" in txs[0].description


class TestWestpacCsv:
    def test_detects_format(self):
        txs = CsvParser().parse(WESTPAC_CSV)
        assert len(txs) == 2

    def test_debit_column_negated(self):
        txs = CsvParser().parse(WESTPAC_CSV)
        eftpos = [t for t in txs if "WOOLWORTHS" in t.description][0]
        assert eftpos.amount == pytest.approx(-65.40)


class TestGenericCsvFallback:
    GENERIC = "Txn Date,Details,Net Amount\n15/05/2026,Coffee Shop,-8.50\n"

    def test_parses_via_column_name_matching(self):
        txs = CsvParser().parse(self.GENERIC)
        assert len(txs) == 1
        assert txs[0].amount == pytest.approx(-8.50)

    def test_custom_column_map(self):
        csv = "When,What,How Much\n15/05/2026,Coffee,-8.50\n"
        txs = CsvParser(column_map={"date": "When", "description": "What", "amount": "How Much"}).parse(csv)
        assert txs[0].description == "Coffee"
        assert txs[0].amount == pytest.approx(-8.50)


# ── Amount parsing edge cases ─────────────────────────────────────────────────

class TestAmountParsing:
    def test_comma_thousands_separator(self):
        csv = "Date,Description,Amount,Balance\n01/01/2026,Rent,-1200.00,500.00\n"
        txs = CsvParser().parse(csv)
        assert txs[0].amount == pytest.approx(-1200.00)

    def test_currency_symbol_stripped(self):
        csv = "Date,Description,Amount,Balance\n01/01/2026,Coffee,£8.50,500.00\n"
        txs = CsvParser().parse(csv)
        assert txs[0].amount == pytest.approx(8.50)

    def test_parentheses_as_negative(self):
        csv = "Date,Description,Amount,Balance\n01/01/2026,Charge,(50.00),500.00\n"
        txs = CsvParser().parse(csv)
        assert txs[0].amount == pytest.approx(-50.00)


# ── OFX parser ────────────────────────────────────────────────────────────────

class TestOfxSgml:
    def test_parses_two_transactions(self):
        txs = OfxParser().parse(OFX_SGML)
        assert len(txs) == 2

    def test_debit_amount(self):
        txs = OfxParser().parse(OFX_SGML)
        debit = [t for t in txs if t.amount < 0][0]
        assert debit.amount == pytest.approx(-42.50)

    def test_credit_amount(self):
        txs = OfxParser().parse(OFX_SGML)
        credit = [t for t in txs if t.amount > 0][0]
        assert credit.amount == pytest.approx(2000.00)

    def test_date_parsed(self):
        txs = OfxParser().parse(OFX_SGML)
        assert txs[0].date == "2026-05-15"

    def test_description_from_memo_or_name(self):
        txs = OfxParser().parse(OFX_SGML)
        debit = [t for t in txs if t.amount < 0][0]
        assert "Coffee shop" in debit.description or "COSTA" in debit.description


class TestOfxXml:
    def test_parses_xml_variant(self):
        txs = OfxParser().parse(OFX_XML)
        assert len(txs) == 1
        assert txs[0].amount == pytest.approx(-42.50)
        assert txs[0].date == "2026-05-15"


# ── QIF parser ────────────────────────────────────────────────────────────────

class TestQifParser:
    def test_parses_two_records(self):
        txs = QifParser().parse(QIF_CONTENT)
        assert len(txs) == 2

    def test_expense_amount(self):
        txs = QifParser().parse(QIF_CONTENT)
        expense = [t for t in txs if t.amount < 0][0]
        assert expense.amount == pytest.approx(-42.50)

    def test_payee_as_description(self):
        txs = QifParser().parse(QIF_CONTENT)
        assert txs[0].description == "Costa Coffee"

    def test_date_format(self):
        txs = QifParser().parse(QIF_CONTENT)
        assert txs[0].date == "2026-05-15"


# ── parse_statement format auto-detection ────────────────────────────────────

class TestAutoDetection:
    def test_detects_ofx_by_extension(self):
        txs = parse_statement(OFX_SGML.encode(), "statement.ofx")
        assert len(txs) == 2

    def test_detects_ofx_by_content_sniff(self):
        txs = parse_statement(OFX_SGML.encode(), "statement.txt")
        assert len(txs) == 2

    def test_detects_qif_by_extension(self):
        txs = parse_statement(QIF_CONTENT.encode(), "statement.qif")
        assert len(txs) == 2

    def test_detects_qif_by_content_sniff(self):
        txs = parse_statement(QIF_CONTENT.encode(), "statement.txt")
        assert len(txs) == 2

    def test_csv_bytes_input(self):
        txs = parse_statement(FIRST_DIRECT_CSV.encode("utf-8"), "statement.csv")
        assert len(txs) == 2

    def test_bom_stripped(self):
        bom_csv = b"\xef\xbb\xbf" + FIRST_DIRECT_CSV.encode("utf-8")
        txs = parse_statement(bom_csv, "statement.csv")
        assert len(txs) == 2
