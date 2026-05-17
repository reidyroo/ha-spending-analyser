"""Authenticated HTTP views — upload API for the Spending Analyser panel."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DEFAULT_CATEGORIES, DOMAIN
from .parsers import parse_statement

if TYPE_CHECKING:
    from .database import SpendingDatabase
    from .ollama_client import OllamaClient

_LOGGER = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024          # 10 MB
_ALLOWED_EXTENSIONS = {".csv", ".ofx", ".qfx", ".qif"}
_SAFE_FILENAME = re.compile(r"[^a-zA-Z0-9_\-.]")


def _safe_name(name: str) -> str:
    """Sanitise an uploaded filename to prevent path traversal."""
    base = os.path.basename(name)
    return _SAFE_FILENAME.sub("_", base)[:120]


class SpendingUploadApiView(HomeAssistantView):
    """POST /api/spending_analyser/upload — accepts a statement file and imports it."""

    url = "/api/spending_analyser/upload"
    name = "api:spending_analyser:upload"
    requires_auth = True   # HA enforces a valid bearer token

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]

        # ── Retrieve DB / Ollama from domain data ──────────────────
        domain_data = hass.data.get(DOMAIN, {})
        entry_data = next(
            (v for v in domain_data.values() if isinstance(v, dict) and "db" in v),
            None,
        )
        if entry_data is None:
            return self.json({"error": "Integration not loaded"}, status_code=503)

        db: SpendingDatabase = entry_data["db"]
        ollama: OllamaClient = entry_data["ollama"]

        # ── Parse multipart form ───────────────────────────────────
        try:
            reader = await request.multipart()
        except Exception:
            return self.json({"error": "Expected multipart/form-data"}, status_code=400)

        file_content: bytes | None = None
        filename: str = "upload.csv"
        do_categorise: bool = True

        async for part in reader:
            if part.name == "file":
                filename = _safe_name(part.filename or "upload.csv")
                chunks = []
                total = 0
                async for chunk in part:
                    total += len(chunk)
                    if total > _MAX_UPLOAD_BYTES:
                        return self.json({"error": "File exceeds 10 MB limit"}, status_code=413)
                    chunks.append(chunk)
                file_content = b"".join(chunks)
            elif part.name == "categorise":
                val = (await part.read(decode=True)).decode().strip().lower()
                do_categorise = val not in ("false", "0", "no")

        if not file_content:
            return self.json({"error": "No file received"}, status_code=400)

        ext = os.path.splitext(filename)[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            return self.json(
                {"error": f"Unsupported format '{ext}'. Allowed: csv, ofx, qfx, qif"},
                status_code=415,
            )

        # ── Save to uploads dir (kept for audit trail) ─────────────
        uploads_dir = hass.config.path("spending_analyser", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        ts = int(time.time())
        save_path = os.path.join(uploads_dir, f"{ts}_{filename}")
        try:
            with open(save_path, "wb") as fh:
                fh.write(file_content)
        except OSError as exc:
            _LOGGER.error("Could not save upload: %s", exc)
            return self.json({"error": "Failed to save file"}, status_code=500)

        # ── Parse ──────────────────────────────────────────────────
        try:
            transactions = await hass.async_add_executor_job(
                parse_statement, file_content, filename, None
            )
        except Exception as exc:
            _LOGGER.exception("Parse error for %s", filename)
            return self.json({"error": f"Parse failed: {exc}"}, status_code=422)

        if not transactions:
            return self.json(
                {"added": 0, "skipped": 0, "warning": "No transactions found in file"},
                status_code=200,
            )

        # ── Categorise + insert ────────────────────────────────────
        categories = await db.async_get_categories()
        category_names = [c["name"] for c in categories] or DEFAULT_CATEGORIES
        learned_rules = await db.async_get_category_rules() if do_categorise else []

        added = skipped = 0
        for tx in transactions:
            category = "Uncategorised"
            ai_confidence = None

            if do_categorise:
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

        _LOGGER.info(
            "Upload import '%s': %d added, %d skipped", filename, added, skipped
        )
        hass.bus.async_fire(
            f"{DOMAIN}_import_complete",
            {"added": added, "skipped": skipped, "file": filename, "source": "upload"},
        )
        return self.json({"added": added, "skipped": skipped, "filename": filename})
