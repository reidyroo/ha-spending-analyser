"""Config flow for HA Spending Analyser."""
from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import (
    CONF_OLLAMA_HOST,
    CONF_OLLAMA_MODEL,
    CONF_OLLAMA_PORT,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_PORT,
    DOMAIN,
)
from .security import validate_ollama_host, validate_port, validate_model_name

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OLLAMA_HOST, default=DEFAULT_OLLAMA_HOST): str,
        vol.Required(CONF_OLLAMA_PORT, default=DEFAULT_OLLAMA_PORT): int,
        vol.Required(CONF_OLLAMA_MODEL, default=DEFAULT_OLLAMA_MODEL): str,
    }
)


async def _test_ollama_connection(host: str, port: int) -> bool:
    """Attempt a lightweight ping to the Ollama API."""
    url = f"http://{host}:{port}/api/tags"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
    except Exception:
        return False


class SpendingAnalyserConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            # ── Validate inputs before hitting the network ─────────
            try:
                host  = validate_ollama_host(user_input[CONF_OLLAMA_HOST])
                port  = validate_port(user_input[CONF_OLLAMA_PORT])
                model = validate_model_name(user_input[CONF_OLLAMA_MODEL])
            except ValueError as exc:
                errors["base"] = "invalid_input"
                # Surface the specific message in the description_placeholders
                return self.async_show_form(
                    step_id="user",
                    data_schema=DATA_SCHEMA,
                    errors=errors,
                    description_placeholders={"error_detail": str(exc)},
                )

            reachable = await _test_ollama_connection(host, port)
            if not reachable:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Spending Analyser",
                    data={
                        CONF_OLLAMA_HOST:  host,
                        CONF_OLLAMA_PORT:  port,
                        CONF_OLLAMA_MODEL: model,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )
