"""HA Spending Analyser — local-first spending tracker with Edge AI categorisation."""
from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DEFAULT_DB_NAME, DOMAIN, PLATFORMS
from .database import SpendingDatabase

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Spending Analyser from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    db_path = entry.data.get(
        "db_path",
        os.path.join(hass.config.path("spending_analyser"), DEFAULT_DB_NAME),
    )
    db = await SpendingDatabase.async_init(db_path)

    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        "db": db,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Spending Analyser loaded (entry: %s, db: %s)", entry.entry_id, db_path)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        await entry_data["db"].async_close()
    return unload_ok
