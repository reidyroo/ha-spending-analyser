"""SQLite database layer for HA Spending Analyser."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any

import aiosqlite

from .const import DEFAULT_CATEGORIES

_LOGGER = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    amount        REAL    NOT NULL,
    category      TEXT    NOT NULL DEFAULT 'Uncategorised',
    account       TEXT,
    import_hash   TEXT    UNIQUE NOT NULL,
    ai_confidence REAL,
    user_verified INTEGER NOT NULL DEFAULT 0,
    raw_data      TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    UNIQUE NOT NULL,
    colour         TEXT,
    budget_monthly REAL
);

CREATE TABLE IF NOT EXISTS category_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT    UNIQUE NOT NULL,
    category    TEXT    NOT NULL,
    match_count INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_date     ON transactions (date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions (category);
CREATE INDEX IF NOT EXISTS idx_transactions_hash     ON transactions (import_hash);
"""


def _make_hash(date: str, description: str, amount: float) -> str:
    raw = f"{date}|{description}|{amount:.4f}"
    return hashlib.sha256(raw.encode()).hexdigest()


class SpendingDatabase:
    """Async SQLite database for spending transactions."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def async_init(cls, db_path: str) -> "SpendingDatabase":
        """Open (or create) the database and apply the schema."""
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        await db.executescript(_SCHEMA)
        await db.commit()
        instance = cls(db)
        await instance._seed_categories()
        _LOGGER.debug("Database ready at %s", db_path)
        return instance

    async def async_close(self) -> None:
        await self._db.close()

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    async def _seed_categories(self) -> None:
        for name in DEFAULT_CATEGORIES:
            await self._db.execute(
                "INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,)
            )
        await self._db.commit()

    async def async_get_categories(self) -> list[dict[str, Any]]:
        async with self._db.execute(
            "SELECT id, name, colour, budget_monthly FROM categories ORDER BY name"
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def async_add_category(
        self, name: str, colour: str | None = None, budget_monthly: float | None = None
    ) -> int:
        cur = await self._db.execute(
            "INSERT OR IGNORE INTO categories (name, colour, budget_monthly) VALUES (?, ?, ?)",
            (name, colour, budget_monthly),
        )
        await self._db.commit()
        return cur.lastrowid or 0

    async def async_update_category(
        self, name: str, colour: str | None = None, budget_monthly: float | None = None
    ) -> None:
        await self._db.execute(
            "UPDATE categories SET colour=?, budget_monthly=? WHERE name=?",
            (colour, budget_monthly, name),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    async def async_add_transaction(
        self,
        date: str,
        description: str,
        amount: float,
        category: str = "Uncategorised",
        account: str | None = None,
        ai_confidence: float | None = None,
        raw_data: dict | None = None,
    ) -> tuple[int, bool]:
        # Hard caps — prevent unbounded data reaching the DB
        description = description[:255]
        category    = category[:60]
        if account:
            account = account[:30]
        """Insert a transaction. Returns (row_id, is_duplicate)."""
        import_hash = _make_hash(date, description, amount)
        try:
            cur = await self._db.execute(
                """INSERT INTO transactions
                   (date, description, amount, category, account,
                    import_hash, ai_confidence, raw_data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date,
                    description,
                    amount,
                    category,
                    account,
                    import_hash,
                    ai_confidence,
                    json.dumps(raw_data) if raw_data else None,
                    datetime.utcnow().isoformat(),
                ),
            )
            await self._db.commit()
            return cur.lastrowid, False
        except aiosqlite.IntegrityError:
            async with self._db.execute(
                "SELECT id FROM transactions WHERE import_hash=?", (import_hash,)
            ) as cur:
                row = await cur.fetchone()
                return (row["id"] if row else 0), True

    async def async_get_transactions(
        self,
        category: str | None = None,
        account: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if account:
            clauses.append("account = ?")
            params.append(account)
        if date_from:
            clauses.append("date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("date <= ?")
            params.append(date_to)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]
        async with self._db.execute(
            f"SELECT * FROM transactions {where} ORDER BY date DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def async_get_transaction(self, tx_id: int) -> dict[str, Any] | None:
        async with self._db.execute(
            "SELECT * FROM transactions WHERE id=?", (tx_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def async_update_transaction_category(
        self, tx_id: int, category: str, user_verified: bool = True
    ) -> bool:
        cur = await self._db.execute(
            "UPDATE transactions SET category=?, user_verified=? WHERE id=?",
            (category, int(user_verified), tx_id),
        )
        await self._db.commit()
        return cur.rowcount > 0

    async def async_delete_transaction(self, tx_id: int) -> bool:
        cur = await self._db.execute(
            "DELETE FROM transactions WHERE id=?", (tx_id,)
        )
        await self._db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Aggregates (used by sensors)
    # ------------------------------------------------------------------

    async def async_get_spending_by_category(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """Return total spending per category for the given date range (expenses only)."""
        async with self._db.execute(
            """SELECT category, SUM(amount) AS total, COUNT(*) AS count
               FROM transactions
               WHERE date >= ? AND date <= ? AND amount < 0
               GROUP BY category
               ORDER BY total ASC""",
            (date_from, date_to),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def async_get_monthly_total(self, year: int, month: int) -> float:
        """Return net total (income − expenses) for the given month."""
        date_from = f"{year:04d}-{month:02d}-01"
        date_to = f"{year:04d}-{month:02d}-31"
        async with self._db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions WHERE date >= ? AND date <= ?",
            (date_from, date_to),
        ) as cur:
            row = await cur.fetchone()
            return float(row["total"]) if row else 0.0

    async def async_get_transaction_count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) AS n FROM transactions") as cur:
            row = await cur.fetchone()
            return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    # Category rules (AI learning)
    # ------------------------------------------------------------------

    async def async_get_category_rules(self) -> list[dict[str, Any]]:
        async with self._db.execute(
            "SELECT pattern, category, match_count FROM category_rules ORDER BY match_count DESC"
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def async_upsert_category_rule(self, pattern: str, category: str) -> None:
        """Insert or increment a category rule learned from user corrections."""
        await self._db.execute(
            """INSERT INTO category_rules (pattern, category, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(pattern) DO UPDATE SET
                   category    = excluded.category,
                   match_count = match_count + 1""",
            (pattern, category, datetime.utcnow().isoformat()),
        )
        await self._db.commit()

    async def async_delete_category_rule(self, pattern: str) -> bool:
        cur = await self._db.execute(
            "DELETE FROM category_rules WHERE pattern=?", (pattern,)
        )
        await self._db.commit()
        return cur.rowcount > 0
