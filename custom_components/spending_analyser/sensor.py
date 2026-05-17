"""HA sensor entities for spending metrics."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, SENSOR_UPDATE_INTERVAL
from .database import SpendingDatabase

_LOGGER = logging.getLogger(__name__)

_UPDATE_INTERVAL = timedelta(minutes=SENSOR_UPDATE_INTERVAL)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    db: SpendingDatabase = hass.data[DOMAIN][entry.entry_id]["db"]

    entities = [
        MonthlySpendingSensor(entry.entry_id, db),
        MonthlyIncomeSensor(entry.entry_id, db),
        MonthlyNetSensor(entry.entry_id, db),
        TopCategorySensor(entry.entry_id, db),
        UncategorisedCountSensor(entry.entry_id, db),
        TransactionCountSensor(entry.entry_id, db),
    ]
    async_add_entities(entities, update_before_add=True)

    # Schedule periodic refresh for all entities
    async def _refresh(_now: Any = None) -> None:
        for entity in entities:
            await entity.async_update()
            entity.async_write_ha_state()

    entry.async_on_unload(
        async_track_time_interval(hass, _refresh, _UPDATE_INTERVAL)
    )


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class _SpendingBaseSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "GBP"

    def __init__(self, entry_id: str, db: SpendingDatabase) -> None:
        self._db = db
        self._entry_id = entry_id
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_{self._sensor_key}"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Spending Analyser",
            "manufacturer": "HA Spending Analyser",
            "model": "Local AI",
        }

    @staticmethod
    def _current_month() -> tuple[str, str]:
        today = date.today()
        first = today.replace(day=1)
        # Last day: first day of next month minus one day
        if today.month == 12:
            last = today.replace(day=31)
        else:
            last = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        return first.isoformat(), last.isoformat()


# ---------------------------------------------------------------------------
# Monthly spending (expenses only — negative amounts, reported as positive £)
# ---------------------------------------------------------------------------

_EXCLUDE_FROM_SPENDING = {"Transfer", "Income"}


class MonthlySpendingSensor(_SpendingBaseSensor):
    _sensor_key = "monthly_spending"
    _attr_name = "Monthly Spending"
    _attr_icon = "mdi:cash-minus"

    async def async_update(self) -> None:
        date_from, date_to = self._current_month()
        rows = await self._db.async_get_spending_by_category(date_from, date_to)
        # Exclude credit card payments and internal transfers — they are reconciliation, not new spend
        rows = [r for r in rows if r["category"] not in _EXCLUDE_FROM_SPENDING]

        total = sum(abs(r["total"]) for r in rows)
        self._attr_native_value = round(total, 2)
        self._attr_extra_state_attributes = {
            "period_start": date_from,
            "period_end": date_to,
            "by_category": {
                r["category"]: round(abs(r["total"]), 2) for r in rows
            },
            "transaction_count": sum(r["count"] for r in rows),
        }


# ---------------------------------------------------------------------------
# Monthly income (positive amounts)
# ---------------------------------------------------------------------------

class MonthlyIncomeSensor(_SpendingBaseSensor):
    _sensor_key = "monthly_income"
    _attr_name = "Monthly Income"
    _attr_icon = "mdi:cash-plus"

    async def async_update(self) -> None:
        date_from, date_to = self._current_month()
        rows = await self._db.async_get_transactions(
            date_from=date_from, date_to=date_to, limit=5000
        )
        income_rows = [r for r in rows if r["amount"] > 0]
        total = sum(r["amount"] for r in income_rows)
        self._attr_native_value = round(total, 2)
        self._attr_extra_state_attributes = {
            "period_start": date_from,
            "period_end": date_to,
            "transaction_count": len(income_rows),
        }


# ---------------------------------------------------------------------------
# Monthly net (income − expenses)
# ---------------------------------------------------------------------------

class MonthlyNetSensor(_SpendingBaseSensor):
    _sensor_key = "monthly_net"
    _attr_name = "Monthly Net"
    _attr_icon = "mdi:bank-transfer"

    async def async_update(self) -> None:
        today = date.today()
        date_from, date_to = self._current_month()
        rows = await self._db.async_get_transactions(date_from=date_from, date_to=date_to, limit=5000)
        # Exclude Transfer so credit card payments don't double-count as expenditure
        total = sum(r["amount"] for r in rows if r["category"] not in _EXCLUDE_FROM_SPENDING)
        self._attr_native_value = round(total, 2)
        self._attr_extra_state_attributes = {
            "year": today.year,
            "month": today.month,
            "positive_means": "surplus",
        }


# ---------------------------------------------------------------------------
# Top spending category this month
# ---------------------------------------------------------------------------

class TopCategorySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Top Spending Category"
    _attr_icon = "mdi:podium-gold"
    _attr_state_class = None

    def __init__(self, entry_id: str, db: SpendingDatabase) -> None:
        self._db = db
        self._entry_id = entry_id
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_top_category"

    @property
    def device_info(self) -> dict:
        return {"identifiers": {(DOMAIN, self._entry_id)}}

    @staticmethod
    def _current_month() -> tuple[str, str]:
        today = date.today()
        first = today.replace(day=1)
        if today.month == 12:
            last = today.replace(day=31)
        else:
            last = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        return first.isoformat(), last.isoformat()

    async def async_update(self) -> None:
        date_from, date_to = self._current_month()
        rows = await self._db.async_get_spending_by_category(date_from, date_to)
        # Filter out Income/Transfer/Uncategorised for "top spend" purposes
        expense_rows = [
            r for r in rows
            if r["category"] not in ("Income", "Transfer", "Uncategorised")
        ]
        if expense_rows:
            top = max(expense_rows, key=lambda r: abs(r["total"]))
            self._attr_native_value = top["category"]
            self._attr_extra_state_attributes = {
                "amount": round(abs(top["total"]), 2),
                "transaction_count": top["count"],
                "period_start": date_from,
                "period_end": date_to,
            }
        else:
            self._attr_native_value = "None"
            self._attr_extra_state_attributes = {}


# ---------------------------------------------------------------------------
# Uncategorised transaction count (actionable — tells user AI needs help)
# ---------------------------------------------------------------------------

class UncategorisedCountSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Uncategorised Transactions"
    _attr_icon = "mdi:help-circle-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "transactions"

    def __init__(self, entry_id: str, db: SpendingDatabase) -> None:
        self._db = db
        self._entry_id = entry_id
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_uncategorised_count"

    @property
    def device_info(self) -> dict:
        return {"identifiers": {(DOMAIN, self._entry_id)}}

    async def async_update(self) -> None:
        rows = await self._db.async_get_transactions(category="Uncategorised", limit=500)
        self._attr_native_value = len(rows)
        # Surface the first 10 so the user can see what needs attention
        self._attr_extra_state_attributes = {
            "sample": [
                {"id": r["id"], "date": r["date"], "description": r["description"],
                 "amount": r["amount"]}
                for r in rows[:10]
            ]
        }


# ---------------------------------------------------------------------------
# Total transaction count (DB health check)
# ---------------------------------------------------------------------------

class TransactionCountSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Total Transactions"
    _attr_icon = "mdi:database"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "transactions"

    def __init__(self, entry_id: str, db: SpendingDatabase) -> None:
        self._db = db
        self._entry_id = entry_id

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_transaction_count"

    @property
    def device_info(self) -> dict:
        return {"identifiers": {(DOMAIN, self._entry_id)}}

    async def async_update(self) -> None:
        self._attr_native_value = await self._db.async_get_transaction_count()
