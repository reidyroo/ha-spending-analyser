"""Tests for the SQLite database layer."""
import pytest
import pytest_asyncio
from datetime import date


# ── Helpers ───────────────────────────────────────────────────────────────────

async def add(db, desc="Coffee", amount=-5.00, dt=None, category="Uncategorised", account=None):
    dt = dt or date.today().isoformat()
    return await db.async_add_transaction(
        date=dt, description=desc, amount=amount, category=category, account=account
    )


# ── Init / schema ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tables_created(db):
    count = await db.async_get_transaction_count()
    assert count == 0


@pytest.mark.asyncio
async def test_default_categories_seeded(db):
    cats = await db.async_get_categories()
    names = [c["name"] for c in cats]
    assert "Groceries" in names
    assert "Uncategorised" in names


# ── Add / deduplication ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_returns_id_and_not_dup(db):
    tx_id, is_dup = await add(db)
    assert tx_id > 0
    assert is_dup is False


@pytest.mark.asyncio
async def test_duplicate_detected(db):
    await add(db, desc="Coffee", amount=-5.00, dt="2026-05-15")
    tx_id2, is_dup = await add(db, desc="Coffee", amount=-5.00, dt="2026-05-15")
    assert is_dup is True


@pytest.mark.asyncio
async def test_same_desc_different_amount_not_dup(db):
    await add(db, desc="Coffee", amount=-5.00, dt="2026-05-15")
    _, is_dup = await add(db, desc="Coffee", amount=-6.00, dt="2026-05-15")
    assert is_dup is False


@pytest.mark.asyncio
async def test_count_increments(db):
    await add(db, desc="A", amount=-1.00, dt="2026-05-01")
    await add(db, desc="B", amount=-2.00, dt="2026-05-02")
    assert await db.async_get_transaction_count() == 2


# ── Get / filter ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_transaction_by_id(db):
    tx_id, _ = await add(db, desc="Unique desc", amount=-99.99)
    tx = await db.async_get_transaction(tx_id)
    assert tx["description"] == "Unique desc"
    assert tx["amount"] == pytest.approx(-99.99)


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(db):
    assert await db.async_get_transaction(999999) is None


@pytest.mark.asyncio
async def test_filter_by_category(db):
    await add(db, desc="Supermarket", amount=-50.00, category="Groceries")
    await add(db, desc="Netflix", amount=-10.00, category="Subscriptions")
    rows = await db.async_get_transactions(category="Groceries")
    assert all(r["category"] == "Groceries" for r in rows)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_filter_by_date_range(db):
    await add(db, desc="Old",     amount=-1.00, dt="2026-01-01")
    await add(db, desc="Current", amount=-2.00, dt="2026-05-15")
    rows = await db.async_get_transactions(date_from="2026-05-01", date_to="2026-05-31")
    assert len(rows) == 1
    assert rows[0]["description"] == "Current"


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_category(db):
    tx_id, _ = await add(db)
    ok = await db.async_update_transaction_category(tx_id, "Groceries")
    assert ok is True
    tx = await db.async_get_transaction(tx_id)
    assert tx["category"] == "Groceries"
    assert tx["user_verified"] == 1


@pytest.mark.asyncio
async def test_update_nonexistent_returns_false(db):
    ok = await db.async_update_transaction_category(999999, "Groceries")
    assert ok is False


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_transaction(db):
    tx_id, _ = await add(db)
    assert await db.async_delete_transaction(tx_id) is True
    assert await db.async_get_transaction(tx_id) is None


# ── Aggregates ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spending_by_category(db):
    await add(db, desc="Tesco",     amount=-50.00, dt="2026-05-01", category="Groceries")
    await add(db, desc="Sainsbury", amount=-30.00, dt="2026-05-10", category="Groceries")
    await add(db, desc="Netflix",   amount=-10.00, dt="2026-05-05", category="Subscriptions")
    rows = await db.async_get_spending_by_category("2026-05-01", "2026-05-31")
    totals = {r["category"]: r["total"] for r in rows}
    assert totals["Groceries"] == pytest.approx(-80.00)
    assert totals["Subscriptions"] == pytest.approx(-10.00)


@pytest.mark.asyncio
async def test_income_excluded_from_spending(db):
    await add(db, desc="Salary", amount=2000.00, dt="2026-05-01", category="Income")
    rows = await db.async_get_spending_by_category("2026-05-01", "2026-05-31")
    cats = [r["category"] for r in rows]
    assert "Income" not in cats


@pytest.mark.asyncio
async def test_monthly_total_net(db):
    await add(db, desc="Salary",     amount=2000.00, dt="2026-05-01")
    await add(db, desc="Supermarket", amount=-65.00,  dt="2026-05-10")
    total = await db.async_get_monthly_total(2026, 5)
    assert total == pytest.approx(1935.00)


# ── Category rules ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_creates_rule(db):
    await db.async_upsert_category_rule("Costa Coffee", "Dining & Takeaway")
    rules = await db.async_get_category_rules()
    assert any(r["pattern"] == "Costa Coffee" for r in rules)


@pytest.mark.asyncio
async def test_upsert_increments_match_count(db):
    await db.async_upsert_category_rule("Costa Coffee", "Dining & Takeaway")
    await db.async_upsert_category_rule("Costa Coffee", "Dining & Takeaway")
    rules = await db.async_get_category_rules()
    rule = next(r for r in rules if r["pattern"] == "Costa Coffee")
    assert rule["match_count"] == 2


@pytest.mark.asyncio
async def test_delete_rule(db):
    await db.async_upsert_category_rule("Amazon", "Shopping & Clothing")
    assert await db.async_delete_category_rule("Amazon") is True
    rules = await db.async_get_category_rules()
    assert not any(r["pattern"] == "Amazon" for r in rules)


# ── Field length caps ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_description_truncated_at_255(db):
    long_desc = "X" * 300
    tx_id, _ = await add(db, desc=long_desc)
    tx = await db.async_get_transaction(tx_id)
    assert len(tx["description"]) <= 255


@pytest.mark.asyncio
async def test_category_truncated_at_60(db):
    long_cat = "C" * 100
    tx_id, _ = await add(db, category=long_cat)
    tx = await db.async_get_transaction(tx_id)
    assert len(tx["category"]) <= 60
