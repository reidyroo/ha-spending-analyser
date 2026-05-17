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
from .security import RateLimiter, validate_statement_content

if TYPE_CHECKING:
    from .database import SpendingDatabase
    from .ollama_client import OllamaClient


def _get_entry_data(hass: HomeAssistant) -> dict | None:
    domain_data = hass.data.get(DOMAIN, {})
    return next(
        (v for v in domain_data.values() if isinstance(v, dict) and "db" in v),
        None,
    )

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

        # ── Rate limiting: 10 uploads per IP per 10 minutes ────────
        limiter = RateLimiter.get(hass.data, "upload", max_calls=10, window_seconds=600)
        remote_ip = request.remote or "unknown"
        if not limiter.allow(remote_ip):
            return self.json({"error": "Too many requests — try again later"}, status_code=429)

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

        # ── Magic-byte / content validation ────────────────────────
        try:
            validate_statement_content(file_content, filename)
        except ValueError as exc:
            return self.json({"error": str(exc)}, status_code=415)

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


# ---------------------------------------------------------------------------
# Transaction list — GET /api/spending_analyser/transactions
# ---------------------------------------------------------------------------

class SpendingTransactionsApiView(HomeAssistantView):
    """Paginated transaction list with optional filters."""

    url = "/api/spending_analyser/transactions"
    name = "api:spending_analyser:transactions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"error": "Integration not loaded"}, status_code=503)
        db: SpendingDatabase = entry_data["db"]

        qs = request.rel_url.query
        category  = qs.get("category") or None
        date_from = qs.get("date_from") or None
        date_to   = qs.get("date_to") or None
        search    = qs.get("search") or None
        try:
            limit  = min(int(qs.get("limit", 100)), 500)
            offset = max(int(qs.get("offset", 0)), 0)
        except (ValueError, TypeError):
            limit, offset = 100, 0

        transactions = await db.async_get_transactions(
            category=category, date_from=date_from, date_to=date_to,
            search=search, limit=limit, offset=offset,
        )
        total = await db.async_count_transactions(
            category=category, date_from=date_from, date_to=date_to, search=search,
        )
        return self.json({"transactions": transactions, "total": total})


# ---------------------------------------------------------------------------
# Categories — GET /api/spending_analyser/categories
# ---------------------------------------------------------------------------

class SpendingCategoriesApiView(HomeAssistantView):
    url = "/api/spending_analyser/categories"
    name = "api:spending_analyser:categories"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"error": "Integration not loaded"}, status_code=503)
        db: SpendingDatabase = entry_data["db"]
        categories = await db.async_get_categories()
        return self.json({"categories": categories})


# ---------------------------------------------------------------------------
# HTTP recategorise — POST /api/spending_analyser/recategorise
# ---------------------------------------------------------------------------

class SpendingRecategoriseApiView(HomeAssistantView):
    """Update a transaction's category and learn the rule."""

    url = "/api/spending_analyser/recategorise"
    name = "api:spending_analyser:recategorise_http"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"error": "Integration not loaded"}, status_code=503)
        db: SpendingDatabase = entry_data["db"]

        try:
            body = await request.json()
        except Exception:
            return self.json({"error": "Invalid JSON body"}, status_code=400)

        tx_id    = body.get("transaction_id")
        category = str(body.get("category", "")).strip()
        if not isinstance(tx_id, int) or not category:
            return self.json(
                {"error": "transaction_id (int) and category (string) required"},
                status_code=400,
            )
        if len(category) > 60:
            return self.json({"error": "category too long (max 60 chars)"}, status_code=400)

        tx = await db.async_get_transaction(tx_id)
        if not tx:
            return self.json({"error": f"Transaction {tx_id} not found"}, status_code=404)

        await db.async_update_transaction_category(tx_id, category, user_verified=True)
        await db.async_upsert_category_rule(tx["description"], category)
        _LOGGER.info("HTTP recategorise: tx %d → '%s'", tx_id, category)
        return self.json({"success": True, "transaction_id": tx_id, "category": category})


# ---------------------------------------------------------------------------
# Ollama connectivity + categorisation test — POST /api/spending_analyser/ollama_test
# ---------------------------------------------------------------------------

class SpendingOllamaTestApiView(HomeAssistantView):
    """Test Ollama connectivity and/or categorise a single description."""

    url = "/api/spending_analyser/ollama_test"
    name = "api:spending_analyser:ollama_test"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"error": "Integration not loaded"}, status_code=503)

        db: SpendingDatabase  = entry_data["db"]
        ollama = entry_data["ollama"]

        try:
            body = await request.json()
        except Exception:
            body = {}

        description = str(body.get("description") or "").strip()[:200]
        start = time.monotonic()

        if not description:
            # Connection-only ping
            connected = await ollama.async_test_connection()
            latency_ms = int((time.monotonic() - start) * 1000)
            models: list[str] = []
            if connected:
                try:
                    models = await ollama.async_list_models()
                except Exception:
                    pass
            return self.json({
                "connected": connected,
                "latency_ms": latency_ms,
                "model": ollama._model,
                "models_available": models,
            })

        # Full categorisation test
        categories = await db.async_get_categories()
        category_names = [c["name"] for c in categories]
        learned_rules = await db.async_get_category_rules()

        category, confidence = await ollama.async_categorise(
            description, category_names, learned_rules
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        return self.json({
            "connected": True,
            "category": category,
            "confidence": round(confidence, 3),
            "latency_ms": latency_ms,
            "model": ollama._model,
        })
