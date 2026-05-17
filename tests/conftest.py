"""Shared pytest fixtures — stubs HA modules so tests run without a full HA install."""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Stub homeassistant and aiohttp before any project code is imported.
# This lets the parsers, database, and security modules load cleanly.
# ---------------------------------------------------------------------------

def _make_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    return mod


def _stub_ha() -> None:
    """Insert lightweight stubs for every homeassistant.* we import."""
    # Base
    ha = _make_module("homeassistant")
    sys.modules.setdefault("homeassistant", ha)

    # config_entries
    class ConfigEntry:
        def __init__(self): self.entry_id = "test"; self.data = {}
        def async_on_unload(self, _): pass
    ce_mod = _make_module("homeassistant.config_entries", ConfigEntry=ConfigEntry)
    sys.modules.setdefault("homeassistant.config_entries", ce_mod)

    # core
    class HomeAssistant:
        def __init__(self): self.data = {}; self.config = MagicMock()
        async def async_add_executor_job(self, fn, *args): return fn(*args)
    class ServiceCall:
        def __init__(self, data=None): self.data = data or {}
    core_mod = _make_module("homeassistant.core", HomeAssistant=HomeAssistant, ServiceCall=ServiceCall)
    sys.modules.setdefault("homeassistant.core", core_mod)

    # exceptions
    class ServiceValidationError(Exception): pass
    exc_mod = _make_module("homeassistant.exceptions", ServiceValidationError=ServiceValidationError)
    sys.modules.setdefault("homeassistant.exceptions", exc_mod)

    # helpers (parent)
    helpers = _make_module("homeassistant.helpers")
    sys.modules.setdefault("homeassistant.helpers", helpers)

    # helpers.config_validation
    cv = _make_module("homeassistant.helpers.config_validation",
                      string=str, boolean=bool)
    sys.modules.setdefault("homeassistant.helpers.config_validation", cv)

    # helpers.aiohttp_client
    ahc = _make_module("homeassistant.helpers.aiohttp_client",
                       async_get_clientsession=MagicMock())
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", ahc)

    # helpers.entity_platform
    ep = _make_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=MagicMock)
    sys.modules.setdefault("homeassistant.helpers.entity_platform", ep)

    # helpers.event
    ev = _make_module("homeassistant.helpers.event", async_track_time_interval=MagicMock())
    sys.modules.setdefault("homeassistant.helpers.event", ev)

    # components (parent)
    comp = _make_module("homeassistant.components")
    sys.modules.setdefault("homeassistant.components", comp)

    # components.http
    class HomeAssistantView:
        requires_auth = True
        def json(self, data, status_code=200): return MagicMock()
    http_mod = _make_module("homeassistant.components.http", HomeAssistantView=HomeAssistantView)
    sys.modules.setdefault("homeassistant.components.http", http_mod)

    # components.sensor
    class SensorEntity:
        _attr_native_value = None
        _attr_extra_state_attributes = {}
        def async_write_ha_state(self): pass
    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"
    sensor_mod = _make_module("homeassistant.components.sensor",
                              SensorEntity=SensorEntity, SensorStateClass=SensorStateClass)
    sys.modules.setdefault("homeassistant.components.sensor", sensor_mod)

    # aiohttp (only the web sub-module is used directly)
    if "aiohttp" not in sys.modules:
        aiohttp_mod = _make_module("aiohttp", web=MagicMock(), ClientSession=MagicMock,
                                   ClientTimeout=MagicMock)
        sys.modules["aiohttp"] = aiohttp_mod
        sys.modules["aiohttp.web"] = _make_module("aiohttp.web", Request=MagicMock,
                                                   Response=MagicMock)


_stub_ha()

# Make custom_components importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db(tmp_path):
    from custom_components.spending_analyser.database import SpendingDatabase
    instance = await SpendingDatabase.async_init(str(tmp_path / "test.db"))
    yield instance
    await instance.async_close()


# ── Sample statement strings ──────────────────────────────────────────────────

MIDATA_CSV = (
    "Transaction Date,Transaction Type,Sort Code,Account Number,"
    "Transaction Description,Debit Amount,Credit Amount,Balance\n"
    "15/05/2026,DEB,00-00-00,12345678,COSTA COFFEE READING,13.45,,1234.56\n"
    "14/05/2026,DEB,00-00-00,12345678,AMAZON.CO.UK,42.99,,1248.01\n"
    "01/05/2026,CR,00-00-00,12345678,SALARY,,2000.00,\n"
)

FIRST_DIRECT_CSV = (
    "Date,Description,Amount,Balance\n"
    "13/05/2026,SUPERMARKET,-65.40,1234.56\n"
    "12/05/2026,SALARY,2000.00,1300.00\n"
)

NEWDAY_JL_CSV = (
    "Date,Description,Note,Amount(GBP)\n"
    "15/05/2026,Costa Coffee,COSTA COFFEE 43011071 READING GBR,13.45\n"
    "14/05/2026,Amazon,AMAZON.CO.UK PAYMENTS LONDON GBR,42.99\n"
    "10/05/2026,Refund,AMAZON REFUND,-5.00\n"
)

ANZ_CSV = (
    "Date,Amount,Description\n"
    "15/05/2026,-65.40,Woolworths\n"
    "14/05/2026,2000.00,Salary\n"
)

NAB_CSV = (
    "Date,Amount,Account Number,Description,Merchant Name,Merchant City,"
    "Merchant State,BSB Number,Transaction Type,Currency Amount,Currency Rate,"
    "Original Currency,Conversion Charge\n"
    "15/05/2026,-65.40,123-456 7890123,Supermarket,Woolworths,Sydney,NSW,"
    ",,,,\n"
)

WESTPAC_CSV = (
    "BSB,Account Number,Transaction Date,Narration,Cheque Number,Debit,Credit,Balance,Transaction Type\n"
    "032-001,123456,15/05/2026,EFTPOS WOOLWORTHS,,65.40,,1234.56,EFTPOS\n"
    "032-001,123456,01/05/2026,SALARY,,,,1300.00,CREDIT\n"
)

OFX_SGML = (
    "OFXHEADER:100\nDATA:OFXSGML\n\n"
    "<OFX>\n"
    "<STMTTRN>\n<TRNTYPE>DEBIT\n<DTPOSTED>20260515120000\n"
    "<TRNAMT>-42.50\n<FITID>TXN001\n<NAME>COSTA COFFEE\n<MEMO>Coffee shop\n"
    "</STMTTRN>\n"
    "<STMTTRN>\n<TRNTYPE>CREDIT\n<DTPOSTED>20260501\n"
    "<TRNAMT>2000.00\n<FITID>TXN002\n<NAME>SALARY\n"
    "</STMTTRN>\n"
    "</OFX>\n"
)

OFX_XML = (
    '<?xml version="1.0"?>\n'
    "<OFX><STMTTRNRS><STMTRS><BANKTRANLIST>\n"
    "<STMTTRN><TRNTYPE>DEBIT</TRNTYPE>"
    "<DTPOSTED>20260515</DTPOSTED>"
    "<TRNAMT>-42.50</TRNAMT>"
    "<FITID>X1</FITID>"
    "<NAME>COSTA COFFEE</NAME></STMTTRN>\n"
    "</BANKTRANLIST></STMTRS></STMTTRNRS></OFX>\n"
)

QIF_CONTENT = (
    "!Type:Bank\n"
    "D15/05/2026\nT-42.50\nPCosta Coffee\n^\n"
    "D01/05/2026\nT2000.00\nPSalary\n^\n"
)
