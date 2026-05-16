"""HA Spending Analyser — local-first spending tracker with Edge AI categorisation."""
from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_OLLAMA_HOST, CONF_OLLAMA_MODEL, CONF_OLLAMA_PORT,
    DEFAULT_DB_NAME, DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_MODEL, DEFAULT_OLLAMA_PORT,
    DEFAULT_CATEGORIES, DOMAIN, PLATFORMS,
    SERVICE_ADD_TRANSACTION, SERVICE_IMPORT_STATEMENT, SERVICE_RECATEGORISE,
)
from .database import SpendingDatabase
from .ollama_client import OllamaClient
from .parsers import parse_statement

_LOGGER = logging.getLogger(__name__)

_SCHEMA_IMPORT = vol.Schema({
    vol.Required("file_path"): cv.string,
    vol.Optional("format"): vol.In(["csv", "ofx", "qif"]),
    vol.Optional("csv_date_column"): cv.string,
    vol.Optional("csv_description_column"): cv.string,
    vol.Optional("csv_amount_column"): cv.string,
    vol.Optional("categorise", default=True): cv.boolean,
})

_SCHEMA_ADD = vol.Schema({
    vol.Required("date"): cv.string,
    vol.Required("description"): cv.string,
    vol.Required("amount"): vol.Coerce(float),
    vol.Optional("category", default="Uncategorised"): cv.string,
    vol.Optional("account"): cv.string,
})

_SCHEMA_RECATEGORISE = vol.Schema({
    vol.Required("transaction_id"): vol.Coerce(int),
    vol.Required("category"): cv.string,
})


def _get_entry_data(hass: HomeAssistant) -> dict:
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if isinstance(entry_data, dict) and "db" in entry_data:
            return entry_data
    raise ServiceValidationError("Spending Analyser integration is not loaded")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Spending Analyser from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    db_path = entry.data.get(
        "db_path",
        os.path.join(hass.config.path("spending_analyser"), DEFAULT_DB_NAME),
    )
    db = await SpendingDatabase.async_init(db_path)

    ollama = OllamaClient(
        hass=hass,
        host=entry.data.get(CONF_OLLAMA_HOST, DEFAULT_OLLAMA_HOST),
        port=entry.data.get(CONF_OLLAMA_PORT, DEFAULT_OLLAMA_PORT),
        model=entry.data.get(CONF_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL),
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        "db": db,
        "ollama": ollama,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)

    _LOGGER.info("Spending Analyser loaded (entry: %s, db: %s)", entry.entry_id, db_path)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        await entry_data["db"].async_close()

    if not hass.data.get(DOMAIN):
        for svc in (SERVICE_IMPORT_STATEMENT, SERVICE_ADD_TRANSACTION, SERVICE_RECATEGORISE):
            hass.services.async_remove(DOMAIN, svc)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_STATEMENT):
        return

    async def handle_import(call: ServiceCall) -> None:
        file_path: str = call.data["file_path"]
        if not os.path.isfile(file_path):
            raise ServiceValidationError(f"File not found: {file_path}")

        column_map: dict[str, str] = {}
        if col := call.data.get("csv_date_column"):
            column_map["date"] = col
        if col := call.data.get("csv_description_column"):
            column_map["description"] = col
        if col := call.data.get("csv_amount_column"):
            column_map["amount"] = col

        with open(file_path, "rb") as fh:
            content = fh.read()

        transactions = await hass.async_add_executor_job(
            parse_statement, content, file_path, column_map or None
        )

        entry_data = _get_entry_data(hass)
        db: SpendingDatabase = entry_data["db"]
        ollama: OllamaClient = entry_data["ollama"]
        do_categorise: bool = call.data.get("categorise", True)

        categories = await db.async_get_categories()
        category_names = [c["name"] for c in categories] or DEFAULT_CATEGORIES
        learned_rules = await db.async_get_category_rules() if do_categorise else []

        added = skipped = 0
        for tx in transactions:
            category = tx.category if hasattr(tx, "category") and tx.category != "Uncategorised" else "Uncategorised"
            ai_confidence: float | None = None

            if do_categorise and category == "Uncategorised":
                category, ai_confidence = await ollama.async_categorise(
                    tx.description, category_names, learned_rules
                )

            _, is_dup = await db.async_add_transaction(
                date=tx.date,
                description=tx.description,
                amount=tx.amount,
                category=category,
                account=tx.account,
                ai_confidence=ai_confidence,
                raw_data=tx.raw,
            )
            if is_dup:
                skipped += 1
            else:
                added += 1

        _LOGGER.info("Import: %d added, %d skipped (%s)", added, skipped, file_path)
        hass.bus.async_fire(
            f"{DOMAIN}_import_complete",
            {"added": added, "skipped": skipped, "file": file_path},
        )

    async def handle_add(call: ServiceCall) -> None:
        entry_data = _get_entry_data(hass)
        db: SpendingDatabase = entry_data["db"]
        tx_id, is_dup = await db.async_add_transaction(
            date=call.data["date"],
            description=call.data["description"],
            amount=call.data["amount"],
            category=call.data.get("category", "Uncategorised"),
            account=call.data.get("account"),
        )
        if is_dup:
            _LOGGER.info("Transaction already exists (id=%d), skipped", tx_id)
        else:
            _LOGGER.info("Transaction added (id=%d)", tx_id)

    async def handle_recategorise(call: ServiceCall) -> None:
        entry_data = _get_entry_data(hass)
        db: SpendingDatabase = entry_data["db"]
        tx_id: int = call.data["transaction_id"]
        category: str = call.data["category"]
        tx = await db.async_get_transaction(tx_id)
        if not tx:
            raise ServiceValidationError(f"Transaction {tx_id} not found")
        await db.async_update_transaction_category(tx_id, category, user_verified=True)
        await db.async_upsert_category_rule(tx["description"], category)
        _LOGGER.info("Transaction %d recategorised to '%s'", tx_id, category)

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_STATEMENT, handle_import, schema=_SCHEMA_IMPORT)
    hass.services.async_register(DOMAIN, SERVICE_ADD_TRANSACTION, handle_add, schema=_SCHEMA_ADD)
    hass.services.async_register(DOMAIN, SERVICE_RECATEGORISE, handle_recategorise, schema=_SCHEMA_RECATEGORISE)
