"""Async Ollama REST client for transaction categorisation."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 5
_CATEGORISE_TIMEOUT = 30

_SYSTEM_PROMPT = """\
You are a bank transaction categoriser. You will be given a transaction description \
and must assign it to exactly one category from the list below.

Rules:
- Respond with ONLY a JSON object — no explanation, no markdown.
- Format: {{"category": "<name>", "confidence": <0.0-1.0>}}
- confidence reflects how certain you are (1.0 = certain).
- If the transaction is unclear, use "Uncategorised" with low confidence.

Categories:
{categories}
"""

_USER_TEMPLATE = "Transaction: {description}"

_EXAMPLE_TEMPLATE = (
    '{{"category": "{category}", "confidence": 1.0}}'
)


class OllamaClient:
    """Async client for the Ollama local inference API."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, model: str) -> None:
        self._hass = hass
        self._base = f"http://{host}:{port}"
        self._model = model

    # ------------------------------------------------------------------
    # Connection / discovery
    # ------------------------------------------------------------------

    async def async_test_connection(self) -> bool:
        """Return True if Ollama is reachable and the chosen model is available."""
        try:
            models = await self.async_list_models()
            if not models:
                _LOGGER.warning("Ollama reachable but no models found at %s", self._base)
                return True  # server is up; model may need pulling
            if self._model not in models:
                _LOGGER.warning(
                    "Model '%s' not found on Ollama server. Available: %s",
                    self._model, models,
                )
            return True
        except Exception as exc:
            _LOGGER.debug("Ollama connection test failed: %s", exc)
            return False

    async def async_list_models(self) -> list[str]:
        """Return the names of models available on the Ollama server."""
        data = await self._get("/api/tags")
        return [m["name"] for m in data.get("models", [])]

    # ------------------------------------------------------------------
    # Categorisation
    # ------------------------------------------------------------------

    async def async_categorise(
        self,
        description: str,
        categories: list[str],
        learned_rules: list[dict[str, Any]] | None = None,
    ) -> tuple[str, float]:
        """Categorise a transaction description.

        Returns (category, confidence). Falls back to ('Uncategorised', 0.0) on
        any error so the import pipeline is never blocked by AI failures.
        """
        # Fast-path: check learned rules before hitting the model
        if learned_rules:
            rule_match = _match_rule(description, learned_rules)
            if rule_match:
                _LOGGER.debug("Rule match for '%s' → '%s'", description, rule_match)
                return rule_match, 1.0

        messages = _build_messages(description, categories, learned_rules)

        try:
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0, "num_predict": 60},
            }
            data = await self._post("/api/chat", payload, timeout=_CATEGORISE_TIMEOUT)
            raw = data.get("message", {}).get("content", "")
            return _parse_response(raw, categories)
        except Exception as exc:
            _LOGGER.warning("Ollama categorisation failed for '%s': %s", description, exc)
            return "Uncategorised", 0.0

    async def async_categorise_batch(
        self,
        descriptions: list[str],
        categories: list[str],
        learned_rules: list[dict[str, Any]] | None = None,
    ) -> list[tuple[str, float]]:
        """Categorise multiple descriptions sequentially (Ollama has no batch API)."""
        results = []
        for desc in descriptions:
            cat, conf = await self.async_categorise(desc, categories, learned_rules)
            results.append((cat, conf))
        return results

    # ------------------------------------------------------------------
    # Long-form report generation
    # ------------------------------------------------------------------

    async def async_generate_report(
        self,
        system_prompt: str,
        user_message: str,
        timeout: int = 120,
    ) -> str:
        """Generate a free-text narrative report.

        Uses higher temperature and token budget than categorisation.
        Returns the model's text response, or raises on failure.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 1024,
                "top_p": 0.9,
            },
        }
        data = await self._post("/api/chat", payload, timeout=timeout)
        return data.get("message", {}).get("content", "").strip()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, payload: dict, timeout: int = 10) -> dict:
        session = async_get_clientsession(self._hass)
        async with session.post(
            self._base + path,
            json=payload,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _get(self, path: str) -> dict:
        session = async_get_clientsession(self._hass)
        async with session.get(
            self._base + path,
            timeout=_CONNECT_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)


# ------------------------------------------------------------------
# Prompt helpers
# ------------------------------------------------------------------

def _build_messages(
    description: str,
    categories: list[str],
    learned_rules: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    system = _SYSTEM_PROMPT.format(categories="\n".join(f"- {c}" for c in categories))
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    # Inject up to 6 high-confidence learned rules as few-shot examples
    if learned_rules:
        examples = sorted(learned_rules, key=lambda r: r.get("match_count", 0), reverse=True)[:6]
        for rule in examples:
            messages.append({"role": "user", "content": _USER_TEMPLATE.format(description=rule["pattern"])})
            messages.append({"role": "assistant", "content": _EXAMPLE_TEMPLATE.format(category=rule["category"])})

    messages.append({"role": "user", "content": _USER_TEMPLATE.format(description=description)})
    return messages


def _parse_response(raw: str, valid_categories: list[str]) -> tuple[str, float]:
    """Extract category and confidence from the model's JSON response."""
    raw = raw.strip()
    # Strip markdown code fences if the model ignores format:json
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        obj = json.loads(raw)
        category = obj.get("category", "Uncategorised").strip()
        confidence = float(obj.get("confidence", 0.5))
        if category not in valid_categories:
            # Try case-insensitive match
            lower_map = {c.lower(): c for c in valid_categories}
            category = lower_map.get(category.lower(), "Uncategorised")
        return category, max(0.0, min(1.0, confidence))
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        _LOGGER.debug("Could not parse Ollama response %r: %s", raw, exc)
        return "Uncategorised", 0.0


def _match_rule(description: str, rules: list[dict[str, Any]]) -> str | None:
    """Return a category if a learned rule pattern is a substring of the description."""
    desc_lower = description.lower()
    for rule in sorted(rules, key=lambda r: len(r.get("pattern", "")), reverse=True):
        pattern = rule.get("pattern", "").lower()
        if pattern and pattern in desc_lower:
            return rule["category"]
    return None
