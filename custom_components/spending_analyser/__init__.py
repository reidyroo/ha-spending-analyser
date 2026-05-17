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
    SERVICE_ADD_TRANSACTION, SERVICE_GENERATE_REPORT, SERVICE_IMPORT_STATEMENT, SERVICE_RECATEGORISE,
)
from .database import SpendingDatabase
from .http_views import SpendingUploadApiView
from .ollama_client import OllamaClient
from .parsers import parse_statement
from .report_generator import ReportGenerator, REPORT_PROMPTS
from .security import sanitize_prompt_input, validate_statement_content

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

_SCHEMA_REPORT = vol.Schema({
    vol.Required("prompt"):              vol.In(list(REPORT_PROMPTS)),
    vol.Optional("category"):            cv.string,
    vol.Optional("year"):                vol.Coerce(int),
    vol.Optional("month"):               vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
    vol.Optional("months_back", default=12): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
    vol.Optional("currency", default="£"): cv.string,
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
    _register_panel(hass)

    _LOGGER.info("Spending Analyser loaded (entry: %s, db: %s)", entry.entry_id, db_path)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        await entry_data["db"].async_close()

    if not hass.data.get(DOMAIN):
        for svc in (SERVICE_IMPORT_STATEMENT, SERVICE_ADD_TRANSACTION, SERVICE_RECATEGORISE, SERVICE_GENERATE_REPORT):
            hass.services.async_remove(DOMAIN, svc)
        hass.data.pop(f"{DOMAIN}_panel_registered", None)

    return unload_ok


def _register_panel(hass: HomeAssistant) -> None:
    """Register the upload UI as a sidebar panel and the API view (idempotent)."""
    # HTTP view — safe to register multiple times; HA deduplicates by name
    hass.http.register_view(SpendingUploadApiView())

    # Sidebar iframe panel — skip if already registered
    from homeassistant.components import frontend
    if not hass.data.get(f"{DOMAIN}_panel_registered"):
        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title="Import Statement",
            sidebar_icon="mdi:file-upload-outline",
            frontend_url_path="spending-upload",
            config={"url": "/local/spending_analyser/upload.html"},
            require_admin=False,
        )
        hass.data[f"{DOMAIN}_panel_registered"] = True


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_STATEMENT):
        return

    async def handle_import(call: ServiceCall) -> None:
        file_path: str = call.data["file_path"]
        # Contain the path to HA config dir to prevent reading arbitrary host files
        config_dir = hass.config.config_dir
        try:
            import os as _os
            resolved = _os.path.realpath(_os.path.abspath(file_path))
            if not resolved.startswith(_os.path.realpath(config_dir)):
                raise ServiceValidationError(
                    f"File path must be within the HA config directory ({config_dir})"
                )
        except ServiceValidationError:
            raise
        except Exception as exc:
            raise ServiceValidationError(f"Invalid file path: {exc}") from exc

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

        try:
            validate_statement_content(content, file_path)
        except ValueError as exc:
            raise ServiceValidationError(str(exc)) from exc

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
            description=sanitize_prompt_input(call.data["description"], max_len=200),
            amount=call.data["amount"],
            category=sanitize_prompt_input(call.data.get("category", "Uncategorised"), max_len=60),
            account=call.data.get("account", "")[:30] or None,
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

    async def handle_generate_report(call: ServiceCall) -> None:
        entry_data = _get_entry_data(hass)
        db: SpendingDatabase = entry_data["db"]
        ollama: OllamaClient = entry_data["ollama"]

        reports_dir = hass.config.path("spending_analyser", "reports")
        generator = ReportGenerator(
            db=db,
            ollama=ollama,
            currency=call.data.get("currency", "£"),
            reports_dir=reports_dir,
        )
        try:
            result = await generator.async_generate(
                prompt_key=call.data["prompt"],
                category=call.data.get("category"),
                year=call.data.get("year"),
                month=call.data.get("month"),
                months_back=call.data.get("months_back", 12),
            )
        except Exception as exc:
            _LOGGER.error("Report generation failed: %s", exc)
            raise ServiceValidationError(str(exc)) from exc

        # Surface as a HA persistent notification so it's visible immediately
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": result["title"],
                "message": result["text"],
                "notification_id": f"{DOMAIN}_report",
            },
        )

        # Fire event so automations can email / push the report
        hass.bus.async_fire(
            f"{DOMAIN}_report_ready",
            {
                "title":     result["title"],
                "prompt":    result["prompt"],
                "file_path": result.get("file_path"),
                "text":      result["text"][:500],   # truncated for event bus
            },
        )
        _LOGGER.info("Report '%s' complete. File: %s", result["title"], result.get("file_path"))

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_STATEMENT, handle_import, schema=_SCHEMA_IMPORT)
    hass.services.async_register(DOMAIN, SERVICE_ADD_TRANSACTION, handle_add, schema=_SCHEMA_ADD)
    hass.services.async_register(DOMAIN, SERVICE_RECATEGORISE, handle_recategorise, schema=_SCHEMA_RECATEGORISE)
    hass.services.async_register(DOMAIN, SERVICE_GENERATE_REPORT, handle_generate_report, schema=_SCHEMA_REPORT)
